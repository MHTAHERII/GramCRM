import re
from sqlalchemy.orm import Session
from app.models.keyword import Keyword
from app.service.bot_settings import get_bot_settings
from app.service.product_response import keyword_response


def normalize_text(text: str) -> str:
    """
    نرمال‌سازی متن ورودی:
    - تبدیل حروف عربی (ي و ك) به فارسی
    - حذف فاصله‌های اضافی و فاصله‌های ابتدا و انتها
    - تبدیل به حروف کوچک (برای واژه‌های انگلیسی)
    """
    if not text:
        return ""
    text = text.replace("ي", "ی").replace("ك", "ک")
    text = re.sub(r"\s+", " ", text).strip().lower()
    return text


def find_keyword_response(text: str, db: Session, fallback: bool = False) -> str | None:
    """
    موتور استخراج پاسخ:
    ۱. تطابق دقیق (Exact Match)
    ۲. در صورت عدم تطابق دقیق، تطابق جزئی (کلمات کلیدی طولانی‌تر اولویت بالاتری دارند)
    ۳. در صورت عدم تطابق، پیام پیش‌فرض از تنظیمات (قابل ویرایش از پنل)
    """
    if not text:
        return _fallback_reply(db) if fallback else None

    clean_text = normalize_text(text)

    # خواندن کلیدواژه‌های فعال از دیتابیس
    keywords = db.query(Keyword).filter(Keyword.active == True).all()  # noqa: E712
    if not keywords:
        return _fallback_reply(db) if fallback else None

    # فقط تطابق کامل و دقیق (Exact Match)
    for item in keywords:
        clean_kw = normalize_text(item.keyword)
        if clean_kw and clean_kw == clean_text:
            return keyword_response(item)

    # اگر کلیدواژه‌ای دقیقاً پیدا نشد
    return _fallback_reply(db) if fallback else None


def _fallback_reply(db: Session) -> str:
    """پیام پیش‌فرض از تنظیمات دیتابیس (قابل ویرایش از پنل)"""
    return get_bot_settings(db).fallback_message


# جهت حفظ سازگاری با روترهای قبلی
find_keyword_responce = find_keyword_response
