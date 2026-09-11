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


def real_page_paths(settings) -> set[str]:
    """返回知识根目录内真实存在的页面相对路径集合（`dir/slug.md`）。

    只包含磁盘上确实存在、resolve 后仍位于知识根目录内的 .md 页面；
    符号链接越界/目录外/缺失文件一律排除。供链接目标免检白名单使用。"""
    root = settings.wiki_dir.resolve()
    paths: set[str] = set()
    for directory in ALLOWED_DIRS:
        for path in sorted((settings.wiki_dir / directory).glob("*.md")):
            try:
                if not path.resolve().is_relative_to(root):
                    continue
            except OSError:
                continue
            if not path.is_file():
                continue
            paths.add(f"{directory}/{path.name}")
    return paths


def _pages(settings, policy: dict | None = None) -> list[dict]:
    safe_paths = real_page_paths(settings)
    pages = []
    for rel in sorted(safe_paths):
        path = settings.wiki_dir / rel
        try:
            raw = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        title = path.stem
        for line in raw.splitlines():
            if line.startswith("# "):
                title = line[2:].strip() or title
                break
        # Wiki 内容应已脱敏；只信任已确认来源登记的精确私密引用（跨来源更新保留），
        # 未登记引用仍按安全策略扫描，确保派生索引不保存秘密原文。
        valid = redactor.registered_refs(db.all_source_refs())
        content, _ = redactor.sanitize_llm_output(raw, policy=policy, valid=valid, safe_wiki_paths=safe_paths)
        title, _ = redactor.sanitize_llm_output(title)
        pages.append({"path": rel, "title": title, "content": content})
    return pages


def build(settings, policy: dict | None = None) -> dict:
    """从 Markdown 全量构建索引，并同步 SQLite 派生页表。"""
    pages = _pages(settings, policy)
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
