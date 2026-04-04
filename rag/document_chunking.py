from typing import Iterable

from langchain_core.documents import Document

try:
    from langchain_text_splitters import RecursiveCharacterTextSplitter
except ModuleNotFoundError:
    class RecursiveCharacterTextSplitter:  # type: ignore[override]
        def __init__(self, chunk_size: int, chunk_overlap: int, add_start_index: bool = False):
            self.chunk_size = chunk_size
            self.chunk_overlap = chunk_overlap
            self.add_start_index = add_start_index

        def split_documents(self, docs: list[Document]) -> list[Document]:
            split_docs: list[Document] = []
            for doc in docs:
                text = doc.page_content
                start = 0
                while start < len(text):
                    end = min(start + self.chunk_size, len(text))
                    metadata = dict(doc.metadata or {})
                    if self.add_start_index:
                        metadata["start_index"] = start
                    split_docs.append(Document(page_content=text[start:end], metadata=metadata))
                    if end >= len(text):
                        break
                    start = max(end - self.chunk_overlap, start + 1)
            return split_docs

PARENT_CHUNK_SIZE = 1500
PARENT_CHUNK_OVERLAP = 200
CHILD_CHUNK_SIZE = 300
CHILD_CHUNK_OVERLAP = 50


def build_parent_child_chunks(docs: Iterable[Document]) -> list[dict]:
    """
    将 loader 输出构造成父子块结构。

    返回结构：
    [
        {
            "parent_doc": Document(...),
            "children": [Document(...), ...]
        },
        ...
    ]
    """
    parent_splitter = RecursiveCharacterTextSplitter(
        chunk_size=PARENT_CHUNK_SIZE,
        chunk_overlap=PARENT_CHUNK_OVERLAP,
        add_start_index=True,
    )
    child_splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHILD_CHUNK_SIZE,
        chunk_overlap=CHILD_CHUNK_OVERLAP,
        add_start_index=True,
    )

    parent_docs = parent_splitter.split_documents(list(docs))
    structured_chunks: list[dict] = []

    for parent_index, parent_doc in enumerate(parent_docs):
        parent_meta = dict(parent_doc.metadata or {})
        parent_meta["chunk_level"] = "parent"
        parent_meta["chunk_index"] = parent_index

        normalized_parent = Document(
            page_content=parent_doc.page_content,
            metadata=parent_meta,
        )

        child_docs = child_splitter.split_documents([normalized_parent])
        normalized_children: list[Document] = []

        for child_index, child_doc in enumerate(child_docs):
            child_meta = dict(child_doc.metadata or {})
            child_meta["chunk_level"] = "child"
            child_meta["chunk_index"] = child_index
            child_meta["parent_chunk_index"] = parent_index
            normalized_children.append(
                Document(page_content=child_doc.page_content, metadata=child_meta)
            )

        structured_chunks.append(
            {
                "parent_doc": normalized_parent,
                "children": normalized_children,
            }
        )

    return structured_chunks


def rank_parent_results(child_results: list, top_k: int) -> list[int]:
    parent_scores: dict[int, float] = {}

    for rank, child in enumerate(child_results):
        parent_key = child.parent_id or child.id
        if parent_key is None:
            continue
        parent_scores[parent_key] = parent_scores.get(parent_key, 0.0) + (1.0 / (rank + 1))

    ranked = sorted(parent_scores.items(), key=lambda item: item[1], reverse=True)
    return [parent_id for parent_id, _score in ranked[:top_k]]
