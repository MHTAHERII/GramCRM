import asyncio
import hashlib
import hmac
import logging
from fastapi import APIRouter, Request, Response, Query, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.service.chat_service import process_incoming_message, drop_unsent_reply
from app.service.instagram_service import instagram_client

logger = logging.getLogger("meta_webhook")

router = APIRouter(
    prefix="/webhook",
    tags=["Meta Webhook"]
)

_meta_secret_warned = False


def _verify_meta_signature(body: bytes, signature_header: str | None) -> bool:
    """تأیید امضای X-Hub-Signature-256 متا با App Secret"""
    if not settings.META_APP_SECRET:
        return True  # بدون App Secret تنظیم‌شده، امضا بررسی نمی‌شود (با هشدار)
    if not signature_header:
        return False
    try:
        algo, _, received_sig = signature_header.partition("=")
        if algo.lower() != "sha256" or not received_sig:
            return False
        expected = hmac.new(
            settings.META_APP_SECRET.encode("utf-8"), body, hashlib.sha256
        ).hexdigest()
        return hmac.compare_digest(expected, received_sig.strip())
    except Exception:
        return False


@router.get("", summary="تأیید اولیه وب‌هوک توسط متا (Verification Challenge)")
@router.get("/", include_in_schema=False)
def verify_webhook(
    hub_mode: str = Query(None, alias="hub.mode"),
    hub_verify_token: str = Query(None, alias="hub.verify_token"),
    hub_challenge: str = Query(None, alias="hub.challenge"),
):
    """
    متا هنگام ست کردن آدرس وب‌هوک این اندپوینت را فراخوانی می‌کند تا توکن و سرور را تایید کند.
    """
    logger.info(f"Webhook verification request received. mode={hub_mode}, token={hub_verify_token}")

    if hub_mode == "subscribe" and hub_verify_token == settings.META_VERIFY_TOKEN:
        logger.info("Webhook verification succeeded.")
        return Response(content=hub_challenge, media_type="text/plain")

    logger.warning("Webhook verification failed: token mismatch or invalid mode.")
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Verification token mismatch"
    )


@router.post("", summary="دریافت رویدادها و دایرکت‌های اینستاگرام از متا")
@router.post("/", include_in_schema=False)
async def receive_webhook(request: Request, db: Session = Depends(get_db)):
    """
    متا با هر دایرکت جدید، رویداد را به این متد POST ارسال می‌کند.
    پیام بلافاصله به chat_service پاس داده شده و پاسخ تولید و ارسال می‌شود.

    نکات امنیتی/عملکردی:
    - امضای HMAC-SHA256 متا (X-Hub-Signature-256) بررسی می‌شود (اگر META_APP_SECRET تنظیم باشد).
    - پردازش همگام (DB + HTTP) در نخ اجرای رویداد اجرا می‌شود تا event loop بلوک نشود.
    """
    global _meta_secret_warned
    body = await request.body()

    if settings.META_APP_SECRET:
        if not _verify_meta_signature(body, request.headers.get("X-Hub-Signature-256")):
            logger.warning("Meta webhook rejected: invalid signature.")
            raise HTTPException(status_code=403, detail="Invalid signature")
    elif not _meta_secret_warned:
        _meta_secret_warned = True
        logger.warning(
            "META_APP_SECRET تنظیم نشده است؛ امضای وب‌هوک‌های متا بررسی نمی‌شود. "
            "برای امنیت، META_APP_SECRET را در .env قرار دهید."
        )

    try:
        payload = await request.json()
    except Exception as e:
        logger.error(f"Failed to parse webhook JSON body: {e}")
        return {"status": "INVALID_JSON"}

    # فقط خلاصه رویداد لاگ می‌شود تا اطلاعات حساس پیام‌ها در لاگ‌ها نماند
    logger.info(
        f"Webhook payload received (object={payload.get('object')}, "
        f"entries={len(payload.get('entry', []))}, bytes={len(body)})"
    )

    # بررسی نوع آبجکت ارسالی متا (instagram یا page)
    if payload.get("object") in ["instagram", "page"]:
        events = []
        for entry in payload.get("entry", []):
            for event in entry.get("messaging", []):
                sender_id = event.get("sender", {}).get("id")
                message_data = event.get("message", {})

                # پیام‌های اکو (پیام‌هایی که خود صفحه ارسال کرده) نادیده گرفته شوند
                if message_data.get("is_echo"):
                    continue

                mid = message_data.get("mid")
                text = message_data.get("text")
                if not text and event.get("postback"):
                    text = event.get("postback", {}).get("payload") or event.get("postback", {}).get("title")
                if not text and message_data.get("quick_reply"):
                    text = message_data.get("quick_reply", {}).get("payload")

                if sender_id and text:
                    events.append((str(sender_id), text, str(mid) if mid else None))

        # پردازش در نخ جداگانه تا event-loop سرور (وب‌سوکت/پنل) بلوک نشود
        loop = asyncio.get_running_loop()
        for sender_id, text, mid in events:
            logger.info(f"Processing inbound DM from {sender_id}: '{text[:30]}...'")
            try:
                reply_text = await loop.run_in_executor(
                    None,
                    process_incoming_message,
                    db,
                    sender_id,
                    text,
                    None,
                    None,
                    mid,
                    True,
                )
                if reply_text:
                    sent = await loop.run_in_executor(
                        None,
                        instagram_client.send_direct_message_with_retry,
                        reply_text,
                        sender_id,
                        None,
                    )
                    if sent:
                        logger.info(f"Replied to {sender_id} via Meta Graph API successfully.")
                    else:
                        logger.error(
                            f"Failed to send reply to {sender_id} after retries; "
                            "dropping unsent record so history stays accurate."
                        )
                        await loop.run_in_executor(
                            None, drop_unsent_reply, db, sender_id, reply_text
                        )
            except Exception as e:
                logger.error(f"Error processing Meta webhook event from {sender_id}: {e}", exc_info=True)

    # متا همیشه انتظار پاسخ 200 OK سریع دارد
    return {"status": "EVENT_RECEIVED"}
