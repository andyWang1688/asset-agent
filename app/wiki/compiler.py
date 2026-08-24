"""Wiki 编译服务：脱敏资料 → LLM 维护计划（JSON）→ Markdown 页面 + FTS5 索引。
路径白名单校验，LLM 输出再次扫描秘密，index/log 由系统确定性维护。"""
import json
import re
from datetime import datetime
from pathlib import Path

from .. import db
from ..config import Settings
from ..llm.provider import LLMError, LLMProvider
from ..security import redactor
from ..security.policy import PolicyStore

ALLOWED_DIRS = ("concepts", "entities", "projects", "sources", "analyses")
MAX_PAGE_CHARS = 3000
LOG_TAIL_CHARS = 4000


def wiki_system_prompt(settings: Settings) -> str:
    parts = []
    if settings.schema_file.exists():
        parts.append(settings.schema_file.read_text(encoding="utf-8"))
    # 安全策略只读注入：Wiki 模型只能读取，不能修改（策略校验保证不含秘密）
    try:
        policy_yaml = PolicyStore(settings.policy_file).dump()
        parts.append(
            "\n## 安全策略（只读，系统级约束，不可修改）\n"
            "以下策略由系统维护，模型只能遵守，不得改变或要求改变：\n\n"
            "```yaml\n" + policy_yaml + "\n```\n"
        )
    except OSError:
        pass
    return "\n".join(p for p in parts if p)


def safe_wiki_path(raw: str) -> Path:
    p = (raw or "").strip()
    if not p.endswith(".md") or "\\" in p or ".." in p or p.startswith("/"):
        raise ValueError(f"非法页面路径: {raw}")
    parts = p.split("/")
    if len(parts) < 2 or parts[0] not in ALLOWED_DIRS:
        raise ValueError(f"页面必须位于 {ALLOWED_DIRS} 子目录: {raw}")
    return Path(p)


def _list_pages(settings: Settings) -> list[dict]:
    pages = []
    for sub in ALLOWED_DIRS:
        for f in sorted((settings.wiki_dir / sub).glob("*.md")):
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


def _bigrams(s: str) -> set:
    return {s[i : i + 2] for i in range(len(s) - 1)}


def _pick_candidates(settings: Settings, text: str, limit: int = 5) -> list[dict]:
    src = _bigrams(text.lower())
    scored = []
    for p in _list_pages(settings):
        try:
            content = (settings.wiki_dir / p["path"]).read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        common = len(src & _bigrams((p["title"] + " " + content[:2000]).lower()))
        scored.append((common, p, content))
    scored.sort(key=lambda x: -x[0])
    return [
        {"path": p["path"], "title": p["title"], "content": c[:MAX_PAGE_CHARS]}
        for _, p, c in scored[:limit]
    ]


def _prompt_compile(settings: Settings, text: str, source_row) -> str:
    try:
        index = (settings.wiki_dir / "index.md").read_text(encoding="utf-8")
    except OSError:
        index = ""
    try:
        log = (settings.wiki_dir / "log.md").read_text(encoding="utf-8")[-LOG_TAIL_CHARS:]
    except OSError:
        log = ""
    candidates = _pick_candidates(settings, text)
    pages_all = _list_pages(settings)

    parts = [
        "【编译任务】",
        "请根据下方新资料与现有 Wiki 状态，输出一个 JSON 维护计划（严格 JSON，不要任何其他文字）。",
        "",
        "<现有索引>",
        index,
        "</现有索引>",
        "",
        "<最近变更日志>",
        log,
        "</最近变更日志>",
        "",
        "<全部现有页面路径>",
        ", ".join(p["path"] for p in pages_all) or "（空）",
        "</全部现有页面路径>",
        "",
        "<相关现有页面>",
    ]
    for c in candidates:
        parts.append(f"## 路径: {c['path']}（标题: {c['title']}）")
        parts.append(c["content"])
        parts.append("")
    parts.append("</相关现有页面>")
    parts.append("")
    parts.append("<新资料>")
    parts.append(text)
    parts.append("</新资料>")
    parts.append("")
    parts.append("JSON 结构：")
    parts.append(
        json.dumps(
            {
                "source_summary": {
                    "title": "来源标题",
                    "path": f"sources/{datetime.now():%Y-%m-%d}-<主题>.md",
                    "content": "来源摘要页完整 Markdown（含引用位置）",
                },
                "pages": [
                    {
                        "action": "create 或 update",
                        "path": "<allowed_dir>/<slug>.md",
                        "title": "页面标题",
                        "content": "页面完整 Markdown",
                    }
                ],
                "conflicts": [{"between": ["路径1", "路径2"], "note": "冲突说明"}],
            },
            ensure_ascii=False,
        )
    )
    parts.append("path 只能位于 concepts/entities/projects/sources/analyses 子目录、小写连字符、.md 结尾；同主题更新已有页面（update），不要新建重复页；页面间用 [[path|标题]] 互链；资料中的 [SECRET_REF:xxx] 原样保留。")
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
    system = wiki_system_prompt(settings)
    user = _prompt_compile(settings, text, source_row)
    resp = await provider.complete(system, user, json_mode=True, max_tokens=8000)
    plan = parse_json_plan(resp)
    return apply_plan(settings, plan, source_row["id"])


