import logging
from fastapi import APIRouter, Request, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.service.chat_service import process_incoming_message
from app.service.instagram_service import instagram_client

logger = logging.getLogger("zernio_webhook")

router = APIRouter(
    prefix="/webhook/zernio",
    tags=["Zernio Webhook"]
)


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
    """
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
            return {"status": "IGNORED_OUTGOING"}

        if sender_id and text:
            # کش کردن سریع شناسه مکالمه جهت پاسخ‌های بدون تاخیر
            instagram_client.cache_conversation(user_id=sender_id, thread_id=conv_id, username=sender_name)

            logger.info(f"Zernio Webhook: Processing message from {sender_name or sender_id}: '{text[:40]}...'")
            reply = process_incoming_message(
                db=db,
                instagram_user_id=str(sender_id),
                text=text,
                username=sender_name,
                full_name=sender_name,
                ig_message_id=str(msg_id) if msg_id else None,
                is_new=True
            )

            if reply and conv_id:
                sent = instagram_client.send_direct_message(
                    text=reply,
                    thread_id=str(conv_id),
                    user_id=str(sender_id)
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
