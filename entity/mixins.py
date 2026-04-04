import jieba
from sqlalchemy import Index, event, func
from sqlalchemy.dialects.postgresql import TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column, declared_attr, MappedAsDataclass

class SearchableMixin(MappedAsDataclass):
    """
    为模型添加全文检索能力的 Mixin
    """
    # 存储分词后的文本向量
    fts_vector: Mapped[str] = mapped_column(TSVECTOR, nullable=True, default=None)

    # 必须由子类实现的属性，指定哪个字段用于生成全文索引（例如 'content' 或 'user_query'）
    @property
    def search_content_field(self):
        raise NotImplementedError

    # 必须由子类实现的属性，指定哪个字段用于向量检索
    @property
    def embedding_field(self):
        raise NotImplementedError

    @declared_attr
    @classmethod
    def __table_args__(cls):
        # 自动为 fts_vector 创建 GIN 索引
        return (
            Index(f'ix_{cls.__tablename__}_fts', 'fts_vector', postgresql_using='gin'),
        )

# 注册统一的拦截器，自动生成 fts_vector
def _generate_fts_vector(mapper, connection, target):
    # 尝试获取需要检索的文本内容
    if hasattr(target, 'search_content_field') and target.search_content_field:
        content = target.search_content_field
        if isinstance(content, str) and content.strip():
            # 将文本进行分词
            seg_text = " ".join(jieba.cut(content))
            # 生成 tsvector 表达式并赋值给 target.fts_vector
            target.fts_vector = func.to_tsvector('simple', seg_text)

event.listen(SearchableMixin, 'before_insert', _generate_fts_vector, propagate=True)
event.listen(SearchableMixin, 'before_update', _generate_fts_vector, propagate=True)
