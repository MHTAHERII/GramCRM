import logging
import requests
from app.config import settings

logger = logging.getLogger("instagram_service")

# سقف ورودی‌های کش‌های درون‌حافظه‌ای (جلوگیری از نشت حافظه در اجرای بلندمدت)
_CACHE_MAX_ENTRIES = 3000


def _bounded_put(cache: dict, key, value, maxsize: int = _CACHE_MAX_ENTRIES) -> None:
    """درج در کش با سقف اندازه؛ قدیمی‌ترین ورودی‌ها حذف می‌شوند"""
    cache[key] = value
    if len(cache) > maxsize:
        for old_key in list(cache.keys())[: len(cache) - maxsize]:
            cache.pop(old_key, None)


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
        # کش پرسرعت مکالمات (ارسال فوری بدون تاخیر شبکه)
        self._conv_cache: dict[str, str] = {}
        self._conv_updated_times: dict[str, str] = {}
        self._follower_cache: dict[str, bool] = {}
        self._rate_limit_until: float = 0.0
        self.session = requests.Session()

    @property
    def headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }

    def login(self) -> bool:
        """بررسی آماده بودن کلید و اکانت"""
        if self.ensure_authenticated():
            logger.info("Instagram (Zernio API) is ready.")
            return True
        logger.warning("Zernio API key or Account ID is missing.")
        return False

    def ensure_authenticated(self) -> bool:
        if bool(self.api_key and self.account_id):
            return True
        if self.api_key and not self.account_id:
            from app.service.zernio_service import zernio_service
            discovered = zernio_service.discover_account_and_profile(self.api_key)
            if discovered and discovered.get("account_id"):
                self.account_id = discovered["account_id"]
                logger.info(f"Auto-discovered instagram_client account_id: {self.account_id}")
                return True
        return False

    def fetch_unread_messages(self, amount: int = 10) -> list[dict]:
        """
        دریافت پیام‌های جدید دایرکت از طریق Zernio Inbox API با مدیریت هوشمند محدودیت نرخ (Rate-limit 429).
        """
        if not self.ensure_authenticated():
            return []

        import time
        if time.time() < self._rate_limit_until:
            wait_rem = int(self._rate_limit_until - time.time())
            logger.debug(f"Rate limited: waiting {wait_rem}s before next fetch...")
            return []

        results = []
        try:
            conv_url = f"{self.base_url}/inbox/conversations"
            params = {"accountId": self.account_id}
            r = self.session.get(conv_url, headers=self.headers, params=params, timeout=10)
            if r.status_code == 429:
                retry_after = 60
                try:
                    retry_after = int(r.json().get("details", {}).get("retryAfterSeconds", 60))
                except Exception:
                    pass
                self._rate_limit_until = time.time() + retry_after
                logger.warning(f"Zernio Rate Limit (429) hit! Pausing polling for {retry_after}s.")
                return []

            if r.status_code != 200:
                logger.error(f"Failed to fetch conversations ({r.status_code}): {r.text}")
                return []

            from datetime import datetime, timezone, timedelta
            now = datetime.now(timezone.utc)

            conversations = r.json().get("data", [])

            # تازه‌ترین مکالمه‌ها اول بررسی شوند تا پیام‌های جدید در همان چرخه پردازش شوند
            conversations = sorted(
                conversations,
                key=lambda c: c.get("updatedTime") or "",
                reverse=True,
            )

            for conv in conversations[:amount]:
                conv_id = conv.get("id")
                participant = conv.get("participantUsername") or conv.get("participantName") or "unknown"
                part_id = conv.get("participantId")
                updated_str = conv.get("updatedTime")

                # ثبت در کش مکالمات جهت پاسخ‌گویی بدون تاخیر از پنل
                if conv_id:
                    _bounded_put(self._conv_cache, str(conv_id), conv_id)
                    if part_id: _bounded_put(self._conv_cache, str(part_id), conv_id)
                    if participant and participant != "unknown":
                        _bounded_put(self._conv_cache, str(participant).lower(), conv_id)

                # کش کردن وضعیت فالوور از دیتای Zernio
                if part_id and "instagramProfile" in conv and isinstance(conv["instagramProfile"], dict):
                    if "isFollower" in conv["instagramProfile"]:
                        _bounded_put(self._follower_cache, str(part_id), bool(conv["instagramProfile"]["isFollower"]))

                # بهینه‌سازی بسیار مهم: اگر مکالمه تغییر نکرده، هیچ درخواست HTTP اضافی ارسال نکن!
                if conv_id and updated_str:
                    if self._conv_updated_times.get(str(conv_id)) == updated_str:
                        continue

                # ۱. فیلتر ۲۴ ساعته — خارج از پنجره مجاز متا
                if updated_str:
                    try:
                        updated_dt = datetime.fromisoformat(updated_str.replace("Z", "+00:00"))
                        if (now - updated_dt) > timedelta(hours=23):
                            logger.debug(f"Skip conversation {participant}: outside 24h window")
                            if conv_id: _bounded_put(self._conv_updated_times, str(conv_id), updated_str)
                            continue
                    except Exception:
                        pass

                # ۲. دریافت پیام‌های مکالمه (تنها در صورتی که پیام جدیدی آمده باشد)
                msg_url = f"{self.base_url}/inbox/conversations/{conv_id}/messages"
                m_res = self.session.get(msg_url, headers=self.headers, params=params, timeout=10)
                if m_res.status_code == 429:
                    self._rate_limit_until = time.time() + 60
                    logger.warning("Zernio Rate Limit (429) hit on messages endpoint! Pausing polling for 60s.")
                    break
                if m_res.status_code != 200:
                    logger.warning(f"Failed to fetch messages for {participant} ({m_res.status_code})")
                    continue

                if conv_id and updated_str:
                    _bounded_put(self._conv_updated_times, str(conv_id), updated_str)

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
        _bounded_put(self._last_processed, thread_id, message_id)

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

        msg_text = text[:640] if len(text) > 640 else text
        url = f"{self.base_url}/inbox/conversations/{conv_id}/messages"
        payload = {
            "accountId": self.account_id,
            "message": msg_text
        }

        try:
            logger.info(f"Sending DM to conversation {conv_id}: '{text[:50]}...'")
            res = self.session.post(url, headers=self.headers, json=payload, timeout=8)
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
                    return False

                # حل خودکار خطای Handover Protocol (409 Conflict / Meta subcode 2534037)
                # اگر گفتگو در کنترل سیستم دیگری (مثل اینباکس منیجر یا پیج فیس‌بوک) باشد، کنترل را پس می‌گیریم
                is_handover_conflict = (
                    res.status_code == 409 or
                    platform_code == 2534037 or
                    "another receiver" in res.text or
                    "thread-control" in res.text or
                    "take control" in res.text
                )
                if is_handover_conflict:
                    logger.info(f"Handover conflict (409) on {conv_id}. Attempting to take thread control...")
                    control_url = f"{self.base_url}/inbox/conversations/{conv_id}/thread-control"
                    try:
                        c_res = self.session.post(
                            control_url,
                            headers=self.headers,
                            json={"accountId": self.account_id, "action": "take"},
                            timeout=6
                        )
                        if c_res.status_code in [200, 201]:
                            logger.info(f"Thread control successfully taken for {conv_id}. Retrying DM send...")
                            retry_res = self.session.post(url, headers=self.headers, json=payload, timeout=8)
                            if retry_res.status_code in [200, 201]:
                                logger.info(f"DM sent successfully after taking thread control to {conv_id}")
                                return True
                            else:
                                logger.error(f"Retry DM send failed after taking control: {retry_res.text[:200]}")
                        else:
                            logger.warning(f"Failed to take thread control ({c_res.status_code}): {c_res.text[:200]}")
                    except Exception as ce:
                        logger.warning(f"Error taking thread control: {ce}")

                logger.error(f"Failed to send DM ({res.status_code}): {res.text[:200]}")
                return False

        except requests.exceptions.Timeout:
            logger.error(f"Timeout sending DM to {conv_id}")
            return False
        except Exception as e:
            logger.error(f"Network error sending DM via Zernio: {e}", exc_info=True)
            return False

    def send_direct_message_with_retry(
        self,
        text: str,
        user_id: str | None = None,
        thread_id: str | None = None,
        attempts: int = 3,
        backoff_seconds: float = 1.0,
    ) -> bool:
        """
        ارسال دایرکت با تلاش مجدد همان لحظه (پشتیبان ارسال‌های ناموفق شبکه).
        باید در نخ جدا (ThreadPool/executor) اجرا شود چون بین تلاش‌ها sleep دارد.
        """
        import time

        for attempt in range(1, max(attempts, 1) + 1):
            if self.send_direct_message(text=text, user_id=user_id, thread_id=thread_id):
                return True
            if attempt < attempts:
                logger.warning(
                    f"DM send attempt {attempt}/{attempts} failed; retrying in {backoff_seconds * attempt}s..."
                )
                time.sleep(backoff_seconds * attempt)
        return False

    def cache_conversation(self, user_id: str | None, thread_id: str | None, username: str | None = None) -> None:
        """ثبت فوری شناسه مکالمه در کش برای ارسال بلادرنگ از پنل"""
        if thread_id:
            _bounded_put(self._conv_cache, str(thread_id), thread_id)
            if user_id:
                _bounded_put(self._conv_cache, str(user_id), thread_id)
            if username:
                _bounded_put(self._conv_cache, str(username).lower(), thread_id)

    def find_conversation_id(self, instagram_user_id: str) -> str | None:
        """
        پیدا کردن conversation ID بر اساس instagram_user_id
        بررسی فوری کش حافظه (۰ میلی‌ثانیه)، و در صورت نیاز استعلام و کش سریع از Zernio
        """
        if not self.ensure_authenticated():
            return None

        # ۱. بررسی بلادرنگ در کش حافظه (Instant Cache Hit)
        key = str(instagram_user_id).lower()
        if key in self._conv_cache:
            return self._conv_cache[key]
        if str(instagram_user_id) in self._conv_cache:
            return self._conv_cache[str(instagram_user_id)]

        # ۲. در صورت نبود، استعلام سریع از Zernio و کش کردن تمام گفتگوها
        try:
            conv_url = f"{self.base_url}/inbox/conversations"
            params = {"accountId": self.account_id}
            r = self.session.get(conv_url, headers=self.headers, params=params, timeout=8)
            if r.status_code != 200:
                return None

            conversations = r.json().get("data", [])
            target_conv = None
            for conv in conversations:
                cid = conv.get("id", "")
                pid = conv.get("participantId", "")
                puser = conv.get("participantUsername", "")

                if cid:
                    _bounded_put(self._conv_cache, str(cid), cid)
                    if pid: _bounded_put(self._conv_cache, str(pid), cid)
                    if puser: _bounded_put(self._conv_cache, str(puser).lower(), cid)

                if str(pid) == str(instagram_user_id) or str(cid) == str(instagram_user_id) or (puser and str(puser).lower() == key):
                    target_conv = cid

            if not target_conv:
                logger.warning(f"No conversation found for user {instagram_user_id}")
            return target_conv

        except Exception as e:
            logger.error(f"Error finding conversation for {instagram_user_id}: {e}")
            return None

    def follows_page(self, user_id: str) -> bool:
        """
        بررسی وضعیت فالوور از روی کش پروفایل‌های دریافتی زِرنیو.
        اگر وضعیت برای این کاربر هرگز از زرنیو دریافت نشده باشد، فالوور فرض می‌شود
        (fail-open) تا مشتریان مشروع پشت دروازه فالو گیر نکنند.
        """
        if str(user_id) in self._follower_cache:
            return self._follower_cache[str(user_id)]
        logger.debug(
            f"Follower status unknown for user {user_id}; treating as follower (fail-open)."
        )
        return True


# اینستنس سراسری سرویس رسمی اینستاگرام
instagram_client = UnifiedInstagramService()