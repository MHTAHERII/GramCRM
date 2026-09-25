from sqlalchemy import Column, Integer, String, Text, Boolean, DateTime
from datetime import datetime
from app.database import Base


class Keyword(Base):
    __tablename__ = "keywords"

    id = Column(Integer, primary_key=True, index=True)

    # کلمه یا عبارتی که مشتری می‌فرستد
    keyword = Column(
        String(100),
        nullable=False,
        unique=True
    )

    # پاسخی که ربات باید ارسال کند
    response = Column(
        Text,
        nullable=False
    )

    active = Column(
        Boolean,
        default=True
    )

    created_at = Column(
        DateTime,
        default=datetime.utcnow
    )