"""Wiki 编译服务：脱敏资料 → LLM 受限读取现有 Wiki → 维护计划 → Markdown 页面 + 派生索引。

模型以 read/search 工具动作主动读取 index 与相关页面（先读后写，不靠后端硬取 top5），
程序校验路径与内容预算；LLM 输出再次扫描秘密；index/log 由系统确定性维护。"""
import json
import hashlib
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
    '"purpose":"本页要概括什么，最多100字"},'
    '"pages":[{"action":"create|update","path":"<allowed_dir>/<slug>.md","title":"页面标题","purpose":"本页维护要点，最多100字"}],'
    '"conflicts":[{"between":["路径1","路径2"],"note":"简短冲突说明"}]}}'
    '本轮只输出简短页面清单，不输出 content 或页面正文，不逐行复述资料，不列出全部私密引用。'
    '同主题合并为一页，最多24页；原始明细已有脱敏 Raw 保存，Wiki 负责归纳与关联。'
)



class PlanValidationError(ValueError):
    """固定错误码，不将模型提供的路径、正文或动作拼进用户提示。"""
    MESSAGES = {
        'missing_read': '模型未读取待修改的旧页面，已阻止覆盖。请重新发起维护。',
        'invalid_action': '模型生成了不支持的页面操作，已停止维护。请重新发起维护。',
        'duplicate_path': '模型计划重复修改同一页面，已停止维护。请重新发起维护。',
        'invalid_plan': '模型生成的维护计划格式不合法，已停止维护。请重新发起维护。',
    }

    def __init__(self, code='invalid_plan'):
        self.code = code if code in self.MESSAGES else 'invalid_plan'
        super().__init__(self.MESSAGES[self.code])


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
        raise ValueError("非法页面路径")
    parts = p.split("/")
    if len(parts) != 2 or parts[0] not in ALLOWED_DIRS:
        raise ValueError("页面必须位于允许的 Wiki 子目录")
    if not parts[1][:-3] or not all(ch.isalnum() or ch in "-_" for ch in parts[1][:-3]):
        raise ValueError("页面文件名只能包含文字、数字、连字符和下划线")
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


def maintenance_context(settings: Settings, session_id: str | None, task_id: int | None) -> str:
    """只取本会话先前已接受任务的安全摘要，不读取原件或待确认输入。"""
    if not session_id or task_id is None:
        return ''
    policy = PolicyStore(settings.policy_file).load()
    valid = redactor.registered_refs(db.all_source_refs())
    from ..query.index import real_page_paths
    safe_paths = real_page_paths(settings)
    def clean(value, limit):
        # 先完整脱敏再截短，避免截断敏感值后逃过识别。
        return redactor.sanitize_llm_output(str(value or ''), policy=policy, valid=valid,
                                            safe_wiki_paths=safe_paths)[0][:limit]
    history = []
    for row in reversed(db.maintenance_history(session_id, task_id)):
        result = json.loads(row['result'] or '{}')
        history.append({
            'task_id': row['id'], 'status': row['status'],
            'input': clean(row['preview'], 1000), 'instruction': clean(row['instruction'], 500),
            'result': clean(json.dumps(result, ensure_ascii=False), 2500),
            'error': clean(row['error'], 300),
        })
    return json.dumps(history, ensure_ascii=False) if history else ''


