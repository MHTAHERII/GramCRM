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
    setting = get_bot_settings(db)
    return BotSettingResponse(
        id=setting.id,
        bot_enabled=setting.bot_enabled,
        fallback_message=setting.fallback_message,
        follow_gate_enabled=setting.follow_gate_enabled,
        follow_gate_message=setting.follow_gate_message,
        comment_reply_enabled=setting.comment_reply_enabled,
        comment_public_reply_enabled=setting.comment_public_reply_enabled,
        comment_public_reply_text=setting.comment_public_reply_text,
        admin_username=setting.admin_username or "admin",
        has_custom_password=bool(setting.admin_password),
        zernio_api_key=setting.zernio_api_key,
        zernio_profile_id=setting.zernio_profile_id,
        zernio_account_id=setting.zernio_account_id,
        updated_at=setting.updated_at
    )


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

    # تنظیمات کاربری و امنیت
    if data.admin_username is not None and data.admin_username.strip():
        setting.admin_username = data.admin_username.strip()
    if data.admin_password is not None and data.admin_password.strip():
        setting.admin_password = data.admin_password.strip()

    # تنظیمات توکن و شناسه‌های API اینستاگرام (Zernio)
    if data.zernio_api_key is not None:
        setting.zernio_api_key = data.zernio_api_key.strip() if data.zernio_api_key.strip() else None
    if data.zernio_profile_id is not None:
        setting.zernio_profile_id = data.zernio_profile_id.strip() if data.zernio_profile_id.strip() else None
    if data.zernio_account_id is not None:
        setting.zernio_account_id = data.zernio_account_id.strip() if data.zernio_account_id.strip() else None

    db.commit()
    db.refresh(setting)

    from app.service.bot_settings import apply_credentials_to_services
    apply_credentials_to_services(setting)

    background_tasks.add_task(_sync_zernio_bg)

    return BotSettingResponse(
        id=setting.id,
        bot_enabled=setting.bot_enabled,
        fallback_message=setting.fallback_message,
        follow_gate_enabled=setting.follow_gate_enabled,
        follow_gate_message=setting.follow_gate_message,
        comment_reply_enabled=setting.comment_reply_enabled,
        comment_public_reply_enabled=setting.comment_public_reply_enabled,
        comment_public_reply_text=setting.comment_public_reply_text,
        admin_username=setting.admin_username or "admin",
        has_custom_password=bool(setting.admin_password),
        zernio_api_key=setting.zernio_api_key,
        zernio_profile_id=setting.zernio_profile_id,
        zernio_account_id=setting.zernio_account_id,
        updated_at=setting.updated_at
    )


@router.post("/test-connection", summary="بررسی وضعیت اتصال به اینستاگرام و Zernio")
def test_connection(db: Session = Depends(get_db)):
    """تست زنده توکن و شناسه‌ها جهت اطمینان از صحت ارتباط با اینستاگرام"""
    setting = get_bot_settings(db)
    if not zernio_service.is_configured():
        return {
            "success": False,
            "message": "توکن API، شناسه Profile یا شناسه Account هنوز کامل وارد نشده‌اند."
        }
    try:
        automations = zernio_service.list_comment_automations()
        return {
            "success": True,
            "message": "اتصال به اینستاگرام و Zernio با موفقیت برقرار است! ✅",
            "automations_count": len(automations)
        }
    except Exception as e:
        return {
            "success": False,
            "message": f"خطا در برقراری ارتباط: {str(e)}"
        }
