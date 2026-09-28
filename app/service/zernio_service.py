import logging
import requests
from urllib.parse import quote
from sqlalchemy.orm import Session
from app.config import settings
from app.models.keyword import Keyword

logger = logging.getLogger("zernio_service")

ZERNIO_BASE_URL = "https://zernio.com/api/v1"
MAX_BUTTON_LABEL_LENGTH = 20


def zernio_button_label(title: str) -> str:
    """Keep already-saved labels usable with Zernio's 20-character limit."""
    label = title.strip()
    if len(label) > MAX_BUTTON_LABEL_LENGTH:
        logger.warning("Zernio button label exceeds 20 characters; shortening it for delivery")
    return label[:MAX_BUTTON_LABEL_LENGTH]


def comment_keyword_variants(keyword: str) -> list[str]:
    """پشتیبانی از شکل انگلیسی، فارسی و عربی رقم‌ها در کامنت."""
    ascii_digits = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
    canonical = keyword.translate(ascii_digits)
    variants = [keyword, canonical, canonical.translate(str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")),
                canonical.translate(str.maketrans("0123456789", "٠١٢٣٤٥٦٧٨٩"))]
    return list(dict.fromkeys(variants))


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

    def discover_account_and_profile(self, api_key: str | None = None) -> dict | None:
        """
        استعلام خودکار شناسه اکانت و پروفایل متصل به کلید API زرنیو
        """
        token = (api_key or self.api_key or "").strip()
        if not token:
            logger.warning("Cannot discover account: Zernio API key is missing.")
            return None

        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }

        try:
            url = f"{ZERNIO_BASE_URL}/accounts"
            res = requests.get(url, headers=headers, timeout=12)
            if res.status_code != 200:
                logger.error(f"Zernio accounts discovery failed ({res.status_code}): {res.text}")
                return None

            data = res.json()
            accounts = data.get("accounts", [])
            if not accounts:
                logger.warning("No accounts found in Zernio for this API key.")
                return None

            # اولویت ۱: اکانت فعال اینستاگرام
            ig_account = None
            for acc in accounts:
                if acc.get("platform") == "instagram" and acc.get("enabled", True) and acc.get("isActive", True):
                    ig_account = acc
                    break

            # اولویت ۲: هر اکانت اینستاگرام
            if not ig_account:
                for acc in accounts:
                    if acc.get("platform") == "instagram":
                        ig_account = acc
                        break

            # اولویت ۳: اولین اکانت موجود
            if not ig_account:
                ig_account = accounts[0]

            account_id = ig_account.get("_id") or ig_account.get("id")

            # استخراج profile_id از آبجکت اکانت
            profile_id = None
            pid_obj = ig_account.get("profileId")
            if isinstance(pid_obj, dict):
                profile_id = pid_obj.get("_id") or pid_obj.get("id")
            elif isinstance(pid_obj, str):
                profile_id = pid_obj

            # فالبک: در صورت نبود، استعلام مستقیم از /profiles
            if not profile_id:
                try:
                    p_res = requests.get(f"{ZERNIO_BASE_URL}/profiles", headers=headers, timeout=10)
                    if p_res.status_code == 200:
                        profiles = p_res.json().get("profiles", [])
                        if profiles:
                            profile_id = profiles[0].get("_id") or profiles[0].get("id")
                except Exception as pe:
                    logger.warning(f"Failed to fetch fallback profiles from Zernio: {pe}")

            username = ig_account.get("username")
            display_name = ig_account.get("displayName")
            platform = ig_account.get("platform", "instagram")

            return {
                "account_id": str(account_id) if account_id else None,
                "profile_id": str(profile_id) if profile_id else None,
                "username": username,
                "display_name": display_name,
                "platform": platform,
                "total_accounts": len(accounts),
                "all_accounts": [
                    {
                        "account_id": a.get("_id") or a.get("id"),
                        "username": a.get("username"),
                        "displayName": a.get("displayName"),
                        "platform": a.get("platform")
                    }
                    for a in accounts
                ]
            }
        except Exception as e:
            logger.error(f"Error during Zernio account discovery: {e}", exc_info=True)
            return None

    def ensure_configured(self) -> bool:
        """
        اطمینان از وجود شناسه‌ها؛ در صورت داشتن توکن اما نبود شناسه‌ها، آن‌ها را خودکار دریافت می‌کند.
        """
        if bool(self.api_key and self.profile_id and self.account_id):
            return True
        if self.api_key and (not self.profile_id or not self.account_id):
            discovered = self.discover_account_and_profile(self.api_key)
            if discovered:
                if not self.account_id and discovered.get("account_id"):
                    self.account_id = discovered["account_id"]
                if not self.profile_id and discovered.get("profile_id"):
                    self.profile_id = discovered["profile_id"]
                logger.info(f"Auto-configured Zernio credentials: account_id={self.account_id}, profile_id={self.profile_id}")
                return bool(self.api_key and self.profile_id and self.account_id)
        return False

    def is_configured(self) -> bool:
        if bool(self.api_key and self.profile_id and self.account_id):
            return True
        if self.api_key and (not self.profile_id or not self.account_id):
            return self.ensure_configured()
        return False

    def list_comment_automations(self) -> list[dict]:
        """دریافت تمام اتوماسیون‌های کامنت به دایرکت ثبت‌شده در Zernio"""
        if not self.is_configured():
            return []
        url = f"{ZERNIO_BASE_URL}/comment-automations"
        res = requests.get(url, headers=self.headers, params={"profileId": self.profile_id}, timeout=10)
        res.raise_for_status()
        return res.json().get("automations", [])

    def create_comment_automation(
        self,
        name: str,
        keywords: list[str],
        dm_message: str,
        buttons: list[dict] | None = None,
        button_title: str | None = None,
        button_url: str | None = None,
        follow_gate_message: str | None = None,
        follow_gate_buttons: list[dict] | None = None,
        comment_reply: str | None = None,
        automation_id: str | None = None
    ) -> dict | None:
        """
        ساخت اتوماسیون جدید کامنت به دایرکت:
        - اگر follow_gate_message ست باشد: اینستاگرام پیام قفل فالو با دو دکمه تعاملی می‌فرستد.
        - اگر buttons یا button_title/button_url ست باشد: پیام نهایی همراه با دکمه‌های لینک‌دار شکیل (تا ۳ دکمه) ارسال می‌شود.
        """
        if not self.is_configured():
            logger.warning("Zernio is not configured.")
            return None

        public_reply = (comment_reply or "").strip()
        payload = {
            "profileId": self.profile_id,
            "accountId": self.account_id,
            "name": name,
            "keywords": [kw.strip() for kw in keywords if kw.strip()],
            "matchMode": "contains" if public_reply else "exact",
            "dmMessage": dm_message.strip(),
            # تطابق جزئی مخصوص کامنت است؛ تطابق دایرکت در موتور داخلی دقیق می‌ماند.
            "alsoMatchInDms": not bool(public_reply)
        }

        if public_reply:
            payload["commentReply"] = public_reply
        elif automation_id:
            payload["commentReply"] = ""

        # افزودن دکمه‌های لینک‌دار یا تعاملی (حداکثر ۳ دکمه طبق استاندارد اینستاگرام)
        formatted_buttons = []
        if buttons:
            for b in buttons[:3]:
                if isinstance(b, dict):
                    b_type = b.get("type", "url")
                    t = b.get("title", "").strip()
                    u = b.get("url", "").strip()
                else:
                    b_type = getattr(b, "type", "url")
                    t = getattr(b, "title", "").strip()
                    u = getattr(b, "url", "").strip()
                if not t:
                    continue
                if b_type == "postback" or "ig.me/m/" in u:
                    formatted_buttons.append({"type": "postback", "title": zernio_button_label(t), "payload": t})
                elif u:
                    formatted_buttons.append({"type": "url", "title": zernio_button_label(t), "url": u})
        elif button_title and button_url:
            if "ig.me/m/" in button_url:
                formatted_buttons.append({"type": "postback", "title": zernio_button_label(button_title), "payload": button_title.strip()})
            else:
                formatted_buttons.append({"type": "url", "title": zernio_button_label(button_title), "url": button_url.strip()})

        if formatted_buttons:
            payload["buttons"] = formatted_buttons
        elif automation_id:
            payload["buttons"] = []

        # افزودن قفل فالو طبق استاندارد رسمی Zernio
        if follow_gate_message:
            payload["audience"] = {
                "followerStatus": "any",
                "whenUnknown": "verify"
            }
            btn_label = "فالو کردم ✅"
            if follow_gate_buttons:
                for b in follow_gate_buttons:
                    t = b.get("title", "").strip() if isinstance(b, dict) else getattr(b, "title", "").strip()
                    if t:
                        btn_label = zernio_button_label(t)
                        break

            payload["followGate"] = {
                "message": follow_gate_message.strip(),
                "buttonLabel": btn_label,
                "notFollowingMessage": "هنوز پیج رو فالو نکردید! لطفاً ابتدا پیج را فالو کنید و سپس دکمه را لمس کنید 🌸"
            }
        elif automation_id:
            payload["audience"] = {"followerStatus": "any", "whenUnknown": "send"}

        try:
            if automation_id:
                url = f"{ZERNIO_BASE_URL}/comment-automations/{quote(str(automation_id), safe='')}"
                payload.pop("profileId")
                payload.pop("accountId")
                payload["isActive"] = True
                res = requests.patch(url, headers=self.headers, json=payload, timeout=10)
            else:
                url = f"{ZERNIO_BASE_URL}/comment-automations"
                res = requests.post(url, headers=self.headers, json=payload, timeout=10)
            if res.status_code in [200, 201]:
                logger.info(f"Comment automation '{name}' saved on Zernio successfully.")
                return res.json()
            logger.error(f"Failed to save Zernio comment automation ({res.status_code}): {res.text}")
            return None
        except Exception as e:
            logger.error(f"Error saving Zernio comment automation: {e}")
            return None

    def set_comment_automation_active(self, automation_id: str, active: bool) -> bool:
        """Pause or resume a managed rule without deleting its delivery history."""
        try:
            url = f"{ZERNIO_BASE_URL}/comment-automations/{quote(str(automation_id), safe='')}"
            res = requests.patch(url, headers=self.headers, json={"isActive": active}, timeout=10)
            if res.status_code == 200:
                return True
            logger.error("Failed to change automation active status (%s): %s", res.status_code, res.text)
        except requests.RequestException as e:
            logger.error("Failed to change automation active status: %s", e)
        return False

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
        fg_buttons = None
        if bot_settings and bot_settings.follow_gate_enabled:
            fg_msg = bot_settings.follow_gate_message or "این محتوا مخصوص دنبال‌کننده‌هاست 💙 پیج رو فالو کن و «فالو کردم» رو بزن."
            fg_buttons = bot_settings.follow_gate_buttons or []

        # ۲. دریافت اتوماسیون‌های فعلی در Zernio
        existing_automations = self.list_comment_automations()
        existing_by_name = {
            auto.get("name"): auto for auto in existing_automations
            if auto.get("accountId") in (None, self.account_id)
        }

        # ۳. خواندن کلیدواژه‌های فعال از دیتابیس
        all_keywords = db.query(Keyword).all()
        active_keywords = [kw for kw in all_keywords if kw.active]

        import time
        synced_count = 0
        for kw in active_keywords:
            auto_name = f"KW_{kw.id}_{kw.keyword}"
            existing = existing_by_name.get(auto_name) or next(
                (auto for name, auto in existing_by_name.items()
                 if isinstance(name, str) and name.startswith(f"KW_{kw.id}_")), None
            )
            existing_id = (existing.get("id") or existing.get("_id")) if existing else None
            if existing and not existing_id:
                logger.warning("Automation %s has no id; skipping to avoid a duplicate", auto_name)
                continue

            created = self.create_comment_automation(
                name=auto_name,
                keywords=comment_keyword_variants(kw.keyword) if kw.comment_reply else [kw.keyword],
                dm_message=kw.response,
                comment_reply=kw.comment_reply,
                buttons=kw.buttons,
                button_title=kw.button_title,
                button_url=kw.button_url,
                follow_gate_message=fg_msg,
                follow_gate_buttons=fg_buttons,
                automation_id=existing_id
            )
            if created:
                synced_count += 1
            time.sleep(0.3)

        for kw in all_keywords:
            if kw.active:
                continue
            existing = existing_by_name.get(f"KW_{kw.id}_{kw.keyword}") or next(
                (auto for name, auto in existing_by_name.items()
                 if isinstance(name, str) and name.startswith(f"KW_{kw.id}_")), None
            )
            if existing and existing.get("isActive", True):
                existing_id = existing.get("id") or existing.get("_id")
                if existing_id:
                    self.set_comment_automation_active(existing_id, False)

        # A deleted local rule must stop firing remotely, while its logs remain available.
        local_ids = {kw.id for kw in all_keywords}
        for name, auto in existing_by_name.items():
            if not isinstance(name, str) or not name.startswith("KW_"):
                continue
            parts = name.split("_", 2)
            if len(parts) != 3 or not parts[1].isdigit() or int(parts[1]) in local_ids:
                continue
            auto_id = auto.get("id") or auto.get("_id")
            if auto_id and auto.get("isActive", True):
                self.set_comment_automation_active(auto_id, False)

        logger.info(f"Successfully synced {synced_count} keywords with buttons & follow gate to Zernio.")
        return {
            "success": True,
            "synced_count": synced_count,
            "total_active": len(active_keywords)
        }


zernio_service = ZernioService()
