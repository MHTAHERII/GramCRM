from sqlalchemy import Column, Integer, Text, Boolean, DateTime
from datetime import datetime
from app.database import Base


class BotSetting(Base):
    """جدول تک‌ردیفه تنظیمات ربات؛ همیشه فقط رکورد id=1 وجود دارد."""
    __tablename__ = "bot_settings"

    id = Column(Integer, primary_key=True)

    # وقتی خاموش باشد، پیام‌ها ذخیره می‌شوند ولی پاسخ خودکار ارسال نمی‌شود
    bot_enabled = Column(Boolean, default=True, nullable=False)

    # پیام پیش‌فرض وقتی هیچ کلیدواژه‌ای منطبق نشود
    fallback_message = Column(Text, nullable=False)

    # دروازه فالو: اگر فعال باشد، کسی که پیج را فالو نکرده اول پیام فالو می‌گیرد
    follow_gate_enabled = Column(Boolean, default=False, nullable=False)

    # متن پیام دروازه فالو
    follow_gate_message = Column(Text, nullable=True)

    # اتوماسیون کامنت به دایرکت (Comment to DM)
    comment_reply_enabled = Column(Boolean, default=True, nullable=False)
    comment_public_reply_enabled = Column(Boolean, default=False, nullable=False)
    comment_public_reply_text = Column(Text, nullable=True, default="پاسخ براتون دایرکت شد 🌸")

    updated_at = Column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow
    )
