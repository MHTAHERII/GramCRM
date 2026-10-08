import asyncio
import logging
from fastapi import APIRouter, Request, Depends, HTTPException
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models.customer import Customer
from app.models.message import Message
from app.service.bot_settings import get_bot_settings, REMINDER_NOT_FOLLOWED
from app.service.chat_service import process_incoming_message
from app.service.instagram_service import instagram_client

logger = logging.getLogger("zernio_webhook")

router = APIRouter(
    prefix="/webhook/zernio",
    tags=["Zernio Webhook"]
)


def _record_remote_gate_message(db, text: str | None, sender_id, sender_name) -> None:
    """
    پیام دروازه فالویی که خود زرنیو ارسال کرده در دیتابیس ثبت می‌شود تا
    کول‌داون ۱۵ دقیقه‌ای بات داخلی آن را ببیند و پیام تکراری نفرستد.
    """
    if not text or not sender_id:
        return
    try:
        gate_setting = get_bot_settings(db)
        gate_texts = {
            t.strip() for t in (gate_setting.follow_gate_message, REMINDER_NOT_FOLLOWED) if t
        }
        if text.strip() not in gate_texts:
            return

        customer = (
            db.query(Customer)
            .filter(Customer.instagram_id == str(sender_id))
            .first()
        )
        if not customer:
            customer = Customer(
                instagram_id=str(sender_id),
                username=sender_name,
                name=sender_name,
            )
            db.add(customer)
            db.flush()
        db.add(Message(customer_id=customer.id, text=text.strip(), sender="bot"))
        db.commit()
        logger.debug(f"Recorded remote follow-gate message for user {sender_id} (cooldown tracking).")
    except Exception as e:
        db.rollback()
        logger.debug(f"Could not record remote gate message: {e}")


def _verify_zernio_token(request: Request) -> bool:
    """
    اگر ZERNIO_WEBHOOK_SECRET تنظیم شده باشد، درخواست باید هدر
    X-Zernio-Webhook-Token (یا ?token=) را با مقدار یکسان داشته باشد.
    """
    secret = settings.ZERNIO_WEBHOOK_SECRET
    if not secret:
        return True  # بدون تنظیم، بررسی نمی‌شود
    provided = (
        request.headers.get("X-Zernio-Webhook-Token")
        or request.query_params.get("token")
        or ""
    )
    return provided == secret


@router.get("", summary="تست صحت اندپوینت وب‌هوک Zernio")
@router.get("/", include_in_schema=False)
def check_webhook():
    return {"status": "ok", "service": "Zernio Webhook Endpoint"}


@router.post("", summary="دریافت رویدادهای زنده اینستاگرام از Zernio (دایرکت و کامنت)")
@router.post("/", include_in_schema=False)
async def receive_zernio_webhook(request: Request, db: Session = Depends(get_db)):
    """
    رویدادهای زنده Zernio:
    - message.received: دایرکت جدید از کاربر
    - comment.received: کامنت جدید زیر پست‌ها

    امنیت: اگر ZERNIO_WEBHOOK_SECRET در .env تنظیم شده باشد، درخواست‌های
    بدون توکن صحیح رد می‌شوند. پردازش در نخ جداگانه اجرا می‌شود تا
    event-loop سرور بلوک نشود.
    """
    if not _verify_zernio_token(request):
        logger.warning("Zernio webhook rejected: invalid/missing webhook token.")
        raise HTTPException(status_code=403, detail="Invalid webhook token")

    try:
        payload = await request.json()
    except Exception as e:
        logger.error(f"Failed to parse Zernio webhook JSON: {e}")
        return {"status": "INVALID_JSON"}

    event_type = payload.get("event") or payload.get("type")
    logger.info(f"Received Zernio webhook event: '{event_type}'")

    data = payload.get("data", payload)

    # ۱. مدیریت پیام‌های دایرکت دریافتی
    if event_type == "message.received":
        # استخراج فیلدها از پی‌لود Zernio
        message_obj = data.get("message", data)
        text = message_obj.get("message") or message_obj.get("text")
        sender_id = message_obj.get("senderId")
        sender_name = message_obj.get("senderName")
        conv_id = data.get("conversationId") or message_obj.get("conversationId")
        msg_id = message_obj.get("id")
        direction = message_obj.get("direction", "incoming")

        # نادیده گرفتن پیام‌های ارسالی توسط خود پیج
        if direction == "outgoing":
            # پیام دروازه فالوی ارسالی زرنیو ثبت شود تا بات داخلی تکرار نفرستد
            _record_remote_gate_message(db, text, sender_id, sender_name)
            return {"status": "IGNORED_OUTGOING"}

        if sender_id and text:
            # کش کردن سریع شناسه مکالمه جهت پاسخ‌های بدون تاخیر
            instagram_client.cache_conversation(user_id=sender_id, thread_id=conv_id, username=sender_name)

            logger.info(f"Zernio Webhook: Processing message from {sender_name or sender_id}: '{text[:40]}...'")

            loop = asyncio.get_running_loop()
            reply = await loop.run_in_executor(
                None,
                process_incoming_message,
                db,
                str(sender_id),
                text,
                sender_name,
                sender_name,
                str(msg_id) if msg_id else None,
                True,
            )

            if reply and conv_id:
                sent = await loop.run_in_executor(
                    None,
                    instagram_client.send_direct_message,
                    reply,
                    str(sender_id),
                    str(conv_id),
                )
                if sent:
                    logger.info(f"Zernio Webhook: Replied to {sender_name or sender_id} successfully.")
                else:
                    logger.warning(f"Zernio Webhook: Failed to send reply to {conv_id}")

        return {"status": "MESSAGE_PROCESSED"}

    # ۲. مدیریت کامنت‌های دریافتی
    elif event_type == "comment.received":
        comment_text = data.get("text") or data.get("comment", "")
        commenter_id = data.get("senderId") or data.get("userId")
        commenter_username = data.get("username") or data.get("senderName")
        post_id = data.get("postId") or data.get("mediaId")

        logger.info(f"Zernio Webhook: New comment from @{commenter_username}: '{comment_text[:40]}...'")

        # اگر کاربر در کامنت کلیدواژه‌ای نوشته باشد و اتوماسیون داخلی بخواهد فعال شود
        # Zernio اتوماسیون Comment-to-DM خود را دارد؛ این اندپوینت برای لاگ و پردازش تکمیلی است.

        return {"status": "COMMENT_LOGGED"}

    return {"status": "EVENT_ACKNOWLEDGED", "event": event_type}
