from sqlalchemy import Column, Integer, String, Text, Boolean, DateTime, JSON, ForeignKey
from sqlalchemy.orm import relationship
from datetime import datetime
from app.database import Base
from app.models.product import Product  # noqa: F401


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
    product_id = Column(Integer, ForeignKey("products.id"), nullable=True, index=True)
    product = relationship("Product")

    # پاسخ عمومی زیر کامنت‌های منطبق (در صورت تنظیم توسط ادمین)
    comment_reply = Column(Text, nullable=True)

    active = Column(
        Boolean,
        default=True
    )

    # دکمه لینک‌دار تعاملی (اختیاری)
    button_title = Column(
        String(100),
        nullable=True
    )
    button_url = Column(
        String(500),
        nullable=True
    )
    buttons = Column(
        JSON,
        nullable=True,
        default=list
    )

    # تنظیمات تاخیر هوشمند برای رفتار طبیعی
    comment_reply_delay_seconds = Column(Integer, nullable=True, default=0)
    dm_delay_seconds = Column(Integer, nullable=True, default=0)

    # چرخش و تنوع متن‌ها برای جلوگیری از اسپم
    comment_reply_variations = Column(JSON, nullable=True, default=list)
    dm_message_variations = Column(JSON, nullable=True, default=list)

    # اتصال به شناسه پست یا ریلز خاص اینستاگرام (اختیاری)
    platform_post_id = Column(String(100), nullable=True)

    created_at = Column(
        DateTime,
        default=datetime.utcnow
    )
