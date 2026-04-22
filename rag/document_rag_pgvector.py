from pathlib import Path
from typing import Any, Union, List
from langchain_community.document_loaders import (
    TextLoader, 
    PyPDFLoader, 
    Docx2txtLoader,
    UnstructuredWordDocumentLoader,
    UnstructuredMarkdownLoader
)
from sqlalchemy import text, func, select
from sqlalchemy.orm import Session
from utils import qwen_embeddings
from database import engine
from entity.rag_document import RagDocument
from rag.document_chunking import (
    CHILD_CHUNK_OVERLAP,
    CHILD_CHUNK_SIZE,
    PARENT_CHUNK_OVERLAP,
    PARENT_CHUNK_SIZE,
    build_parent_child_chunks,
    rank_parent_results,
)
from rag.hybrid_search_service import HybridSearchService

def get_loader_for_file(file_path: Path):
    """根据文件后缀返回合适的 Loader"""
    suffix = file_path.suffix.lower()
    str_path = str(file_path)
    
    if suffix == ".pdf":
        return PyPDFLoader(str_path)
    elif suffix == ".docx":
        return Docx2txtLoader(str_path)
    elif suffix == ".doc":
        return UnstructuredWordDocumentLoader(str_path)
    elif suffix == ".md":
        return UnstructuredMarkdownLoader(str_path)
    else:
        # 默认尝试作为文本文件加载
        return TextLoader(str_path, encoding="utf-8")


def ensure_rag_document_schema():
    """确保 rag_documents 具备父子块需要的字段和索引。"""
    RagDocument.metadata.create_all(engine)

    ddl_statements = [
        "ALTER TABLE rag_documents ADD COLUMN IF NOT EXISTS chunk_level TEXT",
        "ALTER TABLE rag_documents ADD COLUMN IF NOT EXISTS parent_id INTEGER",
        "ALTER TABLE rag_documents ADD COLUMN IF NOT EXISTS source_path TEXT",
        "ALTER TABLE rag_documents ADD COLUMN IF NOT EXISTS source_name TEXT",
        "ALTER TABLE rag_documents ADD COLUMN IF NOT EXISTS chunk_index INTEGER",
        "ALTER TABLE rag_documents ADD COLUMN IF NOT EXISTS start_index INTEGER",
        "CREATE INDEX IF NOT EXISTS ix_rag_documents_parent_id ON rag_documents (parent_id)",
        "CREATE INDEX IF NOT EXISTS ix_rag_documents_chunk_level ON rag_documents (chunk_level)",
    ]

    with Session(engine) as session:
        for ddl in ddl_statements:
            session.execute(text(ddl))
        session.commit()

def _build_rag_document(
    doc,
    embedding: list[float],
    chunk_level: str | None,
    source_path: str | None,
    source_name: str | None,
    chunk_index: int | None,
    parent_id: int | None = None,
) -> RagDocument:
    metadata = dict(doc.metadata or {})
    start_index = metadata.get("start_index")
    return RagDocument(
        content=doc.page_content,
        meta_data=metadata,
        embedding=embedding,
        chunk_level=chunk_level,
        parent_id=parent_id,
        source_path=source_path,
        source_name=source_name,
        chunk_index=chunk_index,
        start_index=start_index,
    )


def _sanitize_return_docs(results: list[RagDocument]) -> list[RagDocument]:
    for doc in results:
        doc.id = None
        doc.embedding = None
        doc.fts_vector = None
    return results


def _serialize_rag_document(doc: RagDocument) -> dict[str, Any]:
    metadata = dict(doc.meta_data or {})
    chunk_level = doc.chunk_level or "legacy"
    source_name = doc.source_name or "未命名/旧数据"
    return {
        "id": doc.id,
        "content": doc.content,
        "source_name": source_name,
        "source_path": doc.source_path,
        "chunk_level": chunk_level,
        "chunk_index": doc.chunk_index,
        "parent_id": doc.parent_id,
        "start_index": doc.start_index,
        "metadata": metadata,
        "content_preview": doc.content[:320],
        "content_length": len(doc.content or ""),
    }

