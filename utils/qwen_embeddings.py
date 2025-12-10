from langchain_core.embeddings import Embeddings
import dashscope

class QwenEmbeddings(Embeddings):
    def __init__(self,model: str = "text-embedding-v1"):
        self.model = model

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        resp = dashscope.TextEmbedding.call(
            model=self.model,
            input=texts
        )
        return [item["embedding"] for item in resp.output["embeddings"]]

    def embed_query(self, text: str) -> list[float]:
        return self.embed_documents([text])[0]

qwen_embeddings = QwenEmbeddings()