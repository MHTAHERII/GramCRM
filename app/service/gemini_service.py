"""
فاز ۲: پیشنهاد جواب هوشمند (AI Draft) با Google Gemini

ادمین در تب گفتگوها دکمه «✨ پیشنهاد» را می‌زند؛ سرویس با در نظر گرفتن
کاتالوگ محصولات و تاریخچه مکالمه، یک پیش‌نویس جواب فارسی آماده می‌کند.
متن در کادر پاسخ پر می‌شود و ادمین قبل از ارسال بازبینی/ویرایش می‌کند —
ارسال بدون تأیید بر عهدهٔ این فاز نیست (ایجنت کامل، فاز ۴).

نکته: توابع سینک هستند و در نخ جدا (threadpool FastAPI) اجرا می‌شوند.
"""
import logging
import time

import requests

from app.config import settings as env_settings

logger = logging.getLogger("gemini")

DEFAULT_MODEL = "gemini-2.5-flash"
BASE_URL = "https://generativelanguage.googleapis.com/v1beta/models"
REQUEST_TIMEOUT = 25

# سقف کاراکتر پیام در دایرکت اینستاگرام
MAX_DRAFT_CHARS = 640
# حداقل فاصله بین دو درخواست پیشنهاد برای یک مشتری (ثانیه)
COOLDOWN_SECONDS = 5
# حداکثر پیام‌های مکالمه و محصولاتی که در پرامپت می‌روند
MAX_CONTEXT_MESSAGES = 15
MAX_CATALOG_ITEMS = 30


class GeminiError(Exception):
    """خطای قابل نمایش به کاربر؛ پیام فارسی و کد HTTP دارد."""

    def __init__(self, message: str, status_code: int = 502):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


SYSTEM_PROMPT = (
    "تو دستیار فروش پیج اینستاگرام هستی که در حوزه عطر و اسانس فعالیت می‌کند. "
    "وظیفه‌ات نوشتن «پیش‌نویس» جواب دایرکت برای اپراتور پیج است؛ اپراتور متن را "
    "بازبینی می‌کند و بعد می‌فرستد.\n"
    "قواعد سخت‌گیرانه:\n"
    "۱. فقط فارسی روان و صمیمی بنویس؛ مختصر و گویا (حداکثر ۶۰۰ کاراکتر).\n"
    "۲. قیمت، موجودی و مشخصات محصول را فقط از کاتالوگ همین پیام بیاور؛ هرگز قیمت "
    "از خودت نساز و عدد را عوض نکن.\n"
    "۳. اگر محصولی در کاتالوگ نیست، صادقانه بگو موجود نیست و در صورت امکان مشابه پیشنهاد بده.\n"
    "۴. شماره تماس، آدرس یا اطلاعات شخصی از مشتری نخواه، مگر خودش پرسیده باشد.\n"
    "۵. از ایموجی به اندازه و با سلیقه استفاده کن (حداکثر دو سه تا در هر جواب).\n"
    "۶. فقط متن جواب نهایی را خروجی بده؛ بدون «جواب:»، بدون توضیح اضافه، بدون نقل‌قول."
)

# حداقل فاصله بین دو درخواست هر مشتری (کلید: customer.id)
_last_draft_at: dict[int, float] = {}


def _resolve_key(bot) -> str:
    return ((getattr(bot, "gemini_api_key", None) or "").strip()) or env_settings.GEMINI_API_KEY


def _resolve_model(bot) -> str:
    return ((getattr(bot, "gemini_model", None) or "").strip()) or env_settings.GEMINI_MODEL or DEFAULT_MODEL


