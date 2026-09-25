import logging
from fastapi import APIRouter, Request, Response, Query, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.service.chat_service import process_incoming_message
from app.service.instagram_service import instagram_client

logger = logging.getLogger("meta_webhook")

router = APIRouter(
    prefix="/webhook",
    tags=["Meta Webhook"]
)


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
    """
    try:
        payload = await request.json()
    except Exception as e:
        logger.error(f"Failed to parse webhook JSON body: {e}")
        return {"status": "INVALID_JSON"}

    logger.info(f"Webhook payload received: {payload}")

    # بررسی نوع آبجکت ارسالی متا (instagram یا page)
    if payload.get("object") in ["instagram", "page"]:
        for entry in payload.get("entry", []):
            for event in entry.get("messaging", []):
                sender_id = event.get("sender", {}).get("id")
                message_data = event.get("message", {})

                # پیام‌های اکو (پیام‌هایی که خود صفحه ارسال کرده) نادیده گرفته شوند
                if message_data.get("is_echo"):
                    continue

                mid = message_data.get("mid")
                text = message_data.get("text")

                if sender_id and text:
                    logger.info(f"Processing inbound DM from {sender_id}: '{text[:30]}...'")
                    reply_text = process_incoming_message(
                        db=db,
                        instagram_user_id=str(sender_id),
                        text=text,
                        ig_message_id=str(mid) if mid else None,
                        is_new=True
                    )

                    if reply_text:
                        sent = instagram_client.send_direct_message(
                            text=reply_text,
                            user_id=str(sender_id)
                        )
                        if sent:
                            logger.info(f"Replied to {sender_id} via Meta Graph API successfully.")
                        else:
                            logger.error(f"Failed to send reply to {sender_id} via Meta Graph API.")

    # متا همیشه انتظار پاسخ 200 OK سریع دارد
    return {"status": "EVENT_RECEIVED"}
