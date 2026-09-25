import logging
import requests
from sqlalchemy.orm import Session
from app.config import settings
from app.models.keyword import Keyword

logger = logging.getLogger("zernio_service")

ZERNIO_BASE_URL = "https://zernio.com/api/v1"


class ZernioService:
    def __init__(self):
        self.api_key = settings.ZERNIO_API_KEY
        self.profile_id = settings.ZERNIO_PROFILE_ID
        self.account_id = settings.ZERNIO_ACCOUNT_ID

    @property
    def headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }

    def is_configured(self) -> bool:
        return bool(self.api_key and self.profile_id and self.account_id)

    def list_comment_automations(self) -> list[dict]:
        """دریافت تمام اتوماسیون‌های کامنت به دایرکت ثبت‌شده در Zernio"""
        if not self.is_configured():
            return []
        try:
            url = f"{ZERNIO_BASE_URL}/comment-automations"
            res = requests.get(url, headers=self.headers, params={"profileId": self.profile_id}, timeout=10)
            if res.status_code == 200:
                return res.json().get("automations", [])
            logger.error(f"Zernio list automations failed ({res.status_code}): {res.text}")
            return []
        except Exception as e:
            logger.error(f"Error calling Zernio list_comment_automations: {e}")
            return []

    def create_comment_automation(
        self,
        name: str,
        keywords: list[str],
        dm_message: str,
        buttons: list[dict] | None = None,
        button_title: str | None = None,
        button_url: str | None = None,
        follow_gate_message: str | None = None
    ) -> dict | None:
        """
        ساخت اتوماسیون جدید کامنت به دایرکت:
        - اگر follow_gate_message ست باشد: اینستاگرام پیام قفل فالو با دو دکمه تعاملی می‌فرستد.
        - اگر buttons یا button_title/button_url ست باشد: پیام نهایی همراه با دکمه‌های لینک‌دار شکیل (تا ۳ دکمه) ارسال می‌شود.
        """
        if not self.is_configured():
            logger.warning("Zernio is not configured.")
            return None

        payload = {
            "profileId": self.profile_id,
            "accountId": self.account_id,
            "name": name,
            "keywords": [kw.strip() for kw in keywords if kw.strip()],
            "dmMessage": dm_message.strip(),
            "alsoMatchInDms": True
        }

        # افزودن دکمه‌های لینک‌دار تعاملی (حداکثر ۳ دکمه طبق استاندارد اینستاگرام)
        formatted_buttons = []
        if buttons:
            for b in buttons[:3]:
                if isinstance(b, dict):
                    t = b.get("title", "").strip()
                    u = b.get("url", "").strip()
                else:
                    t = getattr(b, "title", "").strip()
                    u = getattr(b, "url", "").strip()
                if t and u:
                    formatted_buttons.append({"type": "url", "title": t, "url": u})
        elif button_title and button_url:
            formatted_buttons.append({"type": "url", "title": button_title.strip(), "url": button_url.strip()})

        if formatted_buttons:
            payload["buttons"] = formatted_buttons

        # افزودن قفل فالو با دو دکمه «فالو کردم» و «مشاهده پیج»
        if follow_gate_message:
            payload["followGate"] = {
                "message": follow_gate_message.strip()
            }

        try:
            url = f"{ZERNIO_BASE_URL}/comment-automations"
            res = requests.post(url, headers=self.headers, json=payload, timeout=10)
            if res.status_code in [200, 201]:
                logger.info(f"Comment automation '{name}' created on Zernio successfully.")
                return res.json()
            logger.error(f"Failed to create Zernio comment automation ({res.status_code}): {res.text}")
            return None
        except Exception as e:
            logger.error(f"Error creating Zernio comment automation: {e}")
            return None

    def delete_comment_automation(self, automation_id: str) -> bool:
        """حذف یک اتوماسیون از Zernio"""
        if not self.is_configured():
            return False
        try:
            url = f"{ZERNIO_BASE_URL}/comment-automations/{automation_id}"
            res = requests.delete(url, headers=self.headers, timeout=10)
            return res.status_code == 200
        except Exception as e:
            logger.error(f"Error deleting Zernio automation {automation_id}: {e}")
            return False

    def sync_all_keywords(self, db: Session) -> dict:
        """
        همگام‌سازی کامل کلیدواژه‌های دیتابیس با اتوماسیون‌های کامنت Zernio
        شامل دکمه‌های لینک‌دار و قفل فالو دو دکمه‌ای
        """
        if not self.is_configured():
            return {"success": False, "message": "Zernio تنظیم نشده است"}

        from app.models.bot_setting import BotSetting

        # ۱. استعلام تنظیمات دروازه فالو
        bot_settings = db.query(BotSetting).first()
        fg_msg = None
        if bot_settings and bot_settings.follow_gate_enabled:
            fg_msg = bot_settings.follow_gate_message or "این محتوا مخصوص دنبال‌کننده‌هاست 💙 پیج رو فالو کن و «فالو کردم» رو بزن."

        # ۲. دریافت اتوماسیون‌های فعلی در Zernio
        existing_automations = self.list_comment_automations()
        existing_by_name = {auto.get("name"): auto for auto in existing_automations}

        # ۳. خواندن کلیدواژه‌های فعال از دیتابیس
        active_keywords = db.query(Keyword).filter(Keyword.active == True).all()

        synced_count = 0
        for kw in active_keywords:
            auto_name = f"KW_{kw.id}_{kw.keyword}"
            # اگر قبلاً بوده، حذف کن تا با کانفیگ جدید ایجاد شود
            if auto_name in existing_by_name:
                self.delete_comment_automation(existing_by_name[auto_name]["id"])

            created = self.create_comment_automation(
                name=auto_name,
                keywords=[kw.keyword],
                dm_message=kw.response,
                buttons=kw.buttons,
                button_title=kw.button_title,
                button_url=kw.button_url,
                follow_gate_message=fg_msg
            )
            if created:
                synced_count += 1

        logger.info(f"Successfully synced {synced_count} keywords with buttons & follow gate to Zernio.")
        return {
            "success": True,
            "synced_count": synced_count,
            "total_active": len(active_keywords)
        }


zernio_service = ZernioService()
