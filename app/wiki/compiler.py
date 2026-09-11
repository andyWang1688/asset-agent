"""Wiki 编译服务：脱敏资料 → LLM 受限读取现有 Wiki → 维护计划 → Markdown 页面 + 派生索引。

模型以 read/search 工具动作主动读取 index 与相关页面（先读后写，不靠后端硬取 top5），
程序校验路径与内容预算；LLM 输出再次扫描秘密；index/log 由系统确定性维护。"""
import json
import re
from datetime import datetime
from pathlib import Path

from .. import db
from ..config import Settings
from ..llm.provider import LLMError, LLMProvider
from ..query.agent_loop import TOOL_SYSTEM, run_tool_loop
from ..security import redactor
from ..security.policy import PolicyStore
from .tools import WikiTools

ALLOWED_DIRS = ("concepts", "entities", "projects", "sources", "analyses")
MAX_PAGE_CHARS = 3000
LOG_TAIL_CHARS = 4000

MAINTAIN_FINAL_HINT = (
    '{"action":"final","plan":{"source_summary":{"title":"来源标题","path":"sources/<日期>-<主题>.md",'
    '"content":"来源摘要页完整 Markdown"},'
    '"pages":[{"action":"create|update","path":"<allowed_dir>/<slug>.md","title":"页面标题","content":"页面完整 Markdown"}],'
    '"conflicts":[{"between":["路径1","路径2"],"note":"冲突说明"}]}}'
)


def wiki_system_prompt(settings: Settings) -> str:
    """维护系统提示：schema 规则 + 受限工具说明。不注入完整用户安全策略 YAML
    （可能含用户自定义正则里的秘密常量），也不注入文件名/路径/模型错误正文。"""
    parts = []
    if settings.schema_file.exists():
        parts.append(settings.schema_file.read_text(encoding="utf-8"))
    parts.append(
        "资料中的 [🔒 名称](private:引用ID) 与 [REDACTED:规则] 是系统生成的安全占位符："
        "必须原样保留，不得还原、猜测或改动其中内容。"
    )
    return "\n".join(p for p in parts if p)


def safe_wiki_path(raw: str) -> Path:
    p = (raw or "").strip()
    if not p.endswith(".md") or "\\" in p or ".." in p or p.startswith("/"):
        raise ValueError(f"非法页面路径: {raw}")
    parts = p.split("/")
    if len(parts) < 2 or parts[0] not in ALLOWED_DIRS:
        raise ValueError(f"页面必须位于 {ALLOWED_DIRS} 子目录: {raw}")
    return Path(p)


def _safe_write_target(settings: Settings, raw: str) -> Path:
    """校验并解析写入目标：拒绝绝对/.. /编码/目录外/符号链接逃逸。"""
    p = safe_wiki_path(raw)  # 字符串级校验（抛 ValueError）
    root = settings.wiki_dir.resolve()
    target = (root / str(p)).resolve()
    if not target.is_relative_to(root):
        raise ValueError(f"页面路径越界: {raw}")
    return target


def _safe_system_file(settings: Settings, name: str) -> Path:
    """解析系统文件（index.md/log.md）的真实落点，拒绝符号链接逃逸。"""
    root = settings.wiki_dir.resolve()
    target = (root / name).resolve()
    if not target.is_relative_to(root):
        raise ValueError(f"系统文件越界: {name}")
    return target


def _list_pages(settings: Settings) -> list[dict]:
    pages = []
    root = settings.wiki_dir.resolve()
    for sub in ALLOWED_DIRS:
        for f in sorted((settings.wiki_dir / sub).glob("*.md")):
            try:
                if not f.resolve().is_relative_to(root):
                    continue  # 符号链接越界：跳过，不读取其内容
            except OSError:
                continue
            rel = f"{sub}/{f.name}"
            title = f.stem
            try:
                first = f.read_text(encoding="utf-8").splitlines()
                for line in first:
                    if line.startswith("# "):
                        title = line[2:].strip()
                        break
            except OSError:
                pass
            pages.append({"path": rel, "title": title})
    return pages


