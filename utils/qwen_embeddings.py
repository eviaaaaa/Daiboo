from __future__ import annotations

import hashlib
import os
from typing import TypeGuard

from langchain_core.embeddings import Embeddings
import dashscope

from utils.redis_cache import cache_key, get_json, set_json

try:
    from langchain_openai import OpenAIEmbeddings
except Exception:  # pragma: no cover - optional dependency fallback
    OpenAIEmbeddings = None


MAX_EMBEDDING_BATCH_SIZE = 25


def _strip_env(name: str) -> str | None:
    value = os.getenv(name)
    if value is None:
        return None
    value = value.strip()
    return value or None


def _truthy_env(name: str) -> bool:
    return (_strip_env(name) or "").lower() in {"1", "true", "yes", "on"}


def _positive_int_env(name: str, default: int) -> int:
    try:
        value = int(_strip_env(name) or default)
    except (TypeError, ValueError):
        return default
    return value if value > 0 else default


def _local_embedding(text: str) -> list[float]:
    normalized = (text or " ").strip() or " "
    values: list[float] = []
    counter = 0
    while len(values) < 1536:
        digest = hashlib.sha256(f"{counter}:{normalized}".encode("utf-8")).digest()
        values.extend((byte / 127.5) - 1.0 for byte in digest)
        counter += 1
    return values[:1536]


class QwenEmbeddings(Embeddings):
    def __init__(self, model: str = "text-embedding-v1"):
        self.model = model
        self._use_local_embeddings = _truthy_env("DAIBOO_LOCAL_EMBEDDINGS")
        self._openai_embeddings = None
        self._openai_base_url = _strip_env("OPENAI_EMBEDDING_BASE_URL") or _strip_env("OPENAI_BASE_URL")
        configured_openai_model = _strip_env("OPENAI_EMBEDDING_MODEL")
        self._openai_model = configured_openai_model or model
        api_key = _strip_env("OPENAI_EMBEDDING_API_KEY") or _strip_env("OPENAI_API_KEY")
        # Chat-compatible gateways such as DeepSeek often do not implement
        # /embeddings. Require an explicit embedding model before selecting
        # the OpenAI-compatible embedding client.
        if (
            not self._use_local_embeddings
            and configured_openai_model
            and api_key
            and OpenAIEmbeddings is not None
        ):
            self._openai_embeddings = OpenAIEmbeddings(
                api_key=api_key,
                base_url=self._openai_base_url,
                model=self._openai_model,
            )
        # If neither external provider is configured, default to local embeddings
        # so RAG works offline without DashScope or OpenAI credentials.
        has_dashscope_key = bool(_strip_env("DASHSCOPE_API_KEY"))
        if not self._use_local_embeddings and self._openai_embeddings is None and not has_dashscope_key:
            self._use_local_embeddings = True

    def _normalize_texts(self, texts: list[str]) -> list[str]:
        # 针对 embeddings 设计截断（最大 token 2,048）
        # 由于没有 tokenizer，使用字符长度估算。通常 1 token ≈ 1.5-2 字符。
        # 保守起见，截断到 4000 字符。
        return [(text or " ").strip()[:4000] or " " for text in texts]

    def _embed_texts_openai(self, texts: list[str], text_type: str) -> list[list[float]]:
        assert self._openai_embeddings is not None
        if not texts:
            return []
        if text_type == "query":
            return [self._openai_embeddings.embed_query(text) for text in texts]
        return self._openai_embeddings.embed_documents(texts)

    def _embed_texts_dashscope(self, texts: list[str], text_type: str) -> list[list[float]]:
        if not texts:
            return []

        normalized_texts = self._normalize_texts(texts)
        all_embeddings: list[list[float]] = []

        for start in range(0, len(normalized_texts), MAX_EMBEDDING_BATCH_SIZE):
            batch = normalized_texts[start:start + MAX_EMBEDDING_BATCH_SIZE]
            resp = dashscope.TextEmbedding.call(
                model=self.model,
                input=batch,
                text_type=text_type,
            )
            if resp.status_code != 200:
                raise Exception(f"Dashscope Embedding Error: {resp}")
            all_embeddings.extend(item["embedding"] for item in resp.output["embeddings"])

        return all_embeddings

    def _embed_texts(self, texts: list[str], text_type: str) -> list[list[float]]:
        if self._use_local_embeddings:
            return [_local_embedding(text) for text in texts]
        if self._openai_embeddings is not None:
            return self._embed_texts_openai(texts, text_type)
        return self._embed_texts_dashscope(texts, text_type)

    def _cache_identity(self) -> str:
        if self._use_local_embeddings:
            return "local-sha256-v1"
        if self._openai_embeddings is not None:
            return f"openai:{self._openai_base_url or 'default'}:{self._openai_model}"
        return f"dashscope:{self.model}"

    @staticmethod
    def _valid_cached_embedding(value: object) -> TypeGuard[list[int | float]]:
        return (
            isinstance(value, list)
            and len(value) == 1536
            and all(isinstance(item, (int, float)) for item in value)
        )

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self._embed_texts(texts, text_type="document")

    def embed_query(self, text: str) -> list[float]:
        normalized = self._normalize_texts([text])[0]
        key = cache_key("embedding-query", self._cache_identity(), normalized)
        cached = get_json(key)
        if self._valid_cached_embedding(cached):
            return [float(item) for item in cached]

        embedding = self._embed_texts([normalized], text_type="query")[0]
        set_json(
            key,
            embedding,
            ttl=_positive_int_env("REDIS_EMBEDDING_TTL", 86400),
        )
        return embedding

qwen_embeddings = QwenEmbeddings()


def embed_documents(texts: list[str]) -> list[list[float]]:
    """Compatibility wrapper for callers that import this module directly."""
    return qwen_embeddings.embed_documents(texts)


def embed_query(text: str) -> list[float]:
    """Compatibility wrapper for callers that import this module directly."""
    return qwen_embeddings.embed_query(text)
