from sqlalchemy.orm import Session
from datetime import timedelta
from app.models.bot_setting import BotSetting

# حداکثر فاصله تکرار پیام دروازه فالو برای یک مشتری
FOLLOW_GATE_REPEAT_COOLDOWN = timedelta(minutes=15)

# متن اولیه برای ساخت رکورد تنظیمات؛ از پنل قابل ویرایش است
DEFAULT_FALLBACK_REPLY = (
    "سلام و درود! پیام شما دریافت شد. همکاران ما در اسرع وقت پاسخگوی شما خواهند بود. "
    "در صورت تمایل می‌توانید نام اسانس یا عطر مد نظرتان را ارسال کنید."
)

# متن اولیه دروازه فالو؛ از پنل قابل ویرایش است
DEFAULT_FOLLOW_GATE_MESSAGE = (
    "سلام! برای ادامه و دریافت پاسخ، لطفاً ابتدا پیج ما را فالو کنید 🙏 "
    "بعد از فالو کردن، همین‌جا بنویس: فالو کردم"
)

# یادآوری وقتی کاربر ادعای فالو کرده ولی هنوز فالو نشده است
REMINDER_NOT_FOLLOWED = (
    "هنوز فالو شدن پیج رو دریافت نکردیم 🙏 لطفاً دوباره چک کن و بعدش پیامت رو بفرست."
)


def apply_credentials_to_services(setting: BotSetting):
    """به‌روزرسانی کلیدها و شناسه‌های Zernio در سرویس‌های زنده برنامه"""
    try:
        from app.service.zernio_service import zernio_service
        from app.service.instagram_service import instagram_client
        from app.config import settings

        api_key = setting.zernio_api_key or settings.ZERNIO_API_KEY
        profile_id = setting.zernio_profile_id or settings.ZERNIO_PROFILE_ID
        account_id = setting.zernio_account_id or settings.ZERNIO_ACCOUNT_ID

        if api_key:
            zernio_service.api_key = api_key
            instagram_client.api_key = api_key
        if profile_id:
            zernio_service.profile_id = profile_id
        if account_id:
            zernio_service.account_id = account_id
            instagram_client.account_id = account_id

        # در صورت داشتن توکن اما نبود شناسه‌ها، اتصال خودکار را امتحان کن
        if api_key and (not profile_id or not account_id):
            zernio_service.ensure_configured()
            instagram_client.ensure_authenticated()
    except Exception as e:
        import logging
        logging.getLogger("bot_settings").error(f"Error applying credentials to services: {e}")


def get_bot_settings(db: Session) -> BotSetting:
    """بازگرداندن رکورد تنظیمات؛ در اولین اجرا رکورد پیش‌فرض ساخته می‌شود."""
    setting = db.query(BotSetting).filter(BotSetting.id == 1).first()
    if not setting:
        setting = BotSetting(
            id=1,
            bot_enabled=True,
            fallback_message=DEFAULT_FALLBACK_REPLY,
            follow_gate_enabled=False,
            follow_gate_message=DEFAULT_FOLLOW_GATE_MESSAGE,
            admin_username="admin"
        )
        db.add(setting)
        db.commit()
        db.refresh(setting)
        apply_credentials_to_services(setting)
        return setting

    # رکوردهای ساخته‌شده قبل از اضافه شدن فیلدها ممکن است NULL باشند
    changed = False
    if setting.follow_gate_message is None:
        setting.follow_gate_message = DEFAULT_FOLLOW_GATE_MESSAGE
        changed = True
    if setting.follow_gate_enabled is None:
        setting.follow_gate_enabled = False
        changed = True
    if getattr(setting, "comment_reply_enabled", None) is None:
        setting.comment_reply_enabled = True
        changed = True
    if getattr(setting, "comment_public_reply_enabled", None) is None:
        setting.comment_public_reply_enabled = False
        changed = True
    if getattr(setting, "comment_public_reply_text", None) is None:
        setting.comment_public_reply_text = "پاسخ براتون دایرکت شد 🌸"
        changed = True
    if getattr(setting, "admin_username", None) is None:
        setting.admin_username = "admin"
        changed = True

    # بازیابی خودکار از فایل .env در صورت خالی بودن مقادیر در دیتابیس
    from app.config import settings as env_settings
    if not setting.zernio_api_key and env_settings.ZERNIO_API_KEY:
        setting.zernio_api_key = env_settings.ZERNIO_API_KEY
        changed = True
    if not setting.zernio_profile_id and env_settings.ZERNIO_PROFILE_ID:
        setting.zernio_profile_id = env_settings.ZERNIO_PROFILE_ID
        changed = True
    if not setting.zernio_account_id and env_settings.ZERNIO_ACCOUNT_ID:
        setting.zernio_account_id = env_settings.ZERNIO_ACCOUNT_ID
        changed = True

    # اگر توکن موجود است ولی شناسه‌ها یا نام کاربری اینستاگرام ثبت نشده، استعلام و کشف خودکار کن
    if setting.zernio_api_key and (not setting.zernio_account_id or not setting.zernio_profile_id or not setting.instagram_username):
        try:
            from app.service.zernio_service import zernio_service
            disc = zernio_service.discover_account_and_profile(setting.zernio_api_key)
            if disc:
                if not setting.zernio_account_id and disc.get("account_id"):
                    setting.zernio_account_id = disc["account_id"]
                    changed = True
                if not setting.zernio_profile_id and disc.get("profile_id"):
                    setting.zernio_profile_id = disc["profile_id"]
                    changed = True
                if not setting.instagram_username and disc.get("username"):
                    setting.instagram_username = disc["username"]
                    changed = True
        except Exception as ex:
            import logging
            logging.getLogger("bot_settings").warning(f"Could not auto-discover Zernio details on get_bot_settings: {ex}")

    if changed:
        db.commit()
        db.refresh(setting)

    apply_credentials_to_services(setting)
    return setting

