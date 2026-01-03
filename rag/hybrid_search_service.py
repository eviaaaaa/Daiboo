import jieba
from sqlalchemy import select, func, desc
from sqlalchemy.orm import Session
from utils import qwen_embeddings
from sentence_transformers import CrossEncoder
import torch
import re

# 全局单例模式加载模型，避免每次实例化 Service 都重新加载
_reranker_model = None

def get_reranker():
    global _reranker_model
    if _reranker_model is None:
        # 使用 BGE Reranker Base (支持中英文，效果好且速度适中)
        model_name = 'BAAI/bge-reranker-base'
        print(f"⏳ Loading Reranker model ({model_name})...")
        
        device = 'cuda' if torch.cuda.is_available() else 'cpu'
        _reranker_model = CrossEncoder(model_name, max_length=512, device=device)
        print(f"✅ Reranker model loaded on {device}.")
    return _reranker_model

class HybridSearchService:
    def __init__(self, session: Session):
        self.session = session
        # 懒加载模型
        self._reranker = None

    @property
    def reranker(self):
        if self._reranker is None:
            self._reranker = get_reranker()
        return self._reranker

    def search(self, model_class, query: str, top_k: int = 5, use_rerank: bool = True):
        """
        通用的混合检索函数 (支持重排序)
        :param model_class: SQLAlchemy 模型类 (需继承 SearchableMixin)
        :param query: 用户查询
        :param top_k: 最终返回数量
        :param use_rerank: 是否启用重排序
        """
        # 1. 准备查询向量
        query_embedding = qwen_embeddings.embed_query(query)
        
        # 2. 准备关键词查询 (分词并用 & 连接)
        seg_list = jieba.cut(query)
        
        # 增强清洗逻辑：只保留中文、英文、数字
        # 过滤掉标点符号和特殊字符
        valid_segs = []
        for seg in seg_list:
            seg = seg.strip()
            if not seg:
                continue
            # 使用正则检查是否包含有效字符 (中文、英文、数字)
            if re.match(r'^[\u4e00-\u9fa5a-zA-Z0-9]+$', seg):
                valid_segs.append(seg)
        
        if not valid_segs:
            ts_query_str = ""
        else:
            ts_query_str = " & ".join(valid_segs)

        # 为了给重排序留足空间，召回阶段获取更多候选集
        candidate_k = top_k * 3 if use_rerank else top_k

        # --- A路：向量检索 (Vector Search) ---
        # 动态获取模型的 embedding 字段名
        embedding_field_name = None
        if hasattr(model_class, '__mapper__'):
            for attr_name in dir(model_class):
                if not attr_name.startswith('_'):
                    attr = getattr(model_class, attr_name, None)
                    if hasattr(attr, 'type') and hasattr(attr.type, '__class__'):
                        if 'Vector' in attr.type.__class__.__name__:
                            embedding_field_name = attr_name
                            break
        
        vector_results = []
        if embedding_field_name:
            embedding_column = getattr(model_class, embedding_field_name)
            vector_stmt = select(model_class).order_by(
                embedding_column.cosine_distance(query_embedding)
            ).limit(candidate_k)
            vector_results = self.session.scalars(vector_stmt).all()

        # --- B路：关键词检索 (Keyword Search) ---
        keyword_results = []
        if ts_query_str:
            # 假设模型都有 fts_vector 字段
            kw_stmt = select(model_class).filter(
                model_class.fts_vector.op('@@')(func.to_tsquery('simple', ts_query_str))
            ).order_by(
                desc(func.ts_rank(model_class.fts_vector, func.to_tsquery('simple', ts_query_str)))
            ).limit(candidate_k)
            
            keyword_results = self.session.scalars(kw_stmt).all()

        # --- C路：RRF 融合 (Reciprocal Rank Fusion) ---
        candidates = self._perform_rrf_fusion(vector_results, keyword_results, top_k=candidate_k)

        # --- D路：重排序 (Rerank) ---
        if use_rerank and candidates:
            return self._perform_rerank(query, candidates, top_k=top_k)
        
        return candidates[:top_k]

    def _perform_rrf_fusion(self, vector_results, keyword_results, k=60, top_k=5):
        """
        执行 RRF 融合算法
        """
        scores = {}
        
        # 处理向量结果
        for rank, doc in enumerate(vector_results):
            if doc.id not in scores:
                scores[doc.id] = {"doc": doc, "score": 0}
            scores[doc.id]["score"] += 1 / (k + rank + 1)
            
        # 处理关键词结果
        for rank, doc in enumerate(keyword_results):
            if doc.id not in scores:
                scores[doc.id] = {"doc": doc, "score": 0}
            scores[doc.id]["score"] += 1 / (k + rank + 1)
        
        # 排序
        sorted_docs = sorted(scores.values(), key=lambda x: x["score"], reverse=True)
        
        # 返回前 top_k 个对象
        return [item["doc"] for item in sorted_docs[:top_k]]

    def _perform_rerank(self, query: str, candidates: list, top_k: int):
        """
        使用 Cross-Encoder 对候选文档进行精细打分
        """
        if not candidates:
            return []

        try:
            # 构造输入对：[[query, doc_content], ...]
            pairs = []
            for doc in candidates:
                # 使用 SearchableMixin 的 search_content_field 属性
                if hasattr(doc, 'search_content_field'):
                    content = doc.search_content_field
                else:
                    # 兼容旧代码：尝试获取 content 或 user_query
                    content = getattr(doc, 'content', getattr(doc, 'user_query', ''))
                pairs.append([query, content])

            # 计算分数
            # CrossEncoder.predict 返回 ndarray 或 list
            scores = self.reranker.predict(pairs)
            
            # 结合分数和文档
            scored_docs = list(zip(candidates, scores))
            
            # 按分数降序排列
            scored_docs.sort(key=lambda x: x[1], reverse=True)
            
            # 返回 Top K 文档
            return [doc for doc, score in scored_docs[:top_k]]
        except Exception as e:
            print(f"⚠️ Rerank failed: {e}. Fallback to original order.")
            return candidates[:top_k]