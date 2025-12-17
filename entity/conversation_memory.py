from datetime import datetime
import uuid
from sqlalchemy import String, Text, Integer, DateTime, JSON
from sqlalchemy.orm import Mapped, mapped_column
from entity.base import Base

class ConversationRound(Base):
    __tablename__ = "conversation_rounds"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    session_id: Mapped[str] = mapped_column(String, index=True)
    round_index: Mapped[int] = mapped_column(Integer)
    full_content: Mapped[str] = mapped_column(Text) # JSON string of the messages
    summary: Mapped[str] = mapped_column(Text, nullable=True)
    tags: Mapped[list[str]] = mapped_column(JSON, default=list) # List of IDs or keywords
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
