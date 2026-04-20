from langchain_core.embeddings import Embeddings
import dashscope

class QwenEmbeddings(Embeddings):
    def __init__(self,model: str = "text-embedding-v1"):
        self.model = model

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        # 针对 embeddings 设计截断（最大 token 2,048）
        # 由于没有 tokenizer，使用字符长度估算。通常 1 token ≈ 1.5-2 字符。
        # 保守起见，截断到 4000 字符。
        truncated_texts = [text[:4000] for text in texts]

        resp = dashscope.TextEmbedding.call(
            model=self.model,
            input=truncated_texts
        )
        if resp.status_code != 200:
             raise Exception(f"Dashscope Embedding Error: {resp}")
        return [item["embedding"] for item in resp.output["embeddings"]]

    def embed_query(self, text: str) -> list[float]:
        return self.embed_documents([text])[0]

qwen_embeddings = QwenEmbeddings()
