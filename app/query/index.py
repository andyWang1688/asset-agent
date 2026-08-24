"""Markdown Wiki 的文件级派生索引。

Markdown 目录是事实源；此 JSON 文件和 SQLite 页表都可以删除，再从目录完整重建。
"""
import json
import os
from pathlib import Path

from .. import db
from ..security import redactor

ALLOWED_DIRS = ("concepts", "entities", "projects", "sources", "analyses")
INDEX_FILENAME = "wiki-index.json"


def index_path(settings) -> Path:
    return settings.data_dir / INDEX_FILENAME


def _pages(settings) -> list[dict]:
    pages = []
    for directory in ALLOWED_DIRS:
        for path in sorted((settings.wiki_dir / directory).glob("*.md")):
            rel = f"{directory}/{path.name}"
            try:
                raw = path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            title = path.stem
            for line in raw.splitlines():
                if line.startswith("# "):
                    title = line[2:].strip() or title
                    break
            # Wiki 内容应已脱敏；这里再做一次边界防护，确保派生索引不保存秘密原文。
            content, _ = redactor.sanitize_llm_output(raw)
            title, _ = redactor.sanitize_llm_output(title)
            pages.append({"path": rel, "title": title, "content": content})
    return pages


def build(settings) -> dict:
    """从 Markdown 全量构建索引，并同步 SQLite 派生页表。"""
    pages = _pages(settings)
    target = index_path(settings)
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_suffix(target.suffix + ".tmp")
    temp.write_text(json.dumps({"version": 1, "pages": pages}, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temp, target)

    # pages_data 也是派生数据：清掉已从 Markdown 删除的页面后再完整写入。
    existing = {row["path"] for row in db.list_pages()}
    current = {page["path"] for page in pages}
    for path in existing - current:
        db.delete_page(path)
    for page in pages:
        db.upsert_page(page["path"], page["title"], page["content"])
    return {"path": str(target), "pages": len(pages)}


def rebuild(settings) -> dict:
    return build(settings)


def delete(settings) -> None:
    """删除派生索引文件，不触碰 Markdown 事实源。"""
    index_path(settings).unlink(missing_ok=True)


def load(settings) -> dict:
    try:
        return json.loads(index_path(settings).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"version": 1, "pages": []}


# 便于调用方按“索引构建器”语义命名。
build_index = build
rebuild_index = rebuild
delete_index = delete
