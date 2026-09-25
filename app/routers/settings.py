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
        follow_gate_buttons=setting.follow_gate_buttons or (
            [{"title": setting.follow_gate_button_title, "url": setting.follow_gate_button_url}]
            if (setting.follow_gate_button_title and setting.follow_gate_button_url) else []
        ),
        follow_gate_button_title=setting.follow_gate_button_title,
        follow_gate_button_url=setting.follow_gate_button_url,
        comment_reply_enabled=setting.comment_reply_enabled,
        comment_public_reply_enabled=setting.comment_public_reply_enabled,
        comment_public_reply_text=setting.comment_public_reply_text,
        admin_username=setting.admin_username or "admin",
        has_custom_password=bool(setting.admin_password),
        zernio_api_key=setting.zernio_api_key,
        zernio_profile_id=setting.zernio_profile_id,
        zernio_account_id=setting.zernio_account_id,
        instagram_username=setting.instagram_username,
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

    if data.follow_gate_buttons is not None:
        btn_list = []
        for b in data.follow_gate_buttons:
            t = b.get("title", "").strip() if isinstance(b, dict) else ""
            u = b.get("url", "").strip() if isinstance(b, dict) else ""
            if t and u:
                btn_list.append({"title": t, "url": u})
        setting.follow_gate_buttons = btn_list
        setting.follow_gate_button_title = btn_list[0]["title"] if btn_list else None
        setting.follow_gate_button_url = btn_list[0]["url"] if btn_list else None
    elif data.follow_gate_button_title is not None or data.follow_gate_button_url is not None:
        if data.follow_gate_button_title is not None:
            setting.follow_gate_button_title = data.follow_gate_button_title.strip() if data.follow_gate_button_title.strip() else None
        if data.follow_gate_button_url is not None:
            setting.follow_gate_button_url = data.follow_gate_button_url.strip() if data.follow_gate_button_url.strip() else None
        if setting.follow_gate_button_title and setting.follow_gate_button_url:
            setting.follow_gate_buttons = [{"title": setting.follow_gate_button_title, "url": setting.follow_gate_button_url}]
        elif data.follow_gate_button_title == "" or data.follow_gate_button_url == "":
            setting.follow_gate_buttons = []
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
    api_key_changed = False
    if data.zernio_api_key is not None:
        new_key = data.zernio_api_key.strip() if data.zernio_api_key.strip() else None
        if new_key != setting.zernio_api_key:
            api_key_changed = True
        setting.zernio_api_key = new_key

    if data.zernio_profile_id is not None:
        setting.zernio_profile_id = data.zernio_profile_id.strip() if data.zernio_profile_id.strip() else None
    if data.zernio_account_id is not None:
        setting.zernio_account_id = data.zernio_account_id.strip() if data.zernio_account_id.strip() else None
    if data.instagram_username is not None:
        setting.instagram_username = data.instagram_username.strip() if data.instagram_username.strip() else None

    # کشف و پر کردن خودکار شناسه‌های Account و Profile از روی توکن، در صورتی که کاربر آن‌ها را وارد نکرده باشد
    if setting.zernio_api_key and (not setting.zernio_account_id or not setting.zernio_profile_id or api_key_changed):
        try:
            disc = zernio_service.discover_account_and_profile(setting.zernio_api_key)
            if disc:
                if not setting.zernio_account_id or api_key_changed:
                    setting.zernio_account_id = disc.get("account_id") or setting.zernio_account_id
                if not setting.zernio_profile_id or api_key_changed:
                    setting.zernio_profile_id = disc.get("profile_id") or setting.zernio_profile_id
                if disc.get("username"):
                    setting.instagram_username = disc.get("username")
        except Exception as e:
            import logging
            logging.getLogger("settings_router").warning(f"Failed to auto-discover credentials: {e}")

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
        follow_gate_buttons=setting.follow_gate_buttons or (
            [{"title": setting.follow_gate_button_title, "url": setting.follow_gate_button_url}]
            if (setting.follow_gate_button_title and setting.follow_gate_button_url) else []
        ),
        follow_gate_button_title=setting.follow_gate_button_title,
        follow_gate_button_url=setting.follow_gate_button_url,
        comment_reply_enabled=setting.comment_reply_enabled,
        comment_public_reply_enabled=setting.comment_public_reply_enabled,
        comment_public_reply_text=setting.comment_public_reply_text,
        admin_username=setting.admin_username or "admin",
        has_custom_password=bool(setting.admin_password),
        zernio_api_key=setting.zernio_api_key,
        zernio_profile_id=setting.zernio_profile_id,
        zernio_account_id=setting.zernio_account_id,
        instagram_username=setting.instagram_username,
        updated_at=setting.updated_at
    )


