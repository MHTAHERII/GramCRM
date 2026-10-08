import logging
from urllib.parse import quote
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from sqlalchemy.orm import Session
from app.config import settings
from app.models.keyword import Keyword
from app.service.product_response import keyword_response
from app.service.zernio_service import comment_keyword_variants, zernio_button_label

logger = logging.getLogger("postzen_service")

POSTZEN_BASE_URL = "https://api.postzen.dev/v1"


class PostZenService:
    def __init__(self):
        self.api_key = settings.POSTZEN_API_KEY
        self.account_id = settings.POSTZEN_ACCOUNT_ID
        self._session = None

    @property
    def session(self) -> requests.Session:
        if self._session is None:
            s = requests.Session()
            retries = Retry(
                total=3,
                backoff_factor=0.5,
                status_forcelist=[500, 502, 503, 504],
                raise_on_status=False
            )
            s.mount("https://", HTTPAdapter(max_retries=retries))
            if settings.IG_PROXY:
                s.proxies = {
                    "http": settings.IG_PROXY,
                    "https": settings.IG_PROXY
                }
            self._session = s
        return self._session

    @property
    def headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "User-Agent": "GramCRM/2.3.4"
        }

    def discover_account(self, api_key: str | None = None) -> str | None:
        """
        استعلام خودکار شناسه اکانت اینستاگرام متصل به کلید API پست‌زن
        """
        token = (api_key or self.api_key or "").strip()
        if not token:
            logger.warning("Cannot discover PostZen account: API key is missing.")
            return None

        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": "GramCRM/2.3.4"
        }

        try:
            url = f"{POSTZEN_BASE_URL}/accounts"
            res = self.session.get(url, headers=headers, timeout=12)
            if res.status_code != 200:
                logger.error(f"PostZen accounts discovery failed ({res.status_code}): {res.text}")
                return None

            data = res.json()
            accounts = data.get("accounts", [])
            if not accounts:
                logger.warning("No accounts found in PostZen for this API key.")
                return None

            for acc in accounts:
                if acc.get("platform") == "instagram" and acc.get("isActive", True):
                    acc_id = acc.get("_id") or acc.get("id")
                    self.account_id = acc_id
                    return acc_id

            first_acc = accounts[0]
            acc_id = first_acc.get("_id") or first_acc.get("id")
            self.account_id = acc_id
            return acc_id
        except Exception as e:
            logger.error(f"Error during PostZen account discovery: {e}", exc_info=True)
            return None

    def is_configured(self) -> bool:
        if bool(self.api_key and self.account_id):
            return True
        if self.api_key and not self.account_id:
            return bool(self.discover_account())
        return False

    def list_comment_automations(self) -> list[dict]:
        """دریافت تمام اتوماسیون‌های کامنت ثبت‌شده در PostZen"""
        if not self.is_configured():
            return []
        url = f"{POSTZEN_BASE_URL}/comment-automations"
        params = {"accountId": self.account_id} if self.account_id else {}
        res = self.session.get(url, headers=self.headers, params=params, timeout=12)
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
        automation_id: str | None = None,
        comment_reply_delay_seconds: int | None = None,
        dm_delay_seconds: int | None = None,
        comment_reply_variations: list[str] | None = None,
        dm_message_variations: list[str] | None = None,
        platform_post_id: str | None = None
    ) -> dict | None:
        """
        ساخت یا به‌روزرسانی اتوماسیون کامنت به دایرکت در PostZen
        """
        if not self.is_configured():
            logger.warning("PostZen is not configured.")
            return None

        public_reply = (comment_reply or "").strip()
        dm_msg = dm_message.strip()
        if len(dm_msg) > 640:
            logger.warning(f"dm_message exceeds 640 characters ({len(dm_msg)}); trimming to 640 for PostZen.")
            dm_msg = dm_msg[:640]
        if len(public_reply) > 640:
            logger.warning(f"comment_reply exceeds 640 characters ({len(public_reply)}); trimming to 640 for PostZen.")
            public_reply = public_reply[:640]

        payload = {
            "accountId": self.account_id,
            "name": name,
            "keywords": [kw.strip() for kw in keywords if kw.strip()],
            "matchMode": "contains" if public_reply else "exact",
            "dmMessage": dm_msg
        }


        if public_reply:
            payload["commentReply"] = public_reply
        elif automation_id:
            payload["commentReply"] = ""

        # تاخیر زمانی (Delays)
        if comment_reply_delay_seconds and comment_reply_delay_seconds > 0:
            payload["commentReplyDelaySeconds"] = int(comment_reply_delay_seconds)
        elif automation_id:
            payload["commentReplyDelaySeconds"] = 0

        if dm_delay_seconds and dm_delay_seconds > 0:
            payload["dmDelaySeconds"] = int(dm_delay_seconds)
        elif automation_id:
            payload["dmDelaySeconds"] = 0

        # تنوع متن ریپلای کامنت (Variations - حداکثر ۵)
        clean_cr_vars = [v.strip()[:640] for v in (comment_reply_variations or []) if v.strip()]
        if clean_cr_vars:
            payload["commentReplyVariations"] = clean_cr_vars[:5]
        elif automation_id:
            payload["commentReplyVariations"] = []

        # تنوع متن دایرکت (Variations - حداکثر ۵)
        clean_dm_vars = [v.strip()[:640] for v in (dm_message_variations or []) if v.strip()]
        if clean_dm_vars:
            payload["dmMessageVariations"] = clean_dm_vars[:5]
        elif automation_id:
            payload["dmMessageVariations"] = []

        # اتصال به پست خاص
        if platform_post_id and platform_post_id.strip():
            payload["platformPostId"] = platform_post_id.strip()
        elif automation_id:
            payload["platformPostId"] = None

        # دکمه‌ها
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

        # قفل فالو (Follow Gate)
        if follow_gate_message:
            payload["audience"] = {
                "followerStatus": "follower",
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
                "message": follow_gate_message.strip()[:640],
                "buttonLabel": btn_label,
                "notFollowingMessage": "هنوز پیج رو فالو نکردید! لطفاً ابتدا پیج را فالو کنید و سپس دکمه را لمس کنید 🌸"
            }
        elif automation_id:
            payload["audience"] = {"followerStatus": "any", "whenUnknown": "send"}
            payload["followGate"] = None

        try:
            if automation_id:
                url = f"{POSTZEN_BASE_URL}/comment-automations/{quote(str(automation_id), safe='')}"
                payload.pop("accountId", None)
                payload["isActive"] = True
                res = self.session.patch(url, headers=self.headers, json=payload, timeout=12)
            else:
                url = f"{POSTZEN_BASE_URL}/comment-automations"
                res = self.session.post(url, headers=self.headers, json=payload, timeout=12)

            if res.status_code in [200, 201]:
                logger.info(f"Comment automation '{name}' saved on PostZen successfully.")
                return res.json()
            logger.error(f"Failed to save PostZen comment automation ({res.status_code}): {res.text}")
            return None
        except Exception as e:
            logger.error(f"Error saving PostZen comment automation: {e}")
            return None

    def set_comment_automation_active(self, automation_id: str, active: bool) -> bool:
        """Pause or resume an automation in PostZen."""
        try:
            url = f"{POSTZEN_BASE_URL}/comment-automations/{quote(str(automation_id), safe='')}"
            res = self.session.patch(url, headers=self.headers, json={"isActive": active}, timeout=12)
            if res.status_code == 200:
                return True
            logger.error("Failed to change PostZen automation status (%s): %s", res.status_code, res.text)
        except requests.RequestException as e:
            logger.error("Failed to change PostZen automation status: %s", e)
        return False

    def delete_comment_automation(self, automation_id: str) -> bool:
        """حذف یک اتوماسیون از PostZen"""
        if not self.is_configured():
            return False
        try:
            url = f"{POSTZEN_BASE_URL}/comment-automations/{automation_id}"
            res = self.session.delete(url, headers=self.headers, timeout=12)
            return res.status_code == 200
        except Exception as e:
            logger.error(f"Error deleting PostZen automation {automation_id}: {e}")
            return False

    def sync_all_keywords(self, db: Session, force_recreate: bool = False) -> dict:
        """
        همگام‌سازی کامل کلیدواژه‌های دیتابیس با اتوماسیون‌های کامنت PostZen
        """
        if not self.is_configured():
            return {"success": False, "message": "PostZen تنظیم نشده است"}

        from app.models.bot_setting import BotSetting

        bot_settings = db.query(BotSetting).first()
        fg_msg = None
        fg_buttons = None
        if bot_settings and bot_settings.follow_gate_enabled:
            fg_msg = bot_settings.follow_gate_message or "این محتوا مخصوص دنبال‌کننده‌هاست 💙 پیج رو فالو کن و «فالو کردم» رو بزن."
            fg_buttons = bot_settings.follow_gate_buttons or []

        existing_automations = self.list_comment_automations()
        existing_by_name = {
            auto.get("name"): auto for auto in existing_automations
            if auto.get("accountId") is None
            or str(auto.get("accountId")) == str(self.account_id)
        }

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
            if force_recreate and existing_id:
                self.delete_comment_automation(existing_id)
                existing_id = None

            created = self.create_comment_automation(
                name=auto_name,
                keywords=comment_keyword_variants(kw.keyword) if kw.comment_reply else [kw.keyword],
                dm_message=keyword_response(kw),
                comment_reply=kw.comment_reply,
                buttons=kw.buttons,
                button_title=kw.button_title,
                button_url=kw.button_url,
                follow_gate_message=fg_msg,
                follow_gate_buttons=fg_buttons,
                automation_id=existing_id,
                comment_reply_delay_seconds=kw.comment_reply_delay_seconds,
                dm_delay_seconds=kw.dm_delay_seconds,
                comment_reply_variations=kw.comment_reply_variations,
                dm_message_variations=kw.dm_message_variations,
                platform_post_id=kw.platform_post_id,
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

        logger.info(f"Successfully synced {synced_count} keywords with buttons & follow gate to PostZen.")
        return {
            "success": True,
            "synced_count": synced_count,
            "total_active": len(active_keywords),
            "provider": "postzen"
        }


postzen_service = PostZenService()