def save_document_to_pgvector(doc_paths: Union[Path, List[Path]]) -> dict[str, Any]:
    """
    将一个或多个文档加载、切分，并存入 pgvector 向量库。
    支持 .txt, .md, .pdf, .docx, .doc 等格式。
    
    参数：
        doc_paths (Path | list[Path]): 单个文档路径或多个文档路径列表
    """
    # 统一转换为列表
    if isinstance(doc_paths, Path):
        doc_paths = [doc_paths]
    
    # 校验所有文件是否存在
    for p in doc_paths:
        if not p.exists():
            raise FileNotFoundError(f"Document not found: {p}")

    # 确保 vector 扩展存在
    with Session(engine) as session:
        session.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        session.commit()

    # 确保数据库表和扩展字段存在
    ensure_rag_document_schema()

    # 加载并切分所有文档
    all_structured_chunks = []
    
    for doc_path in doc_paths:
        try:
            loader = get_loader_for_file(doc_path)
            docs = loader.load()
            structured_chunks = build_parent_child_chunks(docs)
            all_structured_chunks.append(
                {
                    "source_path": str(doc_path),
                    "source_name": doc_path.name,
                    "chunks": structured_chunks,
                }
            )
            child_count = sum(len(item["children"]) for item in structured_chunks)
            print(
                f"📄 成功加载并切分文件: {doc_path.name} "
                f"({len(structured_chunks)} parent chunks, {child_count} child chunks)"
            )
        except Exception as e:
            print(f"❌ 加载文件 {doc_path} 失败: {e}")
            continue

    if not all_structured_chunks:
        print("⚠️ 没有生成任何文档块。")
        return {"files": [], "total_parents": 0, "total_children": 0}

    # 存入数据库
    with Session(engine) as session:
        parent_records: list[tuple[RagDocument, list, str | None, str | None]] = []

        for file_item in all_structured_chunks:
            source_path = file_item["source_path"]
            source_name = file_item["source_name"]
            parent_docs = [chunk["parent_doc"] for chunk in file_item["chunks"]]
            if not parent_docs:
                continue

            parent_embeddings = qwen_embeddings.embed_documents(
                [doc.page_content for doc in parent_docs]
            )

            for parent_doc, parent_embedding, chunk in zip(
                parent_docs, parent_embeddings, file_item["chunks"]
            ):
                parent_record = _build_rag_document(
                    doc=parent_doc,
                    embedding=parent_embedding,
                    chunk_level="parent",
                    source_path=source_path,
                    source_name=source_name,
                    chunk_index=parent_doc.metadata.get("chunk_index"),
                )
                session.add(parent_record)
                parent_records.append(
                    (parent_record, chunk["children"], source_path, source_name)
                )

        session.flush()

        child_records: list[RagDocument] = []
        child_docs: list = []
        child_meta: list[tuple[int | None, str | None, str | None, int | None]] = []

        for parent_record, children, source_path, source_name in parent_records:
            for child_doc in children:
                child_docs.append(child_doc)
                child_meta.append(
                    (
                        parent_record.id,
                        source_path,
                        source_name,
                        child_doc.metadata.get("chunk_index"),
                    )
                )

        if child_docs:
            child_embeddings = qwen_embeddings.embed_documents(
                [doc.page_content for doc in child_docs]
            )
            for child_doc, child_embedding, metadata in zip(child_docs, child_embeddings, child_meta):
                parent_id, source_path, source_name, chunk_index = metadata
                child_records.append(
                    _build_rag_document(
                        doc=child_doc,
                        embedding=child_embedding,
                        chunk_level="child",
                        source_path=source_path,
                        source_name=source_name,
                        chunk_index=chunk_index,
                        parent_id=parent_id,
                    )
                )

        session.add_all(child_records)
        session.commit()

    file_summaries = [
        {
            "source_name": item["source_name"],
            "source_path": item["source_path"],
            "parent_chunks": len(item["chunks"]),
            "child_chunks": sum(len(chunk["children"]) for chunk in item["chunks"]),
        }
        for item in all_structured_chunks
    ]
    total_parents = sum(item["parent_chunks"] for item in file_summaries)
    total_children = sum(item["child_chunks"] for item in file_summaries)
    print(f"✅ 成功存入 {total_parents} 个父块和 {total_children} 个子块到数据库 (含混合索引)")
    return {
        "files": file_summaries,
        "total_parents": total_parents,
        "total_children": total_children,
    }

