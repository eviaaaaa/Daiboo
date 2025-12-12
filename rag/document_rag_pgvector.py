from pathlib import Path
from typing import Union, List
import jieba
from langchain_community.document_loaders import (
    TextLoader, 
    PyPDFLoader, 
    Docx2txtLoader,
    UnstructuredMarkdownLoader
)
from langchain_text_splitters import RecursiveCharacterTextSplitter
from sqlalchemy import select, text, func
from sqlalchemy.orm import Session
from utils import qwen_embeddings
from database import engine
from entity.rag_document import RagDocument
from rag.hybrid_search_service import HybridSearchService

def get_loader_for_file(file_path: Path):
    """根据文件后缀返回合适的 Loader"""
    suffix = file_path.suffix.lower()
    str_path = str(file_path)
    
    if suffix == ".pdf":
        return PyPDFLoader(str_path)
    elif suffix in [".docx", ".doc"]:
        return Docx2txtLoader(str_path)
    elif suffix == ".md":
        return UnstructuredMarkdownLoader(str_path)
    else:
        # 默认尝试作为文本文件加载
        return TextLoader(str_path, encoding="utf-8")

def save_document_to_pgvector(doc_paths: Union[Path, List[Path]]):
    """
    将一个或多个文档加载、切分，并存入 pgvector 向量库。
    支持 .txt, .md, .pdf, .docx 等格式。
    
    Args:
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

    # 确保数据库表存在
    RagDocument.metadata.create_all(engine)

    # 加载并切分所有文档
    all_splits = []
    text_splitter = RecursiveCharacterTextSplitter(chunk_size=500, chunk_overlap=50)
    
    for doc_path in doc_paths:
        try:
            loader = get_loader_for_file(doc_path)
            docs = loader.load()
            splits = text_splitter.split_documents(docs)
            all_splits.extend(splits)
            print(f"📄 成功加载并切分文件: {doc_path.name} ({len(splits)} chunks)")
        except Exception as e:
            print(f"❌ 加载文件 {doc_path} 失败: {e}")
            continue

    if not all_splits:
        print("⚠️ 没有生成任何文档块。")
        return

    # 生成嵌入
    texts = [doc.page_content for doc in all_splits]
    embeddings = qwen_embeddings.embed_documents(texts)

    # 创建 RagDocument 对象
    rag_docs = []
    for i, doc in enumerate(all_splits):
        # 中文分词
        seg_list = jieba.cut(doc.page_content)
        seg_content = " ".join(seg_list)
        
        rag_doc = RagDocument(
            content=doc.page_content,
            meta_data=doc.metadata,
            embedding=embeddings[i],
            fts_vector=func.to_tsvector('simple', seg_content)
        )
        rag_docs.append(rag_doc)

    # 存入数据库
    with Session(engine) as session:
        session.add_all(rag_docs)
        session.commit()

    print(f"✅ 成功存入 {len(rag_docs)} 个文本块到数据库 (含混合索引)")

def query_document_from_pgvector(query: str, top_k: int = 3, use_rerank: bool = True)->list[RagDocument]:
    """
    根据查询文本，从 pgvector 向量库中检索相关文档 (混合检索)。
    
    Args:
        query (str): 查询文本
        top_k (int): 返回的相关文档数量，默认值为 3
        use_rerank (bool): 是否使用重排序
    
    Returns:
        list: 检索到的相关文档列表 (RagDocument 对象)
    """
    with Session(engine) as session:
        service = HybridSearchService(session)
        results : list[RagDocument] = service.search(RagDocument, query, top_k=top_k, use_rerank=use_rerank)
    for doc in results:
        doc.id = None 
        doc.embedding = None
        doc.fts_vector = None  # 不返回ID 和向量，节省token
    print(f"🔍 查询 '{query}'，找到 {len(results)} 个相关文档。")
    return results