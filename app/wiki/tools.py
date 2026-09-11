"""受限 Wiki 只读工具：列目录 / 读页面 / search-text（BM25 本地增强）。

只允许知识目录（concepts/entities/projects/sources/analyses）内已存在的 Markdown：
拒绝绝对路径、``..``、编码绕过、符号链接逃逸、目录外、Private Raw、秘密与任意网络/shell。
读取受内容预算限制；超预算明确失败，不假成功。"""
from __future__ import annotations

import json
from pathlib import Path

from .. import db
from ..config import Settings
from ..query import bm25
from ..security import redactor
from ..security.policy import PolicyStore

ALLOWED_DIRS = ("concepts", "entities", "projects", "sources", "analyses")


class ToolError(Exception):
    """工具错误（路径非法 / 页面不存在 / 超预算）。"""


class ToolBudgetExceeded(ToolError):
    """读取内容预算超限：必须明确失败，不假成功。"""


def _load_pages(settings: Settings, policy: dict | None = None) -> list[dict]:
    """从 Markdown 事实源读取已脱敏页面（title/content），始终与磁盘一致。"""
    from ..query import index as file_index

    return file_index._pages(settings, policy)


def _safe_page(settings: Settings, raw: str) -> Path:
    """严格校验并解析页面相对路径，返回 wiki_dir 内的真实文件。"""
    s = (raw or "").strip()
    if not s:
        raise ToolError("页面路径为空")
    # 拒绝任何编码/绝对/反斜杠/点段/非法字符；只接受 dir/slug.md
    if "%" in s or "\\" in s or s.startswith("/") or ":" in s:
        raise ToolError("页面路径非法")
    parts = s.split("/")
    if len(parts) != 2 or not s.endswith(".md"):
        raise ToolError("页面路径非法")
    directory, filename = parts
    if directory not in ALLOWED_DIRS or filename in ("", ".", ".."):
        raise ToolError("页面路径非法")
    # 目录内 slug 只能是安全字符；杜绝 .. / 符号链接名 / 隐写点段
    for seg in (directory, filename[:-3]):
        if not seg or not all(ch.isalnum() or ch in "-_" for ch in seg):
            raise ToolError("页面路径非法")
    root = settings.wiki_dir.resolve()
    target = (root / s).resolve()
    if not target.is_relative_to(root):
        raise ToolError("页面路径越界")
    if not target.is_file():
        raise ToolError("页面不存在")
    return target


class WikiTools:
    """共享的受限阅读上下文：跟踪已读页面与读取预算。"""

    def __init__(self, settings: Settings, *, max_read_chars: int = 60_000) -> None:
        self.settings = settings
        self.max_read_chars = max_read_chars
        self.used_chars = 0
        self.read_pages: set[str] = set()
        self._pages: list[dict] | None = None
        self._safe_paths: set[str] | None = None
        self._bm25: bm25.BM25 | None = None

    def _scrub(self, text: str) -> str:
        """进入知识模型前按本次真实安全策略 + 已登记引用集合检查。
        发现未处置敏感内容即安全替换（保留合法登记引用）；基础检测失败抛错阻断。"""
        policy = PolicyStore(self.settings.policy_file).load()
        valid = redactor.registered_refs(db.all_source_refs())
        clean, _ = redactor.sanitize_llm_output(text, policy=policy, valid=valid, safe_wiki_paths=self._link_safe_paths())
        return clean

    def _link_safe_paths(self) -> set[str]:
        """链接目标免检白名单：只信任磁盘上真实存在、根目录内的 Wiki 页面路径。"""
        if self._safe_paths is None:
            from ..query import index as file_index

            self._safe_paths = file_index.real_page_paths(self.settings)
        return self._safe_paths

    def _page_index(self) -> list[dict]:
        if self._pages is None:
            policy = PolicyStore(self.settings.policy_file).load()
            self._pages = _load_pages(self.settings, policy)
        return self._pages

    def list_pages(self) -> dict:
        pages = self._page_index()
        return {
            "pages": [{"path": p["path"], "title": self._scrub(p.get("title", "") or "")} for p in pages],
        }

    def read_index(self) -> dict:
        """读 index.md 导航入口（固定文件，不在 ALLOWED_DIRS 页面内）。
        resolve 后限制在知识根目录内，拒绝符号链接逃逸。"""
        root = self.settings.wiki_dir.resolve()
        p = (root / "index.md").resolve()
        if not p.is_relative_to(root):
            raise ToolError("index 越界")
        content = p.read_text(encoding="utf-8", errors="replace") if p.is_file() else ""
        self.used_chars += len(content)
        if self.used_chars > self.max_read_chars:
            raise ToolBudgetExceeded("读取内容超过预算，已中止")
        return {"path": "index.md", "content": self._scrub(content)}

    def read_page(self, path: str) -> dict:
        target = _safe_page(self.settings, path)
        content = target.read_text(encoding="utf-8", errors="replace")
        self.used_chars += len(content)
        if self.used_chars > self.max_read_chars:
            raise ToolBudgetExceeded("读取内容超过预算，已中止")
        self.read_pages.add(path)
        return {"path": path, "content": self._scrub(content)}

    def search(self, query: str, limit: int = 5) -> dict:
        if self._bm25 is None:
            self._bm25 = bm25.BM25(self._page_index())
        hits = self._bm25.search(query, limit=limit)
        out = []
        for h in hits:
            content = h.get("content", "") or ""
            self.used_chars += len(content)
            if self.used_chars > self.max_read_chars:
                raise ToolBudgetExceeded("读取内容超过预算，已中止")
            self.read_pages.add(h["path"])
            out.append({"path": h["path"], "title": self._scrub(h.get("title", "") or ""), "content": self._scrub(content)})
        return {"results": out}

    def serialize(self) -> str:
        return json.dumps({"read_pages": sorted(self.read_pages)}, ensure_ascii=False)