def build_prompt(db, customer) -> tuple[str, str]:
    """ساخت system/user prompt؛ خروجی: (متن سیستم، متن کاربر)"""
    from app.models.message import Message
    from app.models.product import Product

    messages = (
        db.query(Message)
        .filter(Message.customer_id == customer.id)
        .order_by(Message.created_at.desc(), Message.id.desc())
        .limit(MAX_CONTEXT_MESSAGES)
        .all()
    )
    messages = list(reversed(messages))

    products = (
        db.query(Product)
        .filter(Product.active.is_(True))
        .order_by(Product.id.asc())
        .limit(MAX_CATALOG_ITEMS)
        .all()
    )
    if products:
        catalog_lines = [
            f"- {p.name}: {p.price:,} تومان / {p.unit} | موجودی: {p.stock}"
            + (f" | {p.description.strip()[:80]}" if (p.description or "").strip() else "")
            for p in products
        ]
    else:
        catalog_lines = ["(فعلاً محصولی در کاتالوگ ثبت نشده است)"]

    sender_labels = {"customer": "مشتری", "admin": "اپراتور پیج", "bot": "ربات پیج"}
    conv_lines = [
        f"{sender_labels.get(m.sender, m.sender)}: {m.text.strip()}"
        for m in messages
        if (m.text or "").strip()
    ]
    if not conv_lines:
        conv_lines = ["(هنوز پیامی رد و بدل نشده است)"]

    label = customer.username or customer.name or "مشتری"
    user_text = (
        "=== کاتالوگ محصولات (مبنای قیمت و موجودی) ===\n"
        + "\n".join(catalog_lines)
        + f"\n\n=== آخرین پیام‌های مکالمه با {label} ===\n"
        + "\n".join(conv_lines)
        + "\n\n=== وظیفه ===\n"
        "یک پیشنهاد متن جواب دایرکت برای اپراتور بنویس. فقط متن جواب نهایی را خروجی بده."
    )
    return SYSTEM_PROMPT, user_text


def _check_cooldown(customer_id: int) -> None:
    now = time.monotonic()
    # پاک‌سازی ورودی‌های کهنه تا رشد بی‌قاعده نگیرد
    if len(_last_draft_at) > 200:
        for cid, ts in list(_last_draft_at.items()):
            if now - ts > COOLDOWN_SECONDS:
                del _last_draft_at[cid]
    last = _last_draft_at.get(customer_id, 0.0)
    if now - last < COOLDOWN_SECONDS:
        raise GeminiError("چند ثانیه صبر کنید و دوباره امتحان کنید", 429)
    _last_draft_at[customer_id] = now


def generate_draft(db, customer, bot) -> str:
    """
    تولید پیش‌نویس جواب برای یک مشتری.
    خطاها: GeminiError با پیام فارسی و status_code (400 کلید، 429 سرعت/سهمیه، 502 سرویس).
    """
    key = _resolve_key(bot)
    if not key:
        raise GeminiError(
            "کلید Gemini تنظیم نشده است؛ از تب تنظیمات → «هوش مصنوعی» وارد کنید", 400
        )

    _check_cooldown(customer.id)

    system_text, user_text = build_prompt(db, customer)
    payload = {
        "system_instruction": {"parts": [{"text": system_text}]},
        "contents": [{"role": "user", "parts": [{"text": user_text}]}],
        "generationConfig": {
            "maxOutputTokens": 1024,
            "temperature": 0.6,
        },
    }
    url = f"{BASE_URL}/{_resolve_model(bot)}:generateContent"

    try:
        resp = requests.post(url, params={"key": key}, json=payload, timeout=REQUEST_TIMEOUT)
    except requests.RequestException as e:
        logger.error(f"Gemini request failed: {e}")
        raise GeminiError("اتصال به سرور Gemini برقرار نشد؛ چند لحظه بعد دوباره تلاش کنید")

    if resp.status_code in (400, 401, 403):
        logger.error(f"Gemini auth/config error {resp.status_code}: {resp.text[:300]}")
        raise GeminiError("کلید Gemini نامعتبر است یا دسترسی ندارد؛ کلید را در تنظیمات بررسی کنید", 400)
    if resp.status_code == 429:
        raise GeminiError("سهمیه درخواست Gemini تمام شده؛ کمی بعد دوباره امتحان کنید", 429)
    if resp.status_code != 200:
        logger.error(f"Gemini HTTP {resp.status_code}: {resp.text[:300]}")
        raise GeminiError("پاسخ نامعتبر از سرور Gemini دریافت شد؛ دوباره تلاش کنید")

    try:
        data = resp.json()
        parts = data["candidates"][0]["content"]["parts"]
        text = "".join(p.get("text", "") for p in parts).strip()
    except (ValueError, KeyError, IndexError, TypeError) as e:
        logger.error(f"Gemini bad payload: {e} | {resp.text[:300]}")
        raise GeminiError("پاسخ نامعتبر از سرور Gemini دریافت شد؛ دوباره تلاش کنید")

    if not text:
        raise GeminiError("مدل متنی برنگرداند؛ دوباره تلاش کنید")

    return text[:MAX_DRAFT_CHARS]