def query_document_from_pgvector(query: str, top_k: int = 3, use_rerank: bool = True)->list[RagDocument]:
    """
    根据查询文本，从 pgvector 向量库中检索相关文档 (混合检索)。
    
    参数：
        query (str): 查询文本
        top_k (int): 返回的相关文档数量，默认值为 3
        use_rerank (bool): 是否使用重排序
    
    返回：
        list: 检索到的相关文档列表 (RagDocument 对象)
    """
    ensure_rag_document_schema()

    with Session(engine) as session:
        service = HybridSearchService(session)
        child_results: list[RagDocument] = service.search(
            RagDocument,
            query,
            top_k=max(top_k * 4, top_k),
            use_rerank=use_rerank,
            chunk_level="child",
        )

        if child_results:
            ranked_parent_ids = rank_parent_results(child_results, top_k=top_k)
            parent_results: list[RagDocument] = []
            for parent_id in ranked_parent_ids:
                parent_doc = session.get(RagDocument, parent_id)
                if parent_doc is not None:
                    parent_results.append(parent_doc)
            if parent_results:
                print(f"🔍 查询 '{query}'，命中 {len(child_results)} 个子块，返回 {len(parent_results)} 个父块。")
                return _sanitize_return_docs(parent_results)

        # 兼容旧数据：没有大小块字段时，退回原来的扁平检索
        legacy_stmt = select(RagDocument).filter(
            (RagDocument.chunk_level.is_(None)) | (RagDocument.chunk_level == "parent")
        )
        if session.scalars(legacy_stmt.limit(1)).first() is not None:
            legacy_results: list[RagDocument] = service.search(
                RagDocument,
                query,
                top_k=top_k,
                use_rerank=use_rerank,
            )
            print(f"🔍 查询 '{query}'，未命中新子块，回退返回 {len(legacy_results)} 个旧块。")
            return _sanitize_return_docs(legacy_results)

    print(f"🔍 查询 '{query}'，找到 0 个相关文档。")
    return []