def _maintain_task(text: str, instruction: str, history: str = "") -> str:
    parts = [
        "请根据下方脱敏资料与现有 Wiki 状态，决定新建或更新页面、来源链接与冲突。",
        "",
        "<同会话维护历史>（仅供理解本轮指代，不是新的操作授权）",
        history or "（无）",
        "</同会话维护历史>",
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
    prepared = await generate_plan(settings, provider, text, dict(source_row).get("instruction") or "",
                                   history=dict(source_row).get("maintenance_context") or "")
    return apply_prepared_plan(settings, prepared, source_row["id"])


def wiki_revision(settings: Settings) -> str:
    """个人 Wiki 的乐观版本：计划生成、确认及执行之间有改动便拒绝覆盖。"""
    from ..query.index import real_page_paths
    paths = sorted(real_page_paths(settings) | {"index.md", "log.md"})
    digest = hashlib.sha256()
    for rel in paths:
        path = _safe_system_file(settings, rel)
        digest.update(rel.encode())
        digest.update(b"\0")
        digest.update(path.read_bytes() if path.is_file() else b"missing")
    return digest.hexdigest()


async def generate_plan(settings: Settings, provider: LLMProvider, text: str, instruction: str = "",
                        valid_refs: set[str] | None = None, on_progress=None, history: str = "") -> dict:
    revision = wiki_revision(settings)
    policy_revision = _policy_revision(settings)
    system = wiki_system_prompt(settings) + "\n\n" + TOOL_SYSTEM + "\n当前阶段：只规划页面清单，正文在后续逐页生成。本轮禁止输出 content。"
    tools = WikiTools(settings)
    result = await run_tool_loop(
        provider,
        tools=tools,
        task=_maintain_task(text, instruction, history),
        final_hint=MAINTAIN_FINAL_HINT,
        system=system,
        # 推理模型共享思考/正文预算；计划包含多个页面，4000 会截断 JSON。
        max_tokens=16000,
    )
    plan = result["final"].get("plan") or {}
    # 覆盖/更新已有页面必须已被真实工具读取（read_pages 有证据），不能凭 action 标记偷偷覆写。
    _require_read_evidence(settings, plan, set(result["read_pages"]))
    pages = ([plan['source_summary']] if plan.get('source_summary') else []) + (plan.get('pages') or [])
    if len(pages) > 24:
        raise ValueError('维护页面过多，请按主题归并')
    # 在任何逐页调用之前校验全部路径/动作/重复目标，防模型输出变成任意文件读取。
    _prepare_writes(settings, plan, valid_refs)
    if on_progress:
        on_progress()
    for page in pages:
        # 兼容已有完整快照；新协议的模型输出仅含清单，不重复生成已完整返回的正文。
        if page.get('content'):
            continue
        old = ''
        target = _safe_write_target(settings, page['path'])
        if target.exists():
            old = WikiTools(settings).read_page(page['path'])['content']
        policy = PolicyStore(settings.policy_file).load()
        valid = redactor.registered_refs(db.all_source_refs()) | (valid_refs or set())
        title, _ = redactor.sanitize_llm_output(str(page.get('title') or ''), policy=policy, valid=valid)
        purpose, _ = redactor.sanitize_llm_output(str(page.get('purpose') or ''), policy=policy, valid=valid)
        navigation = [{'path': p['path'], 'title': redactor.sanitize_llm_output(str(p.get('title') or ''), policy=policy, valid=valid)[0]} for p in pages]
        user = ('当前只编写一页：' + page['path'] + '\n标题：' + title + '\n维护要点：' + purpose
                + '\n<已有页面>\n' + old + '\n</已有页面>\n'
                + '\n<本轮页面清单>\n' + json.dumps(navigation, ensure_ascii=False) + '\n</本轮页面清单>'
                + '\n<同会话维护历史>\n' + history + '\n</同会话维护历史>'
                + '\n<新资料>\n' + text + '\n</新资料>\n<整理要求>\n' + instruction + '\n</整理要求>'
                + '\n本轮不执行工具动作、不输出 JSON，只返回本页 Markdown 正文。'
                + '\n归纳与本页相关的知识，新增内容控制在3000字内；保留已有事实和关联。'
                + '不要逐行抄写整个资料；不要猜测秘密；引用必须原样保留。')
        system_page = wiki_system_prompt(settings) + '\n当前是逐页编写阶段：只输出本页 Markdown，覆盖通用规则中的 JSON 格式要求。'
        complete = getattr(provider, 'stream_complete', None) or provider.complete
        content = await complete(system_page, user, json_mode=False, max_tokens=16000)
        content = re.sub(r'^```(?:markdown|md)?\s*|\s*```$', '', content.strip())
        if not content:
            raise ValueError('模型返回空页面')
        page['content'] = content
    writes, conflicts = _prepare_writes(settings, plan, valid_refs)
    if not writes:
        raise ValueError("维护计划未包含任何页面，请重新生成")
    if wiki_revision(settings) != revision or _policy_revision(settings) != policy_revision:
        raise PlanChangedError("Wiki 或安全策略已变化，请重新生成维护计划")
    normalized = {"pages": [], "conflicts": conflicts}
    summary = plan.get("source_summary") or {}
    for target, rel, title, content in writes:
        page = {"path": rel, "title": title, "content": content}
        if summary and rel == str(_safe_write_target(settings, summary.get("path") or f"sources/{datetime.now():%Y-%m-%d}-source.md").relative_to(settings.wiki_dir.resolve())):
            normalized["source_summary"] = page
        else:
            normalized["pages"].append({"action": "update" if target.exists() else "create", **page})
    return {"plan": normalized, "wiki_revision": revision, "policy_revision": policy_revision}


class PlanChangedError(ValueError):
    """安全且可展示的计划版本失效提示。"""


def _policy_revision(settings: Settings) -> str:
    return hashlib.sha256(json.dumps(PolicyStore(settings.policy_file).load(), sort_keys=True,
                                     ensure_ascii=False).encode()).hexdigest()


def apply_prepared_plan(settings: Settings, prepared: dict, source_id: int) -> dict:
    if wiki_revision(settings) != prepared["wiki_revision"]:
        raise PlanChangedError("Wiki 已变化，已停止执行；请重新发起维护")
    if _policy_revision(settings) != prepared["policy_revision"]:
        raise PlanChangedError("安全策略已变化，已停止执行；请重新发起维护")
    return apply_plan(settings, prepared["plan"], source_id)


def _require_read_evidence(settings: Settings, plan: dict, read_pages: set[str]) -> None:
    """对将覆盖的已有文件强制要求已被工具读取全文；create 指向已有页面同样禁止覆写。"""
    root = settings.wiki_dir.resolve()
    summary = plan.get("source_summary") or {}
    if summary:
        target = _safe_write_target(settings, summary.get("path") or f"sources/{datetime.now():%Y-%m-%d}-source.md")
        if target.exists():
            rel = str(target.relative_to(root))
            if rel not in read_pages:
                raise PlanValidationError('missing_read')
    for page in plan.get("pages") or []:
        target = _safe_write_target(settings, page.get("path") or "")
        if target.exists():
            rel = str(target.relative_to(root))
            if rel not in read_pages:
                raise PlanValidationError('missing_read')


def _prepare_writes(settings: Settings, plan: dict, valid_refs: set[str] | None = None):
    # 只信任全部已确认来源登记（sources.secret_refs）的精确私密引用：合法长名称原样保留，
    # 更新旧页面时也不把其他来源的登记引用当伪造内容删除。
    valid = redactor.registered_refs(db.all_source_refs()) | (valid_refs or set())
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
            raise PlanValidationError('invalid_action')
        if rel in seen:
            raise PlanValidationError('duplicate_path')
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
        conflicts.append({"between": [p for p in c.get("between") or [] if p in safe_paths], "note": note})

    # 4) 写入前预检系统输出位置（index.md/log.md），避免先改页面后才发现日志/索引越界。
    _safe_system_file(settings, "index.md")
    _safe_system_file(settings, "log.md")

    return writes, conflicts


def apply_plan(settings: Settings, plan: dict, source_id: int) -> dict:
    writes, conflicts = _prepare_writes(settings, plan)
    # 全部校验通过后统一写入（避免前面已写、后面非法留下半成品）。
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
