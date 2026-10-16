"""
فاز ۲: پیشنهاد جواب هوشمند (AI Draft)

ادمین در تب گفتگوها دکمه «✨ پیشنهاد» را می‌زند؛ سرویس با در نظر گرفتن
کاتالوگ محصولات و تاریخچه مکالمه، یک پیش‌نویس جواب فارسی آماده می‌کند.
متن در کادر پاسخ پر می‌شود و ادمین قبل از ارسال بازبینی/ویرایش می‌کند —
ارسال بدون تأیید بر عهدهٔ این فاز نیست (ایجنت کامل، فاز ۴).

دو حالت سرویس (تنظیم «سرویس هوش مصنوعی» در پنل):
- gemini: اتصال مستقیم به Google Gemini با کلید Google AI Studio
- openai: هر گیت‌وی سازگار با OpenAI مثل 9Router خودمیزبان روی VPS؛
  کافیست آدرس پایه (تا /v1)، کلید گیت‌وی و نام مدل ثبت‌شده در آن را بدهید.

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


# سرویس‌های AI پشتیبانی‌شده (ai_provider در دیتابیس)
AI_PROVIDERS = ("gemini", "openai")


def _resolve_key(bot) -> str:
    # در هر دو حالت یک فیلد «کلید API» استفاده می‌شود:
    # حالت gemini = کلید Google، حالت openai = کلید گیت‌وی (مثل 9Router)
    return ((getattr(bot, "gemini_api_key", None) or "").strip()) or env_settings.GEMINI_API_KEY


def _resolve_model(bot) -> str:
    return ((getattr(bot, "gemini_model", None) or "").strip()) or env_settings.GEMINI_MODEL or DEFAULT_MODEL


def _resolve_provider(bot) -> str:
    """سرویس AI فعال؛ مقدار نامعتبر یا خالی به gemini برمی‌گردد."""
    provider = ((getattr(bot, "ai_provider", None) or "").strip().lower())
    if provider in AI_PROVIDERS:
        return provider
    env_provider = (env_settings.AI_PROVIDER or "").strip().lower()
    return env_provider if env_provider in AI_PROVIDERS else "gemini"


def _resolve_base_url(bot) -> str:
    """آدرس پایه گیت‌وی (مثل http://IP:3000/v1)؛ اول دیتابیس، بعد env."""
    return ((getattr(bot, "ai_base_url", None) or "").strip()) or (env_settings.AI_BASE_URL or "").strip()


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
    تولید پیش‌نویس جواب برای یک مشتری با سرویس انتخاب‌شده در تنظیمات.
    خطاها: GeminiError با پیام فارسی و status_code (400 کلید/تنظیمات، 429 سرعت/سهمیه، 502 سرویس).
    """
    provider = _resolve_provider(bot)
    base_url = None
    if provider == "openai":
        base_url = _resolve_base_url(bot)
        if not base_url:
            raise GeminiError(
                "آدرس گیت‌وی تنظیم نشده است؛ در تب تنظیمات → «هوش مصنوعی» آدرس پایه "
                "(مثل http://IP-VPS:3000/v1) را وارد کنید", 400
            )
    else:
        if not _resolve_key(bot):
            raise GeminiError(
                "کلید Gemini تنظیم نشده است؛ از تب تنظیمات → «هوش مصنوعی» وارد کنید", 400
            )

    _check_cooldown(customer.id)
    system_text, user_text = build_prompt(db, customer)
    key = _resolve_key(bot)
    model = _resolve_model(bot)

    if provider == "openai":
        return _call_gateway(base_url, key, model, system_text, user_text)
    return _call_gemini(key, model, system_text, user_text)


def _call_gemini(key: str, model: str, system_text: str, user_text: str) -> str:
    """اتصال مستقیم به Google Gemini (generativelanguage.googleapis.com)"""
    payload = {
        "system_instruction": {"parts": [{"text": system_text}]},
        "contents": [{"role": "user", "parts": [{"text": user_text}]}],
        "generationConfig": {
            "maxOutputTokens": 1024,
            "temperature": 0.6,
        },
    }
    url = f"{BASE_URL}/{model}:generateContent"

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


def _call_gateway(base_url: str, key: str, model: str, system_text: str, user_text: str) -> str:
    """اتصال به گیت‌وی سازگار با OpenAI (مثل 9Router خودمیزبان): POST /chat/completions"""
    url = base_url.rstrip("/") + "/chat/completions"
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_text},
            {"role": "user", "content": user_text},
        ],
        "max_tokens": 1024,
        "temperature": 0.6,
    }
    headers = {"Content-Type": "application/json"}
    if key:
        headers["Authorization"] = f"Bearer {key}"

    try:
        resp = requests.post(url, json=payload, headers=headers, timeout=REQUEST_TIMEOUT)
    except requests.RequestException as e:
        logger.error(f"AI gateway request failed: {e}")
        raise GeminiError("اتصال به گیت‌وی هوش مصنوعی برقرار نشد؛ آدرس و روشن بودن سرور را بررسی کنید")

    if resp.status_code in (401, 403):
        logger.error(f"AI gateway auth error {resp.status_code}: {resp.text[:300]}")
        raise GeminiError("کلید گیت‌وی نامعتبر است یا دسترسی ندارد؛ کلید و آدرس را در تنظیمات بررسی کنید", 400)
    if resp.status_code == 404:
        logger.error(f"AI gateway 404: {resp.text[:300]}")
        raise GeminiError("آدرس گیت‌وی نامعتبر است؛ آدرس باید تا /v1 باشد (مثل http://IP:3000/v1)", 400)
    if resp.status_code == 429:
        raise GeminiError("محدودیت نرخ یا سهمیه گیت‌وی؛ کمی بعد دوباره امتحان کنید", 429)
    if resp.status_code in (400, 422):
        logger.error(f"AI gateway rejected request {resp.status_code}: {resp.text[:300]}")
        raise GeminiError("درخواست رد شد؛ نام مدل را بررسی کنید (باید در گیت‌وی ثبت شده باشد)", 400)
    if resp.status_code != 200:
        logger.error(f"AI gateway HTTP {resp.status_code}: {resp.text[:300]}")
        raise GeminiError("پاسخ نامعتبر از گیت‌وی هوش مصنوعی دریافت شد؛ دوباره تلاش کنید")

    try:
        data = resp.json()
        content = data["choices"][0]["message"]["content"]
        if isinstance(content, list):  # برخی گیت‌وی‌ها خروجی بخش‌به‌بخش می‌دهند
            text = "".join(
                p.get("text", "") for p in content if isinstance(p, dict)
            ).strip()
        else:
            text = (content or "").strip()
    except (ValueError, KeyError, IndexError, TypeError) as e:
        logger.error(f"AI gateway bad payload: {e} | {resp.text[:300]}")
        raise GeminiError("پاسخ نامعتبر از گیت‌وی هوش مصنوعی دریافت شد؛ دوباره تلاش کنید")

    if not text:
        raise GeminiError("مدل متنی برنگرداند؛ دوباره تلاش کنید")

    return text[:MAX_DRAFT_CHARS]
