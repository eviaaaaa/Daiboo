from langchain_core.embeddings import Embeddings
import dashscope


MAX_EMBEDDING_BATCH_SIZE = 25


class QwenEmbeddings(Embeddings):
    def __init__(self,model: str = "text-embedding-v1"):
        self.model = model

    def _normalize_texts(self, texts: list[str]) -> list[str]:
        # 针对 embeddings 设计截断（最大 token 2,048）
        # 由于没有 tokenizer，使用字符长度估算。通常 1 token ≈ 1.5-2 字符。
        # 保守起见，截断到 4000 字符。
        return [(text or " ").strip()[:4000] or " " for text in texts]

    def _embed_texts(self, texts: list[str], text_type: str) -> list[list[float]]:
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

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self._embed_texts(texts, text_type="document")

    def embed_query(self, text: str) -> list[float]:
        return self._embed_texts([text], text_type="query")[0]

qwen_embeddings = QwenEmbeddings()
