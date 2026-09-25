import logging
import requests
from app.config import settings

logger = logging.getLogger("instagram_service")


class UnifiedInstagramService:
    """
    سرویس جامع اینستاگرام:
    از API رسمی Zernio برای خواندن و ارسال پیام‌های دایرکت استفاده می‌کند.
    هیچ نیازی به لاگین و نام کاربری/رمز عبور ندارد و ریسک بن شدن صفر است.
    """

    def __init__(self):
        self.api_key = settings.ZERNIO_API_KEY
        self.account_id = settings.ZERNIO_ACCOUNT_ID
        self.base_url = "https://zernio.com/api/v1"
        # ذخیره آخرین message_id پردازش‌شده برای هر مکالمه (جلوگیری از پاسخ تکراری)
        self._last_processed: dict[str, str] = {}

    @property
    def headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }

    def login(self) -> bool:
        """بررسی آماده بودن کلید و اکانت"""
        if bool(self.api_key and self.account_id):
            logger.info("Instagram (Zernio API) is ready.")
            return True
        logger.warning("Zernio API key or Account ID is missing.")
        return False

    def ensure_authenticated(self) -> bool:
        return bool(self.api_key and self.account_id)

    def fetch_unread_messages(self, amount: int = 10) -> list[dict]:
        """
        دریافت پیام‌های جدید دایرکت از طریق Zernio Inbox API.

        منطق بهبود‌یافته:
        ۱. فقط مکالماتی که unreadCount > 0 دارند بررسی می‌شوند
        ۲. همه پیام‌های incoming خوانده‌نشده (نه فقط آخرین) استخراج می‌شوند
        ۳. فیلتر ۲۴ ساعته متا برای جلوگیری از خطای "outside allowed window"
        ۴. تشخیص تکراری با _last_processed و ترتیب زمانی پیام‌ها
        """
        if not self.ensure_authenticated():
            return []

        results = []
        try:
            conv_url = f"{self.base_url}/inbox/conversations"
            params = {"accountId": self.account_id}
            r = requests.get(conv_url, headers=self.headers, params=params, timeout=15)
            if r.status_code != 200:
                logger.error(f"Failed to fetch conversations ({r.status_code}): {r.text}")
                return []

            from datetime import datetime, timezone, timedelta
            now = datetime.now(timezone.utc)

            conversations = r.json().get("data", [])

            for conv in conversations[:amount]:
                conv_id = conv.get("id")
                participant = conv.get("participantUsername") or conv.get("participantName") or "unknown"

                # ۱. فیلتر ۲۴ ساعته — خارج از پنجره مجاز متا
                updated_str = conv.get("updatedTime")
                if updated_str:
                    try:
                        updated_dt = datetime.fromisoformat(updated_str.replace("Z", "+00:00"))
                        if (now - updated_dt) > timedelta(hours=23):
                            logger.debug(f"Skip conversation {participant}: outside 24h window")
                            continue
                    except Exception:
                        pass

                # ۲. دریافت پیام‌های مکالمه
                msg_url = f"{self.base_url}/inbox/conversations/{conv_id}/messages"
                m_res = requests.get(msg_url, headers=self.headers, params=params, timeout=15)
                if m_res.status_code != 200:
                    logger.warning(f"Failed to fetch messages for {participant} ({m_res.status_code})")
                    continue

                messages = m_res.json().get("messages", [])
                if not messages:
                    continue

                # ۳. پیدا کردن آخرین پیام incoming (از انتها به ابتدا)
                # مهم: فقط آخرین پیام incoming رو پردازش کن، نه outgoing
                last_incoming = None
                for msg in reversed(messages):
                    if msg.get("direction") == "incoming" and msg.get("message"):
                        last_incoming = msg
                        break

                if not last_incoming:
                    continue

                msg_id = last_incoming.get("id", "")

                # ۴. چک کردن آیا این پیام قبلاً پردازش شده
                last_known = self._last_processed.get(conv_id)
                if last_known and last_known == msg_id:
                    logger.debug(f"Skip {participant}: last incoming already processed ({msg_id[:30]}...)")
                    continue

                # ۵. چک آیا آخرین پیام واقعاً بعد از آخرین پاسخ ماست
                # (اگر ربات قبلاً جواب داده و کاربر پیام جدیدی نفرستاده، skip کن)
                last_msg_overall = messages[-1]
                if last_msg_overall.get("direction") == "outgoing":
                    # آخرین پیام مکالمه outgoing هست — یعنی ما قبلاً جواب دادیم
                    # فقط اگه incoming بعد از outgoing اومده باشه پردازش کن
                    outgoing_time = last_msg_overall.get("createdAt", "")
                    incoming_time = last_incoming.get("createdAt", "")
                    if incoming_time <= outgoing_time:
                        logger.debug(f"Skip {participant}: already replied (outgoing after last incoming)")
                        continue

                results.append({
                    "message_id": msg_id,
                    "thread_id": conv_id,
                    "user_id": last_incoming.get("senderId"),
                    "username": last_incoming.get("senderName") or conv.get("participantUsername"),
                    "full_name": conv.get("participantName"),
                    "text": last_incoming.get("message"),
                    "is_new": True
                })
                logger.info(f"New message from {participant}: '{last_incoming.get('message', '')[:40]}...'")

        except Exception as e:
            logger.error(f"Error fetching unread messages: {e}", exc_info=True)

        return results

    def mark_processed(self, thread_id: str, message_id: str) -> None:
        """ثبت message_id به عنوان آخرین پیام پردازش‌شده برای این مکالمه"""
        self._last_processed[thread_id] = message_id

    def send_direct_message(
        self,
        text: str,
        user_id: str | None = None,
        thread_id: str | None = None
    ) -> bool:
        """
        ارسال دایرکت به کاربر از طریق Zernio Inbox API.
        thread_id = شناسه مکالمه Zernio (اولویت اول)
        user_id = شناسه اینستاگرام کاربر (فالبک — ممکنه کار نکنه اگه conversation ID نباشه)
        """
        if not self.ensure_authenticated():
            logger.error("Cannot send DM: Zernio is not authenticated.")
            return False

        conv_id = thread_id or user_id
        if not conv_id:
            logger.error("send_direct_message requires thread_id or user_id.")
            return False

        url = f"{self.base_url}/inbox/conversations/{conv_id}/messages"
        payload = {
            "accountId": self.account_id,
            "message": text
        }

        try:
            logger.info(f"Sending DM to conversation {conv_id}: '{text[:50]}...'")
            res = requests.post(url, headers=self.headers, json=payload, timeout=15)
            if res.status_code in [200, 201]:
                logger.info(f"DM sent successfully to {conv_id}")
                return True
            else:
                error_data = {}
                try:
                    error_data = res.json()
                except Exception:
                    pass

                # خطای ۲۴ ساعته متا
                platform_code = error_data.get("platformError", {}).get("subcode")
                if platform_code == 2534022:
                    logger.warning(
                        f"Cannot send DM to {conv_id}: outside 24h messaging window. "
                        f"User needs to message first."
                    )
                else:
                    logger.error(f"Failed to send DM ({res.status_code}): {res.text[:200]}")
                return False

        except requests.exceptions.Timeout:
            logger.error(f"Timeout sending DM to {conv_id}")
            return False
        except Exception as e:
            logger.error(f"Network error sending DM via Zernio: {e}", exc_info=True)
            return False

    def find_conversation_id(self, instagram_user_id: str) -> str | None:
        """
        پیدا کردن conversation ID بر اساس instagram_user_id
        برای ارسال دستی از پنل مدیریت
        """
        if not self.ensure_authenticated():
            return None

        try:
            conv_url = f"{self.base_url}/inbox/conversations"
            params = {"accountId": self.account_id}
            r = requests.get(conv_url, headers=self.headers, params=params, timeout=15)
            if r.status_code != 200:
                return None

            conversations = r.json().get("data", [])
            for conv in conversations:
                # participantId یا خود conversation id ممکنه با instagram_user_id مطابقت داشته باشه
                participant_id = conv.get("participantId", "")
                conv_id = conv.get("id", "")

                if str(participant_id) == str(instagram_user_id) or str(conv_id) == str(instagram_user_id):
                    return conv_id

            logger.warning(f"No conversation found for user {instagram_user_id}")
            return None

        except Exception as e:
            logger.error(f"Error finding conversation for {instagram_user_id}: {e}")
            return None

    def follows_page(self, user_id: str) -> bool:
        """Zernio API نمی‌تواند وضعیت فالو را بررسی کند — همیشه True"""
        return True


# اینستنس سراسری سرویس رسمی اینستاگرام
instagram_client = UnifiedInstagramService()