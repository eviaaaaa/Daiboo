from __future__ import annotations

import hashlib
import os

from langchain_core.embeddings import Embeddings
import dashscope

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
        self._use_local_embeddings = _truthy_env("NAXUSSURF_LOCAL_EMBEDDINGS")
        self._openai_embeddings = None
        api_key = _strip_env("OPENAI_API_KEY")
        if not self._use_local_embeddings and api_key and OpenAIEmbeddings is not None:
            self._openai_embeddings = OpenAIEmbeddings(
                api_key=api_key,
                base_url=_strip_env("OPENAI_BASE_URL"),
                model=_strip_env("OPENAI_EMBEDDING_MODEL") or model,
            )

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

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self._embed_texts(texts, text_type="document")

    def embed_query(self, text: str) -> list[float]:
        return self._embed_texts([text], text_type="query")[0]

qwen_embeddings = QwenEmbeddings()
