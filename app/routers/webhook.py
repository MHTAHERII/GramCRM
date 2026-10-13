import asyncio
import hashlib
import hmac
import logging
import time
from typing import Any

from fastapi import APIRouter, Request, Response, Query, HTTPException, status

from app.config import settings
from app.database import SessionLocal
from app.service.chat_service import process_incoming_message, drop_unsent_reply
from app.service.instagram_service import instagram_client

logger = logging.getLogger("meta_webhook")

router = APIRouter(
    prefix="/webhook",
    tags=["Meta Webhook"]
)

_meta_secret_warned = False

# درون‌حافظه‌ای برای جلوگیری از پردازش دوباره رویدادها (idempotency)
_processed_event_cache: dict[str, float] = {}
_processed_cache_lock = asyncio.Lock()
webhook_queue: asyncio.Queue = asyncio.Queue()


def _verify_meta_signature(body: bytes, signature_header: str | None) -> bool:
    """تأیید امضای X-Hub-Signature-256 متا با App Secret"""
    if not settings.META_APP_SECRET:
        return True
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
    logger.info(f"Webhook verification request received. mode={hub_mode}, token={hub_verify_token}")

    if hub_mode == "subscribe" and hub_verify_token == settings.META_VERIFY_TOKEN:
        logger.info("Webhook verification succeeded.")
        return Response(content=hub_challenge, media_type="text/plain")

    logger.warning("Webhook verification failed: token mismatch or invalid mode.")
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Verification token mismatch"
    )


def _event_fingerprint(sender_id: str, text: str, mid: str | None) -> str:
    if mid:
        return f"mid:{mid}"
    # fallback: deterministic fingerprint of sender+text
    key = f"{sender_id}:{text}"
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


async def _is_duplicate_and_mark(fingerprint: str) -> bool:
    """Returns True if duplicate (recently seen). Otherwise mark and return False."""
    now = time.time()
    ttl = getattr(settings, "WEBHOOK_DEDUP_TTL_SECONDS", 300)
    async with _processed_cache_lock:
        ts = _processed_event_cache.get(fingerprint)
        if ts and (now - ts) < ttl:
            return True
        # otherwise mark and prune expired entries opportunistically
        _processed_event_cache[fingerprint] = now
        # prune some expired keys to bound memory
        if len(_processed_event_cache) > 10000:
            cutoff = now - ttl
            keys_to_remove = [k for k, v in _processed_event_cache.items() if v < cutoff]
            for k in keys_to_remove:
                _processed_event_cache.pop(k, None)
        return False


async def enqueue_event(event: dict[str, Any]) -> bool:
    """Attempt to enqueue event. Returns True if enqueued, False if deduped."""
    fp = _event_fingerprint(event.get("sender_id"), event.get("text", ""), event.get("mid"))
    dup = await _is_duplicate_and_mark(fp)
    if dup:
        logger.info(f"Dropping duplicate webhook event (fp={fp[:8]})")
        return False
    try:
        webhook_queue.put_nowait(event)
        logger.debug(f"Enqueued webhook event (fp={fp[:8]})")
        return True
    except Exception as e:
        logger.error(f"Failed to enqueue webhook event: {e}")
        return False


@router.post("", summary="دریافت رویدادها و دایرکت‌های اینستاگرام از متا")
@router.post("/", include_in_schema=False)
async def receive_webhook(request: Request):
    """Lightweight request handler: verify, parse, enqueue, and ack quickly."""
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

    logger.info(
        f"Webhook payload received (object={payload.get('object')}, entries={len(payload.get('entry', []))}, bytes={len(body)})"
    )

    # only handle instagram/page messaging entries here
    if payload.get("object") in ["instagram", "page"]:
        for entry in payload.get("entry", []):
            for event in entry.get("messaging", []):
                sender_id = event.get("sender", {}).get("id")
                message_data = event.get("message", {})
                if message_data.get("is_echo"):
                    continue
                mid = message_data.get("mid")
                text = message_data.get("text")
                if not text and event.get("postback"):
                    text = event.get("postback", {}).get("payload") or event.get("postback", {}).get("title")
                if not text and message_data.get("quick_reply"):
                    text = message_data.get("quick_reply", {}).get("payload")
                if sender_id and text:
                    evt = {"sender_id": str(sender_id), "text": text, "mid": str(mid) if mid else None, "raw": event}
                    enqueued = await enqueue_event(evt)
                    if enqueued:
                        logger.info(f"Accepted webhook event from {sender_id} (len text={len(text)})")

    # acknowledge quickly
    return {"status": "EVENT_RECEIVED"}


# Worker implementation: runs in event loop, dispatches sync work into threads.
def _handle_event_sync(event: dict[str, Any]) -> None:
    """Executed inside a thread: create DB session locally and perform processing."""
    db = SessionLocal()
    try:
        sender_id = event.get("sender_id")
        text = event.get("text")
        mid = event.get("mid")
        try:
            reply_text = process_incoming_message(db, sender_id, text, None, None, mid, True)
            if reply_text:
                sent = instagram_client.send_direct_message_with_retry(reply_text, sender_id, None)
                if not sent:
                    logger.error(f"Failed to send reply to {sender_id}; dropping unsent record.")
                    drop_unsent_reply(db, sender_id, reply_text)
            # mark processed in instagram client cache/state to avoid reprocessing on other pollers
            instagram_client.mark_processed(thread_id=None, message_id=mid or "")
        except Exception as e:
            logger.error(f"Error processing webhook event for {sender_id}: {e}", exc_info=True)
    finally:
        try:
            db.close()
        except Exception:
            pass


async def _webhook_worker(stop_event: asyncio.Event | None = None):
    logger.info("Webhook worker started.")
    loop = asyncio.get_running_loop()
    while not (stop_event and stop_event.is_set()):
        try:
            event = await asyncio.wait_for(webhook_queue.get(), timeout=1.0)
        except asyncio.TimeoutError:
            continue
        try:
            # run the synchronous processing in a thread so the event loop stays free
            await loop.run_in_executor(None, _handle_event_sync, event)
        except Exception as e:
            logger.error(f"Exception in webhook worker while handling event: {e}", exc_info=True)
        finally:
            try:
                webhook_queue.task_done()
            except Exception:
                pass

    logger.info("Webhook worker stopped.")


async def start_webhook_workers(stop_event: asyncio.Event | None = None, worker_count: int = 1):
    tasks = [asyncio.create_task(_webhook_worker(stop_event)) for _ in range(max(1, worker_count))]
    await asyncio.gather(*tasks)


# helper for tests/monitoring
def get_queue_size() -> int:
    return webhook_queue.qsize()
