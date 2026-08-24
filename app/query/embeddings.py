"""Embedding providers used by the vector query path.

The default provider is deliberately local and dependency free.  Optional
sentence-transformers and Ollama adapters are available for installations
that want a BGE model, while a cloud OpenAI-compatible adapter is only
selected when it is explicitly configured.
"""

from __future__ import annotations

import hashlib
import ipaddress
import math
import re
import socket
from collections.abc import Sequence
from urllib.parse import urlsplit

import httpx


class EmbeddingError(RuntimeError):
    """Raised when an embedding backend cannot produce valid vectors."""


class EmbeddingProvider:
    """Small synchronous embedding seam shared by index building and search."""

    name = "embedding"
    model = ""
    is_local = True

    def embed(self, texts: Sequence[str]) -> list[list[float]]:  # pragma: no cover - protocol-like base
        raise NotImplementedError

    def embed_text(self, text: str) -> list[float]:
        """Embed one text without exposing backend-specific batch details."""
        return self.embed([text])[0]

    def encode(self, texts: Sequence[str]) -> list[list[float]]:
        return self.embed(texts)

    def embed_query(self, text: str) -> list[float]:
        return self.embed([text])[0]

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        return self.embed(texts)


def _normalise(vector: Sequence[float]) -> list[float]:
    values = [float(v) for v in vector]
    norm = math.sqrt(sum(v * v for v in values))
    if not values or not math.isfinite(norm) or norm == 0:
        raise EmbeddingError("embedding 返回空向量或零向量")
    return [v / norm for v in values]


class HashEmbeddingProvider(EmbeddingProvider):
    """Deterministic local text embedding.

    This is a compact feature-hashing model intended as the always-available
    local fallback.  It requires no model download or network access and is
    effective for both Chinese character phrases and ordinary identifiers.
    Deployments with a BGE model can select the sentence-transformers or
    Ollama adapters through ``EMBEDDING_LOCAL_BACKEND``.
    """

    name = "local"
    is_local = True

    def __init__(self, dimensions: int = 384, model: str = "BAAI/bge-small-zh-v1.5") -> None:
        if int(dimensions) < 16:
            raise ValueError("embedding dimensions 必须至少为 16")
        self.dimensions = int(dimensions)
        self.model = model

    @staticmethod
    def _features(text: str) -> list[tuple[str, float]]:
        value = " ".join(str(text).lower().split())
        if not value:
            return []
        features: list[tuple[str, float]] = [
            (token, 1.0) for token in re.findall(r"[\w]+", value, re.UNICODE)
        ]
        compact = re.sub(r"\s+", "", value)
        # Character n-grams make paraphrased Chinese questions useful without
        # relying on whitespace tokenisation.
        for n, weight in ((1, 0.35), (2, 1.0), (3, 0.85), (4, 0.55)):
            features.extend((compact[i : i + n], weight) for i in range(max(0, len(compact) - n + 1)))
        return features

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        result: list[list[float]] = []
        for text in texts:
            vector = [0.0] * self.dimensions
            for feature, weight in self._features(text):
                digest = hashlib.blake2b(feature.encode("utf-8"), digest_size=16).digest()
                index = int.from_bytes(digest[:8], "big") % self.dimensions
                # Positive hashing keeps shared character n-grams additive,
                # which is more useful for short Chinese paraphrases than
                # signed collisions in this tiny fallback.
                vector[index] += weight
            # Empty text still gets a valid vector; callers normally filter it
            # before embedding, but this keeps the provider total and stable.
            if not any(vector):
                vector[0] = 1.0
            result.append(_normalise(vector))
        return result


class SentenceTransformerEmbeddingProvider(EmbeddingProvider):
    """Optional local sentence-transformers adapter (typically a BGE model).

    ``local_files_only=True`` is intentional: selecting this backend never
    causes Wiki text or model downloads to leave the machine.
    """

    name = "sentence-transformers"
    is_local = True

    def __init__(self, model: str, dimensions: int | None = None) -> None:
        # Hugging Face honours this flag across sentence-transformers releases;
        # it prevents an unavailable model from being fetched implicitly.
        import os

        os.environ.setdefault("HF_HUB_OFFLINE", "1")
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:  # pragma: no cover - optional dependency
            raise EmbeddingError("未安装 sentence-transformers") from exc
        try:
            self._model = SentenceTransformer(model, local_files_only=True)
        except TypeError:  # older versions do not expose local_files_only
            try:
                self._model = SentenceTransformer(model)
            except Exception as exc:  # pragma: no cover - optional dependency
                raise EmbeddingError("本地 sentence-transformers 模型不可用") from exc
        except Exception as exc:  # pragma: no cover - optional dependency
            raise EmbeddingError("本地 sentence-transformers 模型不可用") from exc
        self.model = model
        self.dimensions = dimensions

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        try:
            values = self._model.encode(
                list(texts), normalize_embeddings=True, convert_to_numpy=False, show_progress_bar=False
            )
            vectors = [[float(v) for v in row] for row in values]
        except Exception as exc:  # pragma: no cover - optional dependency
            raise EmbeddingError("sentence-transformers embedding 失败") from exc
        return [_normalise(row) for row in vectors]


