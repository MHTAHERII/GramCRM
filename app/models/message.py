from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey
from datetime import datetime
from sqlalchemy.orm import relationship
from app.database import Base


class Message(Base):
    __tablename__ = "messages"

    id = Column(Integer, primary_key=True, index=True)

    customer_id = Column(
        Integer,
        ForeignKey("customers.id"),#پیام متعلق به کدام مشتریه
        nullable=False
    )

    text = Column(Text, nullable=False)

    sender = Column(
        String(20),
        nullable=False
    )

    # فقط پیام‌های ورودی اینستاگرام این آیدی را دارند؛ پیام‌های خروجی ربات/ادمین NULL هستند
    instagram_message_id = Column(
        String(255),
        nullable=True,
        unique=True,
        index=True
    )

    created_at = Column(
        DateTime,
        default=datetime.utcnow
    )


    customer = relationship("Customer", back_populates="messages")