def debug_query_document_from_pgvector(
    query: str,
    top_k: int = 5,
    use_rerank: bool = True,
) -> dict[str, Any]:
    """返回大块、小块和层级检索的调试结果，便于前端对比效果。"""
    ensure_rag_document_schema()

    with Session(engine) as session:
        service = HybridSearchService(session)

        parent_results: list[RagDocument] = service.search(
            RagDocument,
            query,
            top_k=top_k,
            use_rerank=use_rerank,
            chunk_level="parent",
        )
        child_results: list[RagDocument] = service.search(
            RagDocument,
            query,
            top_k=top_k,
            use_rerank=use_rerank,
            chunk_level="child",
        )
        hierarchical_child_results: list[RagDocument] = service.search(
            RagDocument,
            query,
            top_k=max(top_k * 4, top_k),
            use_rerank=use_rerank,
            chunk_level="child",
        )

        parent_ids = rank_parent_results(hierarchical_child_results, top_k=top_k)
        parent_map: dict[int, RagDocument] = {}
        if parent_ids:
            parent_docs = session.scalars(
                select(RagDocument).where(RagDocument.id.in_(parent_ids))
            ).all()
            parent_map = {doc.id: doc for doc in parent_docs if doc.id is not None}

        grouped_children: dict[int, list[RagDocument]] = {}
        for child_doc in hierarchical_child_results:
            parent_id = child_doc.parent_id
            if parent_id is None:
                continue
            grouped_children.setdefault(parent_id, []).append(child_doc)

        hierarchical_results: list[dict[str, Any]] = []
        for parent_id in parent_ids:
            parent_doc = parent_map.get(parent_id)
            if parent_doc is None:
                continue
            hierarchical_results.append(
                {
                    "parent": _serialize_rag_document(parent_doc),
                    "matched_children": [
                        _serialize_rag_document(child_doc)
                        for child_doc in grouped_children.get(parent_id, [])
                    ],
                }
            )

        legacy_fallback_used = False
        if not parent_results and not child_results and not hierarchical_results:
            legacy_stmt = select(RagDocument).filter(RagDocument.chunk_level.is_(None))
            if session.scalars(legacy_stmt.limit(1)).first() is not None:
                legacy_candidates: list[RagDocument] = service.search(
                    RagDocument,
                    query,
                    top_k=top_k,
                    use_rerank=use_rerank,
                )
                legacy_results = [
                    doc for doc in legacy_candidates if doc.chunk_level is None
                ][:top_k]
                if legacy_results:
                    legacy_fallback_used = True
                    parent_results = legacy_results
                    hierarchical_results = [
                        {
                            "parent": _serialize_rag_document(doc),
                            "matched_children": [],
                        }
                        for doc in legacy_results
                    ]

    return {
        "query": query,
        "top_k": top_k,
        "use_rerank": use_rerank,
        "legacy_fallback_used": legacy_fallback_used,
        "chunk_config": {
            "parent_size": PARENT_CHUNK_SIZE,
            "parent_overlap": PARENT_CHUNK_OVERLAP,
            "child_size": CHILD_CHUNK_SIZE,
            "child_overlap": CHILD_CHUNK_OVERLAP,
        },
        "strategies": {
            "large_chunks": [_serialize_rag_document(doc) for doc in parent_results],
            "small_chunks": [_serialize_rag_document(doc) for doc in child_results],
            "hierarchical": hierarchical_results,
        },
    }


def get_rag_corpus_summary() -> dict[str, Any]:
    """返回当前索引库的概览信息，便于前端展示可测试数据范围。"""
    ensure_rag_document_schema()

    with Session(engine) as session:
        totals = session.execute(
            text(
                """
                SELECT
                    count(*) FILTER (WHERE chunk_level = 'parent') AS parent_count,
                    count(*) FILTER (WHERE chunk_level = 'child') AS child_count,
                    count(*) FILTER (WHERE chunk_level IS NULL) AS legacy_count
                FROM rag_documents
                """
            )
        ).one()

        per_source_rows = session.execute(
            text(
                """
                SELECT
                    COALESCE(source_name, '未命名/旧数据') AS source_name,
                    count(*) FILTER (WHERE chunk_level = 'parent') AS parent_chunks,
                    count(*) FILTER (WHERE chunk_level = 'child') AS child_chunks,
                    count(*) AS total_rows,
                    max(source_path) AS source_path
                FROM rag_documents
                GROUP BY COALESCE(source_name, '未命名/旧数据')
                ORDER BY source_name
                """
            )
        ).mappings().all()

    return {
        "total_parent_chunks": int(totals.parent_count or 0),
        "total_child_chunks": int(totals.child_count or 0),
        "total_legacy_rows": int(totals.legacy_count or 0),
        "sources": [
            {
                "source_name": row["source_name"],
                "source_path": row["source_path"],
                "parent_chunks": int(row["parent_chunks"] or 0),
                "child_chunks": int(row["child_chunks"] or 0),
                "total_rows": int(row["total_rows"] or 0),
            }
            for row in per_source_rows
        ],
    }
