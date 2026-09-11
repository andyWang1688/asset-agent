"""独立 BM25 关键词检索：纯 Python，不装载 torch / 向量模型。

作为受限 search-text 工具的本地增强实现，直接对脱敏后的 Wiki 页面打分，
不依赖 LlamaIndex / embedding / 重排。"""
from __future__ import annotations

import math
import re

_TOKEN_RE = re.compile(r"(?u)[a-zA-Z0-9_]+|[\u4e00-\u9fff]")


def _tokens(text: str) -> list[str]:
    return [t.lower() for t in _TOKEN_RE.findall(text or "")]


class BM25:
    """Okapi BM25，文档为 {path,title,content}。"""

    def __init__(self, docs: list[dict], *, k1: float = 1.5, b: float = 0.75) -> None:
        self.docs = docs
        self.k1 = k1
        self.b = b
        self.n = len(docs)
        self.doc_tokens = [_tokens((d.get("title", "") or "") + "\n" + (d.get("content", "") or "")) for d in docs]
        self.doc_len = [len(t) for t in self.doc_tokens]
        self.avgdl = (sum(self.doc_len) / self.n) if self.n else 0.0
        self.df: dict[str, int] = {}
        for toks in self.doc_tokens:
            for term in set(toks):
                self.df[term] = self.df.get(term, 0) + 1

    def _score(self, query_terms: list[str], doc_index: int) -> float:
        toks = self.doc_tokens[doc_index]
        tf: dict[str, int] = {}
        for t in toks:
            tf[t] = tf.get(t, 0) + 1
        dl = self.doc_len[doc_index] or 1
        total = 0.0
        for term in query_terms:
            df = self.df.get(term, 0)
            if not df:
                continue
            idf = math.log(1.0 + (self.n - df + 0.5) / (df + 0.5))
            f = tf.get(term, 0)
            total += idf * (f * (self.k1 + 1)) / (f + self.k1 * (1 - self.b + self.b * dl / max(1.0, self.avgdl)))
        return total

    def search(self, query: str, limit: int = 5) -> list[dict]:
        terms = _tokens(query)
        if not terms:
            return []
        scored = [(self._score(terms, i), self.docs[i]) for i in range(self.n)]
        scored = [(s, d) for s, d in scored if s > 0]
        scored.sort(key=lambda x: -x[0])
        return [d for _, d in scored[:limit]]