def apply_plan(settings: Settings, plan: dict, source_id: int) -> dict:
    changes: list[str] = []
    conflicts: list[dict] = []
    seen: set[str] = set()

    summary = plan.get("source_summary") or {}
    if summary:
        path = safe_wiki_path(summary.get("path") or f"sources/{datetime.now():%Y-%m-%d}-source.md")
        content, hits = redactor.sanitize_llm_output(summary.get("content") or "")
        title, title_hits = redactor.sanitize_llm_output(summary.get("title") or "")
        if hits or title_hits:
            db.log_security("llm_output_secret", f"来源摘要页 {path} 命中规则 {hits + title_hits}，片段已删除")
        _write_page(settings, path, title or str(path).split("/")[-1][:-3], content)
        seen.add(str(path))
        changes.append(str(path))

    for page in plan.get("pages") or []:
        path = safe_wiki_path(page.get("path") or "")
        content, hits = redactor.sanitize_llm_output(page.get("content") or "")
        title, title_hits = redactor.sanitize_llm_output(page.get("title") or "")
        if hits or title_hits:
            db.log_security("llm_output_secret", f"页面 {path} 命中规则 {hits + title_hits}，片段已删除")
        _write_page(settings, path, title or str(path).split("/")[-1][:-3], content)
        seen.add(str(path))
        changes.append(str(path))

    for c in plan.get("conflicts") or []:
        note, note_hits = redactor.sanitize_llm_output(c.get("note") or "")
        if note_hits:
            db.log_security("llm_output_secret", f"冲突说明命中规则 {note_hits}，片段已删除")
        conflicts.append({"between": c.get("between") or [], "note": note})

    rebuild_index(settings)
    append_log(settings, source_id, changes, conflicts)
    return {"changes": changes, "conflicts": conflicts}


def _write_page(settings: Settings, path: Path, title: str, content: str) -> None:
    target = settings.wiki_dir / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    db.upsert_page(str(path), title, content)


def rebuild_index(settings: Settings) -> None:
    lines = ["# Wiki 索引", "", "> 本文件由系统自动维护，人工修改会被覆盖。", ""]
    groups: dict[str, list[str]] = {}
    for p in sorted(_list_pages(settings), key=lambda x: x["path"]):
        groups.setdefault(p["path"].split("/")[0], []).append(f'- [{p["title"]}]({p["path"]})')
    for d in ALLOWED_DIRS:
        lines.append(f"## {d}")
        lines.extend(groups.get(d) or ["- （暂无）"])
        lines.append("")
    (settings.wiki_dir / "index.md").write_text("\n".join(lines), encoding="utf-8")
    # 文件级查询索引是 Markdown 的派生物，与 Wiki 导航索引一起全量更新。
    from ..query import index as query_index

    query_index.build(settings)
    # 向量模式与 FTS5 并存；仅在显式启用时构建 embedding，默认本地执行。
    if getattr(settings, "query_engine", "fts5") == "vector":
        from ..query import vector as vector_index

        vector_index.build(settings)


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
    with (settings.wiki_dir / "log.md").open("a", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n\n")
