"""安全报告：固定格式处理文档的程序化生成。

报告字段（与 ADR-0010 一致）：敏感类型、可读名称、说明、来源、保存动作、
保险柜条目/字段、私密引用、脱敏预览。报告由程序规则生成（无安全模型时完整可用），
可选安全模型只补充识别与字段；报告本身绝不含秘密原文。
"""
from ..security import entries as entries_mod
from ..security.rules import KINDS


def _summary(findings) -> dict:
    out = {k: 0 for k in KINDS}
    for f in findings:
        out[f.kind] = out.get(f.kind, 0) + 1
    return out


def build_report(entries, original_name: str, preview: str, instruction: str = "",
                 refs: list | None = None) -> dict:
    """生成报告结构（summary/entries/preview/instruction）。entries 为已解析条目
    （含来源定位），与落盘/写保险柜同源；refs 为 finalize 返回的保险柜引用。"""
    refs_by_id = {r.get("finding_id"): r for r in (refs or []) if r.get("finding_id")}

    report_entries = []
    for e in entries:
        entry = entries_mod.entry_to_report(e)
        entry["source"] = e.source or original_name
        r = refs_by_id.get(e.finding.id)
        if r:
            entry["vault"].update(
                {
                    "item_id": r.get("item_id") or None,
                    "saved": bool(r.get("saved", False)),
                    "pending_id": r.get("pending_id") or None,
                }
            )
        report_entries.append(entry)
    return {
        "summary": _summary([e.finding for e in entries]),
        "entries": report_entries,
        "preview": preview,
        "instruction": instruction,
    }
