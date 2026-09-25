import logging
from datetime import datetime
from sqlalchemy.orm import Session
from app.models.customer import Customer
from app.models.message import Message
from app.service.reply_engine import find_keyword_response, normalize_text
from app.service.bot_settings import (
    get_bot_settings,
    REMINDER_NOT_FOLLOWED,
    FOLLOW_GATE_REPEAT_COOLDOWN,
)

logger = logging.getLogger(__name__)


def _claims_followed(text: str) -> bool:
    """تشخیص اینکه پیام کاربر اعلام فالو کردن است (مثل: فالو کردم / فالو شدم)"""
    norm = normalize_text(text)
    return "فالو" in norm and ("کردم" in norm or "شدم" in norm)


def process_incoming_message(
    db: Session,
    instagram_user_id: str,
    text: str,
    username: str | None = None,
    full_name: str | None = None,
    ig_message_id: str | None = None,
    is_new: bool = True
) -> str | None:
    """
    پایپ‌لاین کامل مدیریت پیام دایرکت:
    ۱. جلوگیری از پاسخ تکراری
    ۲. جستجو یا ثبت رکورد مشتری
    ۳. ذخیره پیام دریافتی مشتری (همه پیام‌ها، حتی قدیمی، برای نمایش در پنل)
    ۴. پیام قدیمی (قبل از استارت ربات) یا ربات خاموش → بدون پاسخ خودکار
    ۵. دروازه فالو (در صورت فعال بودن): غیرفالوکننده فقط پیام فالو می‌گیرد
    ۶. استخراج پاسخ از موتور کلیدواژه‌ها
    ۷. ذخیره پیام ارسالی ربات در دیتابیس و بازگرداندن متن پاسخ
    """
    if not text or not text.strip():
        return None

    # ۱. جلوگیری از پردازش پیام تکراری
    if ig_message_id:
        existing_msg = (
            db.query(Message)
            .filter(Message.instagram_message_id == str(ig_message_id))
            .first()
        )
        if existing_msg:
            logger.info(f"پیام با شناسه {ig_message_id} قبلاً پردازش شده است. نادیده گرفته شد.")
            return None

    # ۲. ثبت یا به‌روزرسانی مشتری
    customer = (
        db.query(Customer)
        .filter(Customer.instagram_id == str(instagram_user_id))
        .first()
    )

    if not customer:
        customer = Customer(
            instagram_id=str(instagram_user_id),
            username=username,
            name=full_name
        )
        db.add(customer)
        db.commit()
        db.refresh(customer)
        logger.info(f"مشتری جدید ثبت شد: ID={customer.id} | Instagram ID={customer.instagram_id}")
    else:
        # به‌روزرسانی نام یا یوزرنیم در صورت تغییر
        updated = False
        if username and customer.username != username:
            customer.username = username
            updated = True
        if full_name and customer.name != full_name:
            customer.name = full_name
            updated = True
        if updated:
            db.commit()
            db.refresh(customer)

    # ۳. ذخیره پیام ورودی مشتری
    inbound_message = Message(
        customer_id=customer.id,
        text=text.strip(),
        sender="customer",
        instagram_message_id=str(ig_message_id) if ig_message_id else None
    )
    db.add(inbound_message)
    db.commit()
    db.refresh(inbound_message)

    # ۴. پیام قدیمی (قبل از استارت ربات) فقط در سوابق می‌ماند تا جواب دیرهنگام و بی‌دلیل ارسال نشود
    if not is_new:
        logger.info(f"پیام قدیمی مشتری {customer.id} فقط ذخیره شد؛ پاسخ خودکار ارسال نشد.")
        return None

    # ۵. اگر ربات خاموش باشد پیام فقط ذخیره می‌شود تا ادمین دستی پاسخ دهد
    bot_settings = get_bot_settings(db)
    if not bot_settings.bot_enabled:
        logger.info(f"ربات خاموش است؛ پیام مشتری {customer.id} بدون پاسخ خودکار ذخیره شد.")
        return None

    # ۶. دروازه فالو: کسی که پیج را فالو نکرده، به‌جای پاسخ، پیام فالو می‌گیرد
    if bot_settings.follow_gate_enabled:
        from app.service.instagram_service import instagram_client

        if not instagram_client.follows_page(customer.instagram_id):
            last_gate = (
                db.query(Message)
                .filter(
                    Message.customer_id == customer.id,
                    Message.sender == "bot",
                    Message.text == bot_settings.follow_gate_message,
                )
                .order_by(Message.id.desc())
                .first()
            )
            recently_gated = (
                last_gate is not None
                and (datetime.utcnow() - last_gate.created_at) < FOLLOW_GATE_REPEAT_COOLDOWN
            )

            if recently_gated:
                if _claims_followed(text):
                    # ادعای فالو کرده ولی هنوز فالو نشده؛ فقط یک بار یادآوری می‌کنیم
                    last_bot = (
                        db.query(Message)
                        .filter(Message.customer_id == customer.id, Message.sender == "bot")
                        .order_by(Message.id.desc())
                        .first()
                    )
                    if not last_bot or last_bot.text != REMINDER_NOT_FOLLOWED:
                        db.add(Message(customer_id=customer.id, text=REMINDER_NOT_FOLLOWED, sender="bot"))
                        db.commit()
                        return REMINDER_NOT_FOLLOWED
                # پیام فالو همین تازگی رفته؛ تکرار نمی‌کنیم تا اسپم نشود
                logger.info(f"مشتری {customer.id} هنوز فالو نکرده و پیام فالو تازه رسیده؛ ساکت ماندیم.")
                return None

            # پیام فالو نگرفته یا کول‌داون گذشته → دوباره می‌فرستیم
            gate_text = bot_settings.follow_gate_message
            db.add(Message(customer_id=customer.id, text=gate_text, sender="bot"))
            db.commit()
            logger.info(f"دروازه فالو: مشتری {customer.id} فالو نبود؛ پیام فالو ارسال شد.")
            return gate_text

        # فالو شده و اعلام «فالو کردم» زده → پیام قبلی‌اش (اولین پیام غیر-اعلامی) را دوباره پردازش کن
        if _claims_followed(text):
            recent = (
                db.query(Message)
                .filter(
                    Message.customer_id == customer.id,
                    Message.sender == "customer",
                    Message.id != inbound_message.id,
                )
                .order_by(Message.id.desc())
                .limit(5)
                .all()
            )
            previous = next((m for m in recent if not _claims_followed(m.text)), None)
            if previous and previous.text:
                logger.info(f"مشتری {customer.id} فالو کرد؛ پردازش مجدد پیام قبلی: '{previous.text[:30]}...'")
                text = previous.text

    # ۷. استخراج پاسخ از موتور کلیدواژه‌ها
    reply_text = find_keyword_response(text, db, fallback=True)
    if not reply_text:
        return None

    # ۸. ذخیره پیام خروجی ربات
    outbound_message = Message(
        customer_id=customer.id,
        text=reply_text,
        sender="bot"
    )
    db.add(outbound_message)
    db.commit()
    db.refresh(outbound_message)

    logger.info(f"پاسخ تولید شد برای مشتری {customer.id}: '{reply_text[:30]}...'")
    return reply_text