@router.post("/auto-discover", summary="استعلام خودکار اطلاعات اکانت و پروفایل از Zernio با توکن")
def auto_discover_zernio(payload: dict | None = None, db: Session = Depends(get_db)):
    """استعلام خودکار و ذخیره شناسه اکانت و پروفایل تنها با وارد کردن توکن"""
    setting = get_bot_settings(db)
    api_key = None
    if payload and isinstance(payload, dict):
        api_key = payload.get("api_key")
    token = (api_key or setting.zernio_api_key or "").strip()
    if not token:
        return {
            "success": False,
            "message": "لطفاً ابتدا کلید API توکن (sk_...) را وارد کنید."
        }

    disc = zernio_service.discover_account_and_profile(token)
    if not disc or not disc.get("account_id"):
        return {
            "success": False,
            "message": "هیچ اکانت متصلی برای این توکن در Zernio پیدا نشد. لطفاً مطمئن شوید پیج اینستاگرام در داشبورد Zernio متصل است."
        }

    setting.zernio_api_key = token
    setting.zernio_account_id = disc["account_id"]
    if disc.get("profile_id"):
        setting.zernio_profile_id = disc["profile_id"]
    if disc.get("username"):
        setting.instagram_username = disc["username"]

    db.commit()
    db.refresh(setting)

    from app.service.bot_settings import apply_credentials_to_services
    apply_credentials_to_services(setting)

    return {
        "success": True,
        "message": f"اکانت @{disc.get('username')} با موفقیت شناسایی و متصل شد! 🎉",
        "data": {
            "account_id": setting.zernio_account_id,
            "profile_id": setting.zernio_profile_id,
            "username": setting.instagram_username,
            "display_name": disc.get("display_name"),
            "platform": disc.get("platform")
        }
    }


@router.post("/test-connection", summary="بررسی وضعیت اتصال به اینستاگرام و Zernio")
def test_connection(db: Session = Depends(get_db)):
    """تست زنده توکن و شناسه‌ها جهت اطمینان از صحت ارتباط با اینستاگرام"""
    setting = get_bot_settings(db)

    # اگر شناسه‌ها موجود نبودند ولی توکن بود، کشف خودکار انجام بده
    if setting.zernio_api_key and (not setting.zernio_account_id or not setting.zernio_profile_id):
        disc = zernio_service.discover_account_and_profile(setting.zernio_api_key)
        if disc:
            setting.zernio_account_id = disc.get("account_id") or setting.zernio_account_id
            setting.zernio_profile_id = disc.get("profile_id") or setting.zernio_profile_id
            setting.instagram_username = disc.get("username") or setting.instagram_username
            db.commit()
            db.refresh(setting)
            from app.service.bot_settings import apply_credentials_to_services
            apply_credentials_to_services(setting)

    if not zernio_service.is_configured():
        return {
            "success": False,
            "message": "کلید API (توکن زرنیو) تنظیم نشده است. لطفاً توکن خود را در کادر بالا وارد کنید."
        }
    try:
        automations = zernio_service.list_comment_automations()
        return {
            "success": True,
            "message": "اتصال به اینستاگرام و Zernio با موفقیت برقرار است! ✅",
            "username": setting.instagram_username,
            "account_id": setting.zernio_account_id,
            "profile_id": setting.zernio_profile_id,
            "automations_count": len(automations)
        }
    except Exception as e:
        return {
            "success": False,
            "message": f"خطا در برقراری ارتباط: {str(e)}"
        }
