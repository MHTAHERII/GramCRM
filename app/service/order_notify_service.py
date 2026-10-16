"""
فاز ۱: اعلان خودکار وضعیت سفارش در دایرکت مشتری

هنگامی که ادمین وضعیت سفارش را در پنل تغییر می‌دهد (تأیید / ارسال / لغو)،
یک پیام خودکار با متن قابل ویرایش برای مشتری ارسال می‌شود.

نکات:
- پنجره پیام‌رسانی ۲۴ ساعته اینستاگرام رعایت می‌شود؛ خارج از پنجره، اعلان
  در صف می‌ماند و به محض پیام مشتری (باز شدن پنجره) ارسال خواهد شد.
- همه توابع این ماژول سینک هستند و باید در نخ جدا (thread/executor) اجرا شوند.
"""
import asyncio
import logging
from datetime import datetime, timedelta

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models.bot_setting import BotSetting
from app.models.customer import Customer
from app.models.message import Message
from app.models.order import Order

logger = logging.getLogger("order_notify")

# وضعیت‌هایی که برایشان اعلان ارسال می‌شود
NOTIFY_STATUSES = ("confirmed", "shipped", "cancelled")

# برچسب فارسی وضعیت‌ها (برای متغیر {status} در متن)
STATUS_LABELS = {
    "pending": "در انتظار",
    "confirmed": "تأیید شد",
    "shipped": "ارسال شد",
    "cancelled": "لغو شد",
}

# متن پیش‌فرض هر وضعیت — وقتی ادمین متنی ذخیره نکرده (یا خالی گذاشته) استفاده می‌شود
DEFAULT_TEMPLATES = {
    "confirmed": (
        "سلام {recipient} عزیز 🌸\n"
        "سفارش «{product}» شما تأیید شد و در صف آماده‌سازیه.\n"
        "تعداد: {quantity} {unit} | مبلغ کل: {total} تومان\n"
        "به‌زودی براتون ارسال می‌شه 📦"
    ),
    "shipped": (
        "سلام {recipient} عزیز 📦\n"
        "سفارش «{product}» شما ارسال شد!\n"
        "کد رهگیری: {tracking}\n"
        "با این کد می‌تونید مرسوله رو پیگیری کنید. ممنون که به ما اعتماد کردید 🌸"
    ),
    "cancelled": (
        "سلام {recipient} عزیز\n"
        "سفارش «{product}» شما لغو شد.\n"
        "اگه سؤالی دارید یا می‌خواید دوباره ثبت کنید، در همین دایرکت در خدمتم 🌸"
    ),
}

# فاصله چرخه بررسی صف اعلان‌ها (ثانیه)
FLUSH_INTERVAL_SECONDS = 30
# حداقل فاصله بین دو تلاش ارسال یک اعلان (جلوگیری از اسپم API)
FLUSH_GRACE_SECONDS = 60


def _fmt_amount(value) -> str:
    try:
        return f"{int(value):,}"
    except (TypeError, ValueError):
        return str(value)


def get_template(bot: BotSetting, status: str) -> str:
    """متن اعلان یک وضعیت؛ خالی/ذخیره‌نشده → متن پیش‌فرض سیستم"""
    stored = {
        "confirmed": getattr(bot, "order_notify_confirmed", None),
        "shipped": getattr(bot, "order_notify_shipped", None),
        "cancelled": getattr(bot, "order_notify_cancelled", None),
    }.get(status, "")
    text = (stored or "").strip()
    return text or DEFAULT_TEMPLATES[status]


def render_template(text: str, order: Order) -> str:
    """جایگزینی متغیرهای {product}، {quantity}، {unit}، {total}، {tracking}، {recipient}، {order_id}، {status}"""
    values = {
        "product": order.product_name,
        "quantity": order.quantity,
        "unit": order.unit,
        "total": _fmt_amount(order.total_price),
        "tracking": order.tracking_code or "—",
        "recipient": order.recipient_name,
        "order_id": order.id,
        "status": STATUS_LABELS.get(order.status, order.status),
    }
    for key, value in values.items():
        text = text.replace("{" + key + "}", str(value))
    return text


def last_customer_message_at(db: Session, customer_id: int) -> datetime | None:
    """آخرین زمانی که خود مشتری پیام فرستاده (مبنای پنجره ۲۴ ساعته)"""
    return (
        db.query(func.max(Message.created_at))
        .filter(Message.customer_id == customer_id, Message.sender == "customer")
        .scalar()
    )


def within_messaging_window(db: Session, customer_id: int, hours: int = 24) -> bool:
    last_at = last_customer_message_at(db, customer_id)
    if not last_at:
        return False
    return datetime.utcnow() - last_at <= timedelta(hours=hours)