def _maintain_task(text: str, instruction: str) -> str:
    parts = [
        "请根据下方脱敏资料与现有 Wiki 状态，决定新建或更新页面、来源链接与冲突。",
        "",
        "<新资料>（已脱敏，秘密以占位符表示）",
        text,
        "</新资料>",
        "",
        "<整理要求>（已脱敏，空则无）",
        instruction or "（无）",
        "</整理要求>",
        "",
        "请先读取 index 与相关现有页面（read/search），避免只凭片段覆盖丢失旧内容，"
        "再 final 给出维护计划。同主题资料更新已有页面（update），不要新建重复页。",
    ]
    return "\n".join(parts)


def parse_json_plan(resp: str) -> dict:
    text = resp.strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start == -1:
            raise LLMError("模型输出不是有效 JSON")
        try:
            return json.loads(text[start : end + 1])
        except json.JSONDecodeError as e:
            raise LLMError("模型输出 JSON 无法解析") from e


async def compile_source(settings: Settings, provider: LLMProvider, source_row, text: str) -> dict:
    system = wiki_system_prompt(settings) + "\n\n" + TOOL_SYSTEM
    row = dict(source_row or {})
    instruction = row.get("instruction") or ""
    tools = WikiTools(settings)
    result = await run_tool_loop(
        provider,
        tools=tools,
        task=_maintain_task(text, instruction),
        final_hint=MAINTAIN_FINAL_HINT,
        system=system,
        max_tokens=4000,
    )
    plan = result["final"].get("plan") or {}
    # 覆盖/更新已有页面必须已被真实工具读取（read_pages 有证据），不能凭 action 标记偷偷覆写。
    _require_read_evidence(settings, plan, set(result["read_pages"]))
    return apply_plan(settings, plan, row["id"])


def _require_read_evidence(settings: Settings, plan: dict, read_pages: set[str]) -> None:
    """对将覆盖的已有文件强制要求已被工具读取全文；create 指向已有页面同样禁止覆写。"""
    root = settings.wiki_dir.resolve()
    summary = plan.get("source_summary") or {}
    if summary:
        target = _safe_write_target(settings, summary.get("path") or f"sources/{datetime.now():%Y-%m-%d}-source.md")
        if target.exists():
            rel = str(target.relative_to(root))
            if rel not in read_pages:
                raise ValueError(f"覆盖已有页面 {rel} 前必须已读取该页")
    for page in plan.get("pages") or []:
        target = _safe_write_target(settings, page.get("path") or "")
        if target.exists():
            rel = str(target.relative_to(root))
            if rel not in read_pages:
                raise ValueError(f"覆盖已有页面 {rel} 前必须已读取该页")


