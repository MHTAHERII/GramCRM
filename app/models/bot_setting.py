from sqlalchemy import Column, Integer, String, Text, Boolean, DateTime, JSON
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

    # دکمه‌های شیشه‌ای لینک‌دار دروازه فالو (اختیاری)
    follow_gate_button_title = Column(String(100), nullable=True)
    follow_gate_button_url = Column(String(500), nullable=True)
    follow_gate_buttons = Column(JSON, nullable=True, default=list)

    # اتوماسیون کامنت به دایرکت (Comment to DM)
    comment_reply_enabled = Column(Boolean, default=True, nullable=False)
    comment_public_reply_enabled = Column(Boolean, default=False, nullable=False)
    comment_public_reply_text = Column(Text, nullable=True, default="پاسخ براتون دایرکت شد 🌸")

    # اطلاعات ورود به پنل مدیریت
    admin_username = Column(String(100), default="admin", nullable=False)
    admin_password = Column(String(100), nullable=True)

    # اطلاعات اتصال به API اینستاگرام (Zernio)
    zernio_api_key = Column(String(255), nullable=True)
    zernio_profile_id = Column(String(100), nullable=True)
    zernio_account_id = Column(String(100), nullable=True)
    instagram_username = Column(String(100), nullable=True)

    updated_at = Column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow
    )