def notify_order_status(db: Session, order_id: int) -> str:
    """
    ارسال فوری اعلان وضعیت سفارش. باید در نخ جدا اجرا شود.

    خروجی: sent | queued_window | disabled | already | skipped | failed | not_found
    """
    order = db.get(Order, order_id)
    if not order:
        return "not_found"
    if order.status not in NOTIFY_STATUSES:
        return "skipped"

    from app.service.bot_settings import get_bot_settings
    bot = get_bot_settings(db)

    # اعلان از پنل خاموش است → هیچ صفی باقی نماند
    if not getattr(bot, "order_notify_enabled", True):
        if order.notify_pending:
            order.notify_pending = False
            order.notify_error = "اعلان وضعیت از تنظیمات غیرفعال است"
            order.notify_updated_at = datetime.utcnow()
            db.commit()
        return "disabled"

    # همین وضعیت قبلاً اطلاع‌رسانی شده و چیزی در صف نیست → تکرار نشود
    if not order.notify_pending and order.notified_status == order.status:
        return "already"

    customer = db.get(Customer, order.customer_id)
    if not customer:
        order.notify_pending = False
        order.notify_error = "مشتری سفارش پیدا نشد"
        order.notify_updated_at = datetime.utcnow()
        db.commit()
        return "failed"

    # رعایت پنجره ۲۴ ساعته اینستاگرام
    if not within_messaging_window(db, order.customer_id):
        order.notify_pending = True
        order.notify_error = "خارج از پنجره ۲۴ ساعته — با اولین پیام مشتری ارسال می‌شود"
        order.notify_updated_at = datetime.utcnow()
        db.commit()
        logger.info(f"Order #{order.id} notification queued (outside 24h window).")
        return "queued_window"

    text = render_template(get_template(bot, order.status), order)

    thread_id = None
    try:
        from app.service.instagram_service import instagram_client
        thread_id = instagram_client.find_conversation_id(customer.instagram_id)
        sent = instagram_client.send_direct_message_with_retry(
            text=text,
            user_id=customer.instagram_id,
            thread_id=thread_id,
            attempts=2,
            backoff_seconds=1,
        )
    except Exception as e:
        logger.error(f"Order #{order.id} notification send error: {e}", exc_info=True)
        sent = False

    now = datetime.utcnow()
    if sent:
        order.notify_pending = False
        order.notified_status = order.status
        order.notify_error = None
        order.notify_updated_at = now
        db.commit()
        logger.info(
            f"Order #{order.id} status notification '{order.status}' sent to {customer.instagram_id}."
        )
        return "sent"

    order.notify_pending = True
    order.notify_error = "ارسال ناموفق؛ در صف تلاش مجدد"
    order.notify_updated_at = now
    db.commit()
    return "failed"


def send_order_notification_task(order_id: int) -> None:
    """ورودی BackgroundTasks پنل — سشن خودش را می‌سازد چون بعد از پاسخ HTTP اجرا می‌شود."""
    db = SessionLocal()
    try:
        notify_order_status(db, order_id)
    except Exception as e:
        logger.error(f"Order notification task failed for #{order_id}: {e}", exc_info=True)
        db.rollback()
    finally:
        db.close()


def flush_pending_notifications(db: Session | None = None, limit: int = 10) -> int:
    """
    ارسال اعلان‌های در صف (مثلاً بعد از باز شدن پنجره ۲۴ ساعته با پیام مشتری).
    فقط سفارش‌هایی که آخرین تلاش‌شان حداقل FLUSH_GRACE_SECONDS پیش بوده برداشته می‌شوند.
    """
    own_session = db is None
    if own_session:
        db = SessionLocal()
    sent = 0
    try:
        cutoff = datetime.utcnow() - timedelta(seconds=FLUSH_GRACE_SECONDS)
        pending = (
            db.query(Order)
            .filter(Order.notify_pending.is_(True))
            .filter(Order.status.in_(NOTIFY_STATUSES))
            .filter((Order.notify_updated_at.is_(None)) | (Order.notify_updated_at < cutoff))
            .order_by(Order.id.desc())
            .limit(limit)
            .all()
        )
        for order in pending:
            try:
                if notify_order_status(db, order.id) == "sent":
                    sent += 1
            except Exception as e:
                logger.error(f"Flush failed for order #{order.id}: {e}", exc_info=True)
                db.rollback()
        return sent
    finally:
        if own_session:
            db.close()


async def run_order_notify_worker(stop_event: asyncio.Event | None = None):
    """تسک پس‌زمینه: هر چند ثانیه اعلان‌های در صف را بررسی و ارسال می‌کند."""
    logger.info(
        f"Order notification worker started (interval: {FLUSH_INTERVAL_SECONDS}s)"
    )
    loop = asyncio.get_running_loop()
    while True:
        try:
            await loop.run_in_executor(None, flush_pending_notifications)
        except Exception as e:
            logger.error(f"Order notify worker error: {e}", exc_info=True)

        try:
            if stop_event:
                await asyncio.wait_for(stop_event.wait(), timeout=FLUSH_INTERVAL_SECONDS)
                break
            else:
                await asyncio.sleep(FLUSH_INTERVAL_SECONDS)
        except asyncio.TimeoutError:
            pass
    logger.info("Order notification worker stopped.")
