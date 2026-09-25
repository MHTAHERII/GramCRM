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

    def create_comment_automation(self, name: str, keywords: list[str], dm_message: str) -> dict | None:
        """
        ساخت اتوماسیون جدید کامنت به دایرکت:
        به محض اینکه کاربری در کامنت هر پستی یکی از کلیدواژه‌ها را بنویسد،
        Zernio به صورت خودکار پیام دایرکت را برای او ارسال می‌کند.
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
            "alsoMatchInDms": True  # پاسخ خودکار هم در کامنت و هم در دایرکت
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
        همگام‌سازی کامل کلیدواژه‌های دیتابیس لوکال با اتوماسیون‌های کامنت Zernio:
        تمام کلیدواژه‌های فعال به عنوان کامنت-به-دایرکت در Zernio ثبت/به‌روز می‌شوند.
        """
        if not self.is_configured():
            return {"success": False, "message": "Zernio تنظیم نشده است"}

        # ۱. دریافت اتوماسیون‌های فعلی در Zernio
        existing_automations = self.list_comment_automations()
        existing_by_name = {auto.get("name"): auto for auto in existing_automations}

        # ۲. خواندن کلیدواژه‌های فعال از دیتابیس
        active_keywords = db.query(Keyword).filter(Keyword.active == True).all()

        synced_count = 0
        for kw in active_keywords:
            auto_name = f"KW_{kw.id}_{kw.keyword}"
            # اگر قبلاً بوده، حذف و با مقدار جدید ایجاد کن (یا نگه دار)
            if auto_name in existing_by_name:
                self.delete_comment_automation(existing_by_name[auto_name]["id"])

            created = self.create_comment_automation(
                name=auto_name,
                keywords=[kw.keyword],
                dm_message=kw.response
            )
            if created:
                synced_count += 1

        logger.info(f"Successfully synced {synced_count} keywords to Zernio comment automations.")
        return {
            "success": True,
            "synced_count": synced_count,
            "total_active": len(active_keywords)
        }


zernio_service = ZernioService()