def _local_host(host: str) -> bool:
    host = (host or "").strip("[]").lower()
    if host == "localhost":
        return True
    try:
        address = ipaddress.ip_address(host)
        return bool(address.is_loopback or address.is_private or address.is_link_local or address.is_reserved)
    except ValueError:
        pass
    try:
        addresses = {item[4][0].split("%")[0] for item in socket.getaddrinfo(host, None)}
    except socket.gaierror:
        return False
    if not addresses:
        return False
    for address in addresses:
        try:
            parsed = ipaddress.ip_address(address)
        except ValueError:
            return False
        if not (parsed.is_loopback or parsed.is_private or parsed.is_link_local or parsed.is_reserved):
            return False
    return True


def validate_local_endpoint(base_url: str) -> str | None:
    host = urlsplit((base_url or "").strip()).hostname
    if not host:
        return "本地 embedding 必须填写有效的 API 地址"
    if not _local_host(host):
        return "本地 embedding 仅允许 localhost/内网端点"
    return None


class OllamaEmbeddingProvider(EmbeddingProvider):
    """Ollama's local ``/api/embed`` endpoint."""

    name = "ollama"
    is_local = True

    def __init__(self, base_url: str, model: str, timeout: float = 60) -> None:
        error = validate_local_endpoint(base_url)
        if error:
            raise EmbeddingError(error)
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        values = list(texts)
        if not values:
            return []
        try:
            with httpx.Client(timeout=self.timeout) as client:
                response = client.post(
                    self.base_url + "/api/embed",
                    json={"model": self.model, "input": values},
                )
                body = response.json() if response.status_code < 400 else {}
                vectors = body.get("embeddings")
                if response.status_code == 404 and len(values) == 1:
                    # Older Ollama versions expose the singular endpoint.
                    response = client.post(
                        self.base_url + "/api/embeddings",
                        json={"model": self.model, "prompt": values[0]},
                    )
                    response.raise_for_status()
                    vectors = [response.json().get("embedding")]
                else:
                    response.raise_for_status()
        except (httpx.HTTPError, ValueError, TypeError, KeyError) as exc:
            raise EmbeddingError("Ollama embedding 请求失败") from exc
        if not isinstance(vectors, list) or len(vectors) != len(values):
            raise EmbeddingError("Ollama embedding 返回数量不匹配")
        return [_normalise(row) for row in vectors]


# Common spelling used by callers and documentation.
OllamaEmbedding = OllamaEmbeddingProvider


class CloudEmbeddingProvider(EmbeddingProvider):
    """OpenAI-compatible remote embedding adapter.

    The factory never selects this class implicitly; callers must opt into a
    cloud provider explicitly with ``EMBEDDING_PROVIDER=cloud`` (or ``openai``).
    """

    name = "cloud"
    is_local = False

    def __init__(self, base_url: str, api_key: str, model: str, timeout: float = 180) -> None:
        if not base_url:
            raise EmbeddingError("云端 embedding 必须填写 API 地址")
        if not model:
            raise EmbeddingError("云端 embedding 必须填写模型名")
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout = timeout

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        values = list(texts)
        if not values:
            return []
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        try:
            with httpx.Client(timeout=self.timeout) as client:
                response = client.post(
                    self.base_url + "/embeddings",
                    json={"model": self.model, "input": values},
                    headers=headers,
                )
                response.raise_for_status()
                body = response.json()
                rows = sorted(body["data"], key=lambda row: row.get("index", 0))
                vectors = [row["embedding"] for row in rows]
        except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError) as exc:
            raise EmbeddingError("云端 embedding 请求失败") from exc
        if len(vectors) != len(values):
            raise EmbeddingError("云端 embedding 返回数量不匹配")
        return [_normalise(row) for row in vectors]


OpenAIEmbeddingProvider = CloudEmbeddingProvider


def _setting(settings, *names: str, default=None):
    for name in names:
        value = getattr(settings, name, None)
        if value is not None and value != "":
            return value
    return default


def build_embedding_provider(settings, provider: str | None = None) -> EmbeddingProvider:
    """Build an embedding provider from settings.

    ``local`` is the fail-safe default.  A cloud provider is selected only by
    an explicit provider value; merely supplying a cloud URL or key does not
    change the default.
    """
    selected = str(
        provider
        or _setting(settings, "embedding_provider", "embedding_backend", default="local")
    ).strip().lower()
    model = str(_setting(settings, "embedding_model", default="BAAI/bge-small-zh-v1.5"))
    dimensions = int(_setting(settings, "embedding_dimensions", default=384))

    if selected == "cloud":
        return CloudEmbeddingProvider(
            str(_setting(settings, "embedding_base_url", default="")),
            str(_setting(settings, "embedding_api_key", default="") or ""),
            model,
            float(_setting(settings, "embedding_timeout", default=180)),
        )
    if selected != "local":
        raise EmbeddingError(f"未知 embedding provider: {selected}")

    backend = str(_setting(settings, "embedding_local_backend", default="hash")).strip().lower()
    if backend in {"sentence-transformers", "sentence_transformers", "st"}:
        return SentenceTransformerEmbeddingProvider(model, dimensions)
    if backend == "ollama":
        return OllamaEmbeddingProvider(
            str(_setting(settings, "embedding_base_url", default="") or "http://127.0.0.1:11434"),
            model,
            float(_setting(settings, "embedding_timeout", default=60)),
        )
    if backend == "hash":
        return HashEmbeddingProvider(dimensions, model)
    raise EmbeddingError(f"未知本地 embedding backend: {backend}")


# Friendly aliases for callers/tests that use the backend names directly.
LocalEmbeddingProvider = HashEmbeddingProvider
LocalEmbedding = HashEmbeddingProvider
build_provider = build_embedding_provider
