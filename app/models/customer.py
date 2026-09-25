from sqlalchemy import Column, Integer, String, DateTime
from datetime import datetime
from app.database import Base
from sqlalchemy.orm import relationship

class Customer(Base):
    __tablename__ = "customers"

    id = Column(Integer, primary_key=True, index=True)

    instagram_id = Column(String(100), unique=True, nullable=False)

    username = Column(String(100), nullable=True)

    name = Column(String(150), nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)

    # با حذف مشتری، پیام‌هایش هم حذف می‌شوند تا خطای FK رخ ندهد
    messages = relationship(
        "Message",
        back_populates="customer",
        cascade="all, delete-orphan"
    )