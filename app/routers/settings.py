from fastapi import APIRouter, Depends, BackgroundTasks
from sqlalchemy.orm import Session

from app.auth import require_auth
from app.database import get_db, SessionLocal
from app.schemas.bot_setting import BotSettingResponse, BotSettingUpdate
from app.service.bot_settings import get_bot_settings, DEFAULT_FALLBACK_REPLY, DEFAULT_FOLLOW_GATE_MESSAGE
from app.service.zernio_service import zernio_service

router = APIRouter(prefix="/settings", tags=["Settings"], dependencies=[Depends(require_auth)])


def _sync_zernio_bg():
    """همگام‌سازی کلیدواژه‌ها و تنظیمات با Zernio در پس‌زمینه"""
    try:
        db = SessionLocal()
        zernio_service.sync_all_keywords(db)
    except Exception as e:
        import logging
        logging.getLogger("settings_router").error(f"Failed to auto-sync to Zernio: {e}")
    finally:
        db.close()


@router.get("/", response_model=BotSettingResponse)
def get_settings(db: Session = Depends(get_db)):
    return get_bot_settings(db)


@router.put("/", response_model=BotSettingResponse)
def update_settings(data: BotSettingUpdate, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    setting = get_bot_settings(db)

    if data.bot_enabled is not None:
        setting.bot_enabled = data.bot_enabled
    if data.fallback_message is not None:
        stripped = data.fallback_message.strip()
        setting.fallback_message = stripped if stripped else DEFAULT_FALLBACK_REPLY
    if data.follow_gate_enabled is not None:
        setting.follow_gate_enabled = data.follow_gate_enabled
    if data.follow_gate_message is not None:
        stripped = data.follow_gate_message.strip()
        setting.follow_gate_message = stripped if stripped else DEFAULT_FOLLOW_GATE_MESSAGE
    if data.comment_reply_enabled is not None:
        setting.comment_reply_enabled = data.comment_reply_enabled
    if data.comment_public_reply_enabled is not None:
        setting.comment_public_reply_enabled = data.comment_public_reply_enabled
    if data.comment_public_reply_text is not None:
        stripped = data.comment_public_reply_text.strip()
        setting.comment_public_reply_text = stripped if stripped else "پاسخ براتون دایرکت شد 🌸"

    db.commit()
    db.refresh(setting)

    background_tasks.add_task(_sync_zernio_bg)
    return setting
