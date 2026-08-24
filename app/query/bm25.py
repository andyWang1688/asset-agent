"""轻量 BM25 关键词检索（无第三方依赖），供混合召回的关键词支路使用。

中文按字符 bigram 切词（与本地 hash embedding 的特征口径一致），ASCII 词元单独成词。
语料即 sanitized 的派生索引页面，不存在额外的持久层。
"""

from __future__ import annotations

import math
import re

K1 = 1.5
B = 0.75

WORD_RE = re.compile(r"[a-z0-9_]+", re.UNICODE)


def tokenize(text: str) -> list[str]:
    """切词：ASCII 词元 + 压缩空白/标点后的字符 bigram。"""
    value = str(text or "")
    tokens = WORD_RE.findall(value.lower())
    compact = re.sub(r"[\W_]+", "", value, flags=re.UNICODE)
    tokens.extend(compact[i : i + 2] for i in range(len(compact) - 1))
    return tokens


class BM25:
    """内存 BM25：构建时统计文档频率与长度，search 返回带 ``bm25`` 分的页面。"""

    def __init__(self, pages: list[dict]) -> None:
        self.pages = [dict(page) for page in pages]
        self.doc_tokens = [
            tokenize(f"{page.get('title', '')}\n{page.get('content', '')}")
            for page in self.pages
        ]
        self.doc_len = [len(tokens) for tokens in self.doc_tokens]
        self.avg_len = sum(self.doc_len) / len(self.doc_len) if self.doc_len else 0.0
        self.df: dict[str, int] = {}
        for tokens in self.doc_tokens:
            for term in set(tokens):
                self.df[term] = self.df.get(term, 0) + 1
        self.total = len(self.pages)

    def search(self, query: str, limit: int = 5) -> list[dict]:
        if not self.pages:
            return []
        terms = list(dict.fromkeys(tokenize(query)))
        idf = {
            term: math.log(1 + (self.total - df + 0.5) / (df + 0.5))
            for term in terms
            if (df := self.df.get(term, 0)) > 0
        }
        if not idf:
            return []
        avg = max(self.avg_len, 1e-9)
        scored: list[tuple[float, dict]] = []
        for page, tokens, length in zip(self.pages, self.doc_tokens, self.doc_len):
            total = 0.0
            for term, weight in idf.items():
                freq = tokens.count(term)
                if not freq:
                    continue
                total += weight * (freq * (K1 + 1)) / (freq + K1 * (1 - B + B * length / avg))
            if total > 0:
                scored.append((total, page))
        scored.sort(key=lambda item: (-item[0], item[1].get("path", "")))
        return [{**page, "bm25": score} for score, page in scored[:limit]]


def search(pages: list[dict], query: str, limit: int = 5) -> list[dict]:
    """对页面列表做一次 BM25 检索（就地构建统计，适合每次查询的小语料）。"""
    return BM25(pages).search(query, limit)
