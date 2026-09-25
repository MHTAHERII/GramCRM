import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
from app.config import settings
from app.database import SessionLocal
from app.service.instagram_service import instagram_client
from app.service.chat_service import process_incoming_message

logger = logging.getLogger("ig_worker")
_executor = ThreadPoolExecutor(max_workers=2)


def poll_cycle() -> int:
    """
    یک دور بررسی پیام‌های جدید (Polling):
    پیام‌های خوانده‌نشده را می‌گیرد، در دیتابیس ثبت و پاسخ مناسب را ارسال می‌کند.
    """
    if not settings.ENABLE_IG_WORKER:
        return 0

    try:
        messages = instagram_client.fetch_unread_messages(amount=10)
    except Exception as e:
        logger.error(f"Error fetching unread messages: {e}", exc_info=True)
        return 0

    if not messages:
        return 0

    processed = 0
    db = SessionLocal()
    try:
        for msg in messages:
            try:
                reply = process_incoming_message(
                    db=db,
                    instagram_user_id=msg["user_id"],
                    text=msg["text"],
                    username=msg.get("username"),
                    full_name=msg.get("full_name"),
                    ig_message_id=msg["message_id"],
                    is_new=msg.get("is_new", True)
                )

                if reply:
                    sent = instagram_client.send_direct_message(
                        text=reply,
                        thread_id=msg.get("thread_id"),
                        user_id=msg.get("user_id")
                    )
                    if sent:
                        processed += 1
                        logger.info(
                            f"Replied to {msg.get('username', 'unknown')}: "
                            f"'{reply[:40]}...'"
                        )
                    else:
                        logger.warning(
                            f"Failed to send reply to {msg.get('username', 'unknown')}"
                        )

                # ثبت پیام به عنوان پردازش‌شده (چه جواب داده باشیم چه نه)
                # این جلوی تکرار پردازش پیام قدیمی را می‌گیرد
                instagram_client.mark_processed(
                    thread_id=msg.get("thread_id", ""),
                    message_id=msg.get("message_id", "")
                )

            except Exception as e:
                logger.error(
                    f"Error processing message from {msg.get('username', 'unknown')}: {e}",
                    exc_info=True
                )
    finally:
        db.close()

    return processed


async def run_worker(stop_event: asyncio.Event | None = None):
    """
    تسک آسنکرون پس‌زمینه که در طول اجرای برنامه، به طور مداوم اینباکس را چک می‌کند.
    """
    logger.info(f"Instagram worker started (interval: {settings.IG_POLL_INTERVAL}s)")
    loop = asyncio.get_running_loop()

    while True:
        try:
            count = await loop.run_in_executor(_executor, poll_cycle)
            if count > 0:
                logger.info(f"Poll cycle: replied to {count} message(s).")
        except Exception as e:
            logger.error(f"Worker error: {e}", exc_info=True)

        # وقفه تا دور بعدی بررسی پیام‌ها
        try:
            if stop_event:
                await asyncio.wait_for(stop_event.wait(), timeout=settings.IG_POLL_INTERVAL)
                break
            else:
                await asyncio.sleep(settings.IG_POLL_INTERVAL)
        except asyncio.TimeoutError:
            pass