"""共享的受限 Wiki 阅读工具循环：模型以结构化 JSON 动作 read/search/final 驱动，
程序验证动作与路径、固定步数与内容预算；不做通用 Agent 平台。"""
from __future__ import annotations

import json
import re
from typing import Awaitable, Callable

from ..llm.provider import LLMError
from ..wiki.tools import ToolBudgetExceeded, ToolError, WikiTools

# 流式事件：{"type":"reasoning","text":...} / {"type":"action",...} / {"type":"retry"}
EventSink = Callable[[dict], Awaitable[None]]

TOOL_SYSTEM = (
    "你是一个受限的 Wiki 阅读助手。你只能通过 JSON 动作与系统交互，每个动作是一个 JSON 对象，"
    "每次只输出一个 JSON 对象，不要输出任何其他文字。可用动作：\n"
    '  {"action":"index"} —— 读取 index.md 导航入口。\n'
    '  {"action":"list"} —— 列出所有页面路径与标题。\n'
    '  {"action":"read","path":"<dir>/<slug>.md"} —— 读取一个已知页面。\n'
    '  {"action":"search","query":"<关键词>"} —— 关键词搜索页面。\n'
    '  {"action":"final", ...} —— 结束并给出最终结果（字段见任务说明）。\n'
    "只能读 concepts/entities/projects/sources/analyses 目录下已存在的 .md 页面；"
    "不得读取、写入任何其他文件、目录、网络或执行命令。"
)


def _strip_fences(text: str) -> str:
    text = (text or "").strip()
    if text.startswith("```"):
        text = text.strip("`")
        nl = text.find("\n")
        if nl != -1 and text[:nl].strip().lower() in ("json",):
            text = text[nl + 1 :]
    return text.strip()


def _parse_action(resp: str) -> dict:
    text = _strip_fences(resp)
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start == -1:
            raise LLMError("模型输出不是有效 JSON 动作")
        try:
            data = json.loads(text[start : end + 1])
        except json.JSONDecodeError as e:
            raise LLMError("模型输出 JSON 无法解析") from e
    if not isinstance(data, dict):
        raise LLMError("模型动作必须是 JSON 对象")
    return data


def _execute(action: dict, tools: WikiTools) -> dict:
    kind = action.get("action")
    if kind == "index":
        return tools.read_index()
    if kind == "list":
        return tools.list_pages()
    if kind == "read":
        try:
            return tools.read_page(str(action.get("path") or ""))
        except ToolBudgetExceeded:
            raise
        except ToolError as e:
            return {"path": action.get("path"), "error": str(e)}
    if kind == "search":
        return tools.search(str(action.get("query") or ""), limit=5)
    return {"error": "未知动作（只允许 list/read/search/final）"}


def _build_user(task: str, context: list[str], final_hint: str, remaining: int | None = None) -> str:
    parts = ["【任务】", task, "", "<已读内容>"]
    if context:
        parts.extend(context)
    else:
        parts.append("（尚未读取任何内容）")
    parts.append("</已读内容>")
    parts.append("")
    parts.append("现在输出下一步 JSON 动作。最终动作字段：" + final_hint)
    if remaining is not None and remaining <= 2:
        parts.append(f"【提醒】剩余动作步数仅 {remaining} 步：已能回答时必须立即输出 final，不要继续读取新页面。")
    return "\n".join(parts)


async def _complete(provider, system: str, user: str, *, max_tokens: int, on_event: EventSink | None) -> str:
    """优先走流式（推理增量实时回调）；提供方不支持时退化为一次性调用。"""
    stream = getattr(provider, "stream_complete", None)
    if stream is None:
        return await provider.complete(system, user, json_mode=True, max_tokens=max_tokens)
    on_reasoning: Callable[[str], Awaitable[None]] | None = None
    if on_event is not None:
        async def forward(text: str) -> None:
            await on_event({"type": "reasoning", "text": text})

        on_reasoning = forward
    return await stream(system, user, json_mode=True, max_tokens=max_tokens, on_reasoning=on_reasoning)


async def run_tool_loop(
    provider,
    *,
    tools: WikiTools,
    task: str,
    final_hint: str,
    max_steps: int = 8,
    max_tokens: int = 2200,
    system: str = TOOL_SYSTEM,
    on_event: EventSink | None = None,
) -> dict:
    """执行受限阅读循环，返回 {final, read_pages}。超步数/超预算抛 LLMError（不写任何内容）。
    on_event 存在时实时上抛推理增量与工具动作（只读轨迹，不含任何写入）。"""
    context: list[str] = []
    # 预载 index 作为初始阅读上下文（安全且预算内），再由模型决定 read/search；空库给真实空索引。
    try:
        context.append(json.dumps(tools.read_index(), ensure_ascii=False))
    except ToolBudgetExceeded:
        raise  # 索引预载超预算必须失败，不假成功
    except ToolError:
        pass  # 索引缺失/非法：不预载，模型仍可 list/read/search
    parse_failures = 0
    steps = 0
    while steps < max_steps:
        user = _build_user(task, context, final_hint, remaining=max_steps - steps)
        resp = await _complete(provider, system, user, max_tokens=max_tokens, on_event=on_event)
        try:
            action = _parse_action(resp)
        except LLMError as e:
            # 模型偶尔不按 JSON 协议输出：回灌纠错提示重试（不占工具步数），超过上限才失败（不静默降级）
            parse_failures += 1
            if parse_failures > 2:
                raise
            if on_event is not None:
                await on_event({"type": "retry"})
            context.append(
                json.dumps(
                    {
                        "error": f"上一条输出不是有效 JSON 动作（{e}）。请只输出一个 JSON 对象，"
                        "可用动作：index / list / read / search / final。"
                    },
                    ensure_ascii=False,
                )
            )
            continue
        parse_failures = 0
        steps += 1
        if action.get("action") == "final":
            return {"final": action, "read_pages": sorted(tools.read_pages)}
        if on_event is not None:
            event = {"type": "action", "action": str(action.get("action") or "")}
            if action.get("path"):
                event["path"] = str(action["path"])
            if action.get("query"):
                event["query"] = str(action["query"])
            await on_event(event)
        result = _execute(action, tools)
        context.append(json.dumps(result, ensure_ascii=False))
    # 步数用尽仍不收口：给一次只允许 final 的机会；模型仍不配合则失败（不静默降级、不返回残缺答案）。
    user = _build_user(task, context, final_hint, remaining=0)
    user += "\n【最后机会】动作步数已用尽，现在必须直接输出一个 final JSON 动作（字段：" + final_hint + "），不得再输出其他动作。"
    try:
        action = _parse_action(await _complete(provider, system, user, max_tokens=max_tokens, on_event=on_event))
    except LLMError:
        raise LLMError("工具循环超过步数上限，已中止") from None
    if action.get("action") == "final" and len(action) > 1:
        return {"final": action, "read_pages": sorted(tools.read_pages)}
    raise LLMError("工具循环超过步数上限，已中止")
