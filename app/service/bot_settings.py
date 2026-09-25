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
        )
        db.add(setting)
        db.commit()
        db.refresh(setting)
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
    if changed:
        db.commit()
        db.refresh(setting)
    return setting
