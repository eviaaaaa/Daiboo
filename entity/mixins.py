from sqlalchemy import Index
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
