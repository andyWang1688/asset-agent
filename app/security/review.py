"""本机人工审查：仅解密待确认载荷；不读取 Private Raw、不调用模型、不持久化原文。"""
from dataclasses import replace

from .. import db
from ..crypto import sha256_hex
from ..ingest.finalize import validate_decisions
from . import entries, submissions
from .rules import Finding


def resolve_findings(payload, manual=None):
    """人工补标只接受原文坐标。包含的自动命中并入新标记，部分重叠拒绝。"""
    groups = {
        "document": [submissions.finding_from_dict(f) for f in payload.get("findings", [])],
        "instruction": [submissions.finding_from_dict(f) for f in payload.get("instruction_findings", [])],
    }
    spans = {"document": [], "instruction": []}
    if len(manual or []) > 1000:
        raise submissions.SubmissionError("手动标记过多，请分批导入")
    for item in manual or []:
        source, start, end = item.get("source"), item.get("start"), item.get("end")
        original_source = source
        document = next((d for d in payload.get("documents", []) if d["id"] == source), None)
        if document:
            if type(start) is not int or type(end) is not int or not document["start"] <= start < end <= document["end"]:
                raise submissions.SubmissionError("选区超出文件范围")
            source = "document"
        if source not in groups:
            raise submissions.SubmissionError("未知审查来源")
        text = payload["text"] if source == "document" else payload.get("instruction", "")
        if type(start) is not int or type(end) is not int or not 0 <= start < end <= len(text) or not text[start:end].strip():
            raise submissions.SubmissionError("选区无效，请重新选择")
        if any(start < b and end > a for a, b in spans[source]):
            raise submissions.SubmissionError("手动选区不能重叠")
        if source == 'document' and payload.get('documents') and not any(
                d['start'] <= start < end <= d['end'] for d in payload['documents']):
            raise submissions.SubmissionError("选区不能跨文件")
        spans[source].append((start, end))
        remaining = []
        for f in groups[source]:
            if start < f.end and end > f.start:
                if not (start <= f.start and end >= f.end):
                    raise submissions.SubmissionError("选区与已有标记部分重叠，请选择完整标记")
            else:
                remaining.append(f)
        remaining.append(Finding(
            id=f"manual:{original_source}:{start}:{end}", kind="unknown_suspect", rule="manual",
            span=(start, end), confidence=1.0, evidence="用户手动保护",
            suggested_action="store", detector="manual", value=text[start:end],
            key_hint="手动保护内容",
        ))
        groups[source] = remaining
    return groups["document"], groups["instruction"]


def load(settings, submission_id, session_id):
    row = db.get_submission(submission_id)
    if not row or row["status"] != "waiting":
        raise submissions.SubmissionError("提交不存在或已处理")
    if row["session_id"] != session_id or db.session_mode(session_id) != db.SESSION_MAINTAIN:
        raise submissions.SubmissionError("仅所属维护会话可以审查")
    return row, submissions._decrypt(settings, row)


def range_preview(text, start, end, all_entries, preview_spans=None):
    local = []
    for entry in all_entries:
        f = entry.finding
        if start < f.end and end > f.start:
            local.append(replace(entry, finding=replace(f, span=(max(0, f.start-start), min(end, f.end)-start))))
    result, _ = entries.apply_entries(text[start:end], local, repeated_entries=all_entries, preview_spans=preview_spans)
    return result


def inspect(settings, policy_store, submission_id, session_id, decisions=None, edits=None, manual=None):
    _, payload = load(settings, submission_id, session_id)
    findings, instruction_findings = resolve_findings(payload, manual)
    combined = findings + instruction_findings
    dec = validate_decisions(combined, decisions)
    sources = {f.id: "整理要求" for f in instruction_findings}
    file_entries, instr_entries = entries.build_all_entries(
        findings, instruction_findings, dec, edits, namespace=payload["sha256"],
        policy=payload.get("policy") or policy_store.load(), sources=sources, documents=payload.get("documents"),
    )
    return {
        "documents": build_documents(payload, file_entries, instr_entries),
        "findings": [{
            "id": e.finding.id, "source": "instruction" if e.source else "document",
            "start": e.finding.start, "end": e.finding.end,
            "name": e.name, "description": e.description, "action": e.action,
            "private_ref": entries._placeholder(e),
        } for e in file_entries + instr_entries],
        "revision": sha256_hex(payload["text"] + payload.get("instruction", "")),
    }


def build_documents(payload, file_entries, instr_entries):
    if payload.get("documents"):
        result = []
        for doc in payload["documents"]:
            start, end = doc["start"], doc["end"]
            local = [replace(e, finding=replace(e.finding, span=(e.finding.start-start, e.finding.end-start)))
                     for e in file_entries if start <= e.finding.start < e.finding.end <= end]
            part = build_documents({"text": payload["text"][start:end], "review_layout": doc["layout"]}, local, [])[0]
            part.update(id=doc["id"], name=doc["name"])
            for unit in part["units"]:
                unit.update(start=unit["start"]+start, end=unit["end"]+start)
                unit["id"] = f"{doc['id']}:{unit['start']}:{unit['end']}"
            result.append(part)
        if payload.get("instruction"):
            result.extend(build_documents({"text": "", "instruction": payload["instruction"]}, [], instr_entries))
        return result
    result = []
    for source, text, group in (("document", payload["text"], file_entries),
                                 ("instruction", payload.get("instruction", ""), instr_entries)):
        if not text:
            continue
        layout = payload.get("review_layout", []) if source == "document" else []
        units = []
        if layout:
            for sheet_no, sheet in enumerate(layout):
                for cell in sheet["cells"]:
                    units.append({**cell, "sheet": sheet_no})
                if "title_start" in sheet:
                    units.append({"start": sheet["title_start"], "end": sheet["title_end"], "sheet": sheet_no, "row": 0, "col": 0})
        else:
            offset = 0
            for line in text.splitlines(keepends=True):
                units.append({"start": offset, "end": offset + len(line), "row": len(units)+1, "col": 0, "sheet": 0})
                offset += len(line)
        for unit in units:
            a, b = unit["start"], unit["end"]
            preview_spans = []
            unit.update(id=f"{source}:{a}:{b}", text=text[a:b],
                        preview=range_preview(text, a, b, group, preview_spans), preview_spans=preview_spans,
                        finding_ids=[e.finding.id for e in group if a < e.finding.end and b > e.finding.start])
        preview, _ = entries.apply_entries(text, group)
        result.append({"id": source, "name": "资料正文" if source == "document" else "整理要求",
                       "text": text, "preview": preview, "units": units,
                       "sheets": [{"name": s["name"]} for s in layout]})
    return result


def readback_snapshot(payload, file_entries, instr_entries, edited_text=None):
    """只保存裁决后的文本与布局，不附带原文副本；明确放行的值保持原样。"""
    if edited_text is not None:
        # 自由编辑会破坏坐标；调用者必须先完成复扫，再保存为普通文本。
        payload = {**payload, "text": edited_text, "review_layout": [], "documents": []}
        file_entries = []
    documents = []
    for doc in build_documents(payload, file_entries, instr_entries):
        units = [{key: unit[key] for key in (
            "id", "preview", "preview_spans", "finding_ids", "row", "col", "sheet"
        )} for unit in doc["units"]]
        sheets = [{"name": next((u["preview"] for u in units if u["sheet"] == i and u["row"] == 0),
                                f"工作表 {i + 1}")}
                  for i in range(len(doc["sheets"]))]
        documents.append({"id": doc["id"], "name": doc["name"], "preview": doc["preview"],
                          "units": units, "sheets": sheets})
    return {"documents": documents}