def apply_plan(settings: Settings, plan: dict, source_id: int) -> dict:
    # 只信任全部已确认来源登记（sources.secret_refs）的精确私密引用：合法长名称原样保留，
    # 更新旧页面时也不把其他来源的登记引用当伪造内容删除。
    valid = redactor.registered_refs(db.all_source_refs())
    policy = PolicyStore(settings.policy_file).load()
    root = settings.wiki_dir.resolve()

    # 1) 先整体校验整个计划（结构/路径/动作/重复路径），收集全部待写条目，任何非法项直接抛错。
    entries: list[dict] = []
    seen: set[str] = set()

    summary = plan.get("source_summary") or {}
    if summary:
        target = _safe_write_target(settings, summary.get("path") or f"sources/{datetime.now():%Y-%m-%d}-source.md")
        rel = str(target.relative_to(root))
        entries.append({
            "target": target, "rel": rel, "kind": "来源摘要页",
            "title": summary.get("title") or "", "content": summary.get("content") or "",
        })
        seen.add(rel)

    for page in plan.get("pages") or []:
        target = _safe_write_target(settings, page.get("path") or "")
        rel = str(target.relative_to(root))
        action = page.get("action")
        if action not in ("create", "update"):
            raise ValueError(f"非法页面动作: {action}")
        if rel in seen:
            raise ValueError(f"重复页面路径: {rel}")
        seen.add(rel)
        entries.append({
            "target": target, "rel": rel, "kind": "页面",
            "title": page.get("title") or "", "content": page.get("content") or "",
        })

    # 2) 链接目标免检白名单 = 磁盘真实存在的页面 ∪ 本轮已验证的待写页面路径。
    from ..query import index as query_index

    safe_paths = set(query_index.real_page_paths(settings)) | {e["rel"] for e in entries}

    # 3) 内容/标题脱敏。链接目标只在白名单内豁免，标签/正文仍完整扫描。
    writes: list[tuple[Path, str, str, str]] = []
    for e in entries:
        content, hits = redactor.sanitize_llm_output(e["content"], policy=policy, valid=valid, safe_wiki_paths=safe_paths)
        title, title_hits = redactor.sanitize_llm_output(e["title"], policy=policy, valid=valid)
        if hits or title_hits:
            db.log_security("llm_output_secret", f"{e['kind']} {e['rel']} 命中规则 {hits + title_hits}，片段已删除")
        writes.append((e["target"], e["rel"], title or e["rel"].split("/")[-1][:-3], content))

    conflicts: list[dict] = []
    for c in plan.get("conflicts") or []:
        note, note_hits = redactor.sanitize_llm_output(c.get("note") or "", policy=policy, valid=valid)
        if note_hits:
            db.log_security("llm_output_secret", f"冲突说明命中规则 {note_hits}，片段已删除")
        conflicts.append({"between": c.get("between") or [], "note": note})

    # 4) 写入前预检系统输出位置（index.md/log.md），避免先改页面后才发现日志/索引越界。
    _safe_system_file(settings, "index.md")
    _safe_system_file(settings, "log.md")

    # 5) 全部校验通过后统一写入（避免前面已写、后面非法留下半成品）。
    changes: list[str] = []
    for target, rel, title, content in writes:
        _write_page(settings, target, rel, title, content)
        changes.append(rel)

    rebuild_index(settings)
    append_log(settings, source_id, changes, conflicts)
    return {"changes": changes, "conflicts": conflicts}


def _write_page(settings: Settings, target: Path, rel: str, title: str, content: str) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    db.upsert_page(rel, title, content)


def rebuild_index(settings: Settings) -> None:
    lines = ["# Wiki 索引", "", "> 本文件由系统自动维护，人工修改会被覆盖。", ""]
    groups: dict[str, list[str]] = {}
    for p in sorted(_list_pages(settings), key=lambda x: x["path"]):
        groups.setdefault(p["path"].split("/")[0], []).append(f'- [{p["title"]}]({p["path"]})')
    for d in ALLOWED_DIRS:
        lines.append(f"## {d}")
        lines.extend(groups.get(d) or ["- （暂无）"])
        lines.append("")
    _safe_system_file(settings, "index.md").write_text("\n".join(lines), encoding="utf-8")
    # 文件级查询索引是 Markdown 的派生物，与 Wiki 导航索引一起全量更新。
    # 主链路（LLM Wiki）不使用向量/embedding/重排：不在此触发向量索引构建。
    from ..query import index as query_index

    query_index.build(settings)


def append_log(settings: Settings, source_id: int, changes: list[str], conflicts: list[dict]) -> None:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    lines = [
        f"## {now}",
        f"- 来源: #{source_id}",
        f"- 变更: {', '.join(changes) or '无'}",
    ]
    if conflicts:
        lines.append("- 冲突:")
        for c in conflicts:
            lines.append(f"  - {c['note']}（{', '.join(c['between'])}）")
    with _safe_system_file(settings, "log.md").open("a", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n\n")
