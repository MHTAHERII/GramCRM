import time
import unittest
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from starlette.middleware.sessions import SessionMiddleware

from app.auth import router as auth_router, _LOGIN_ATTEMPTS, _constant_time_equals
from app.config import settings as app_settings
from app.database import Base, get_db
from app.models.customer import Customer
from app.models.message import Message
from app.routers.zernio_webhook import _verify_zernio_token
from app.service.chat_service import drop_unsent_reply
from app.service.instagram_service import instagram_client
from app.routers.settings import update_settings, _is_masked_secret
from app.schemas.bot_setting import BotSettingUpdate


# ---------- دیتابیس SQLite درون‌حافظه‌ای برای تست‌های دیتابیسی ----------
# check_same_thread=False چون TestClient درخواست‌ها را در نخ دیگری اجرا می‌کند
from sqlalchemy.pool import StaticPool

_engine = create_engine(
    "sqlite://",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
Base.metadata.create_all(_engine)
TestSession = sessionmaker(bind=_engine)


def _make_session():
    return TestSession()


class NonAsciiLoginTests(unittest.TestCase):
    """لاگین با نام کاربری/رمز فارسی نباید 500 بدهد (compare_digest غیر-ASCII استثنا می‌دهد)"""

    def setUp(self):
        _LOGIN_ATTEMPTS.clear()
        app = FastAPI()
        app.add_middleware(SessionMiddleware, secret_key="test-session-secret")
        app.include_router(auth_router)
        app.dependency_overrides[get_db] = lambda: None
        self.settings_patch = patch(
            "app.auth.get_bot_settings",
            return_value=SimpleNamespace(
                admin_username="مدیر", admin_password="رمز-فارسی-۱۲۳"
            ),
        )
        self.settings_patch.start()
        self.client = TestClient(app)

    def tearDown(self):
        self.client.close()
        self.settings_patch.stop()
        _LOGIN_ATTEMPTS.clear()

    def test_persian_credentials_login_succeeds(self):
        response = self.client.post(
            "/auth/login",
            json={"username": "مدیر", "password": "رمز-فارسی-۱۲۳"},
        )
        self.assertEqual(response.status_code, 200)

    def test_wrong_persian_password_returns_401_not_500(self):
        response = self.client.post(
            "/auth/login",
            json={"username": "مدیر", "password": "اشتباه"},
        )
        self.assertEqual(response.status_code, 401)

    def test_constant_time_equals_handles_unicode(self):
        self.assertTrue(_constant_time_equals("مدیر", "مدیر"))
        self.assertFalse(_constant_time_equals("مدیر", "مدیری"))
        self.assertTrue(_constant_time_equals("admin", "admin"))


class LoginRatePruningTests(unittest.TestCase):
    def test_expired_entries_are_pruned(self):
        from app.auth import _login_rate_ok, _LOGIN_WINDOW_SECONDS

        _LOGIN_ATTEMPTS.clear()
        old = time.time() - (_LOGIN_WINDOW_SECONDS + 10)
        for i in range(1005):
            _LOGIN_ATTEMPTS[f"10.0.0.{i}"] = [old]
        try:
            self.assertTrue(_login_rate_ok("203.0.113.9"))
            # بعد از عبور از سقف، ورودی‌های منقضی پاک شده‌اند
            self.assertLess(len(_LOGIN_ATTEMPTS), 1005)
        finally:
            _LOGIN_ATTEMPTS.clear()


class RetrySendTests(unittest.TestCase):
    """ارسال باید همان لحظه تا ۳ بار تلاش شود (نه در چرخه‌های بعدی که هرگز اجرا نمی‌شد)"""

    def test_succeeds_on_second_attempt(self):
        results = [False, True, True]
        with patch.object(
            instagram_client, "send_direct_message", side_effect=results
        ) as mock_send:
            ok = instagram_client.send_direct_message_with_retry(
                "سلام", user_id="u1", attempts=3, backoff_seconds=0
            )
        self.assertTrue(ok)
        self.assertEqual(mock_send.call_count, 2)

    def test_gives_up_after_max_attempts(self):
        with patch.object(
            instagram_client, "send_direct_message", return_value=False
        ) as mock_send:
            ok = instagram_client.send_direct_message_with_retry(
                "سلام", thread_id="t1", attempts=3, backoff_seconds=0
            )
        self.assertFalse(ok)
        self.assertEqual(mock_send.call_count, 3)

    def test_immediate_success_makes_single_call(self):
        with patch.object(
            instagram_client, "send_direct_message", return_value=True
        ) as mock_send:
            ok = instagram_client.send_direct_message_with_retry(
                "سلام", user_id="u1", attempts=3, backoff_seconds=0
            )
        self.assertTrue(ok)
        self.assertEqual(mock_send.call_count, 1)


class DropUnsentReplyDbTests(unittest.TestCase):
    def setUp(self):
        self.db = _make_session()
        self.customer = Customer(instagram_id="91111", username="user1")
        self.db.add(self.customer)
        self.db.commit()
        self.db.refresh(self.customer)

        self.recent_bot = Message(
            customer_id=self.customer.id, text="پاسخ تکراری", sender="bot"
        )
        self.old_bot = Message(
            customer_id=self.customer.id, text="پاسخ تکراری", sender="bot",
            created_at=datetime.utcnow() - timedelta(minutes=30),
        )
        self.inbound = Message(
            customer_id=self.customer.id, text="سلام", sender="customer",
            instagram_message_id="ig-1",
        )
        self.db.add_all([self.recent_bot, self.old_bot, self.inbound])
        self.db.commit()
        for m in (self.recent_bot, self.old_bot, self.inbound):
            self.db.refresh(m)

    def tearDown(self):
        self.db.rollback()
        self.db.query(Message).delete()
        self.db.query(Customer).delete()
        self.db.commit()
        self.db.close()

    def test_only_recent_matching_bot_message_is_dropped(self):
        drop_unsent_reply(self.db, "91111", "پاسخ تکراری")
        remaining = self.db.query(Message).all()
        ids = {m.id for m in remaining}
        self.assertNotIn(self.recent_bot.id, ids)
        self.assertIn(self.old_bot.id, ids)       # رکورد قدیمی‌تر حفظ می‌شود
        self.assertIn(self.inbound.id, ids)       # پیام مشتری حفظ می‌شود

    def test_non_matching_text_is_untouched(self):
        drop_unsent_reply(self.db, "91111", "متنی که اصلاً ثبت نشده")
        self.assertEqual(len(self.db.query(Message).all()), 3)

    def test_unknown_user_is_noop(self):
        drop_unsent_reply(self.db, "00000", "پاسخ تکراری")
        self.assertEqual(len(self.db.query(Message).all()), 3)


class MaskedKeyGuardTests(unittest.TestCase):
    """مقدار ماسک‌شده (•••) نباید به‌جای کلید واقعی ذخیره یا شناسه‌ها پاک شوند"""

    def _setting(self):
        return SimpleNamespace(
            id=1,
            bot_enabled=True,
            fallback_message="پاسخ پیش‌فرض",
            follow_gate_enabled=False,
            follow_gate_message="فالو کنید",
            follow_gate_buttons=None,
            follow_gate_button_title=None,
            follow_gate_button_url=None,
            comment_reply_enabled=True,
            comment_public_reply_enabled=False,
            comment_public_reply_text=None,
            admin_username="admin",
            admin_password="existing-hash-or-plain",
            zernio_api_key="sk_real_key_1234567890",
            zernio_profile_id="prof-1",
            zernio_account_id="acc-1",
            instagram_username="my_page",
            automation_provider="zernio",
            postzen_api_key="pzn_live_real_key_1234567890",
            postzen_account_id="pzn-acc-1",
            updated_at=datetime.utcnow(),
        )

    def _run(self, data):
        setting = self._setting()
        from fastapi import BackgroundTasks

        with patch("app.routers.settings.get_bot_settings", return_value=setting), \
             patch("app.routers.settings.zernio_service") as mock_zernio, \
             patch("app.service.bot_settings.apply_credentials_to_services", lambda s: None):
            mock_zernio.discover_account_and_profile.return_value = None
            update_settings(data, BackgroundTasks(), db=MagicMock())
        return setting

    def test_masked_zernio_key_is_ignored(self):
        setting = self._run(BotSettingUpdate(zernio_api_key="sk_r•••7890"))
        self.assertEqual(setting.zernio_api_key, "sk_real_key_1234567890")
        # شناسه‌های اکانت نباید پاک شوند
        self.assertEqual(setting.zernio_account_id, "acc-1")
        self.assertEqual(setting.zernio_profile_id, "prof-1")
        self.assertEqual(setting.instagram_username, "my_page")

    def test_masked_postzen_key_is_ignored(self):
        setting = self._run(BotSettingUpdate(postzen_api_key="pzn•••67890"))
        self.assertEqual(setting.postzen_api_key, "pzn_live_real_key_1234567890")

    def test_real_new_key_is_accepted(self):
        setting = self._run(BotSettingUpdate(zernio_api_key="sk_brand_new_key_000"))
        self.assertEqual(setting.zernio_api_key, "sk_brand_new_key_000")
        self.assertIsNone(setting.zernio_account_id)

    def test_is_masked_helper(self):
        self.assertTrue(_is_masked_secret("sk_a•••xyz9"))
        self.assertFalse(_is_masked_secret("sk_real_key"))
        self.assertFalse(_is_masked_secret(None))
        self.assertFalse(_is_masked_secret(""))


class ZernioTokenVerifyTests(unittest.TestCase):
    def _request(self, header=None, query=None):
        req = MagicMock()
        req.headers = {"X-Zernio-Webhook-Token": header} if header else {}
        req.query_params = {"token": query} if query else {}
        return req

    def test_matching_header_accepted(self):
        with patch("app.routers.zernio_webhook.settings") as s:
            s.ZERNIO_WEBHOOK_SECRET = "tok-123"
            self.assertTrue(_verify_zernio_token(self._request(header="tok-123")))

    def test_wrong_header_rejected(self):
        with patch("app.routers.zernio_webhook.settings") as s:
            s.ZERNIO_WEBHOOK_SECRET = "tok-123"
            self.assertFalse(_verify_zernio_token(self._request(header="wrong")))

    def test_query_param_fallback(self):
        with patch("app.routers.zernio_webhook.settings") as s:
            s.ZERNIO_WEBHOOK_SECRET = "tok-123"
            self.assertTrue(_verify_zernio_token(self._request(query="tok-123")))

    def test_no_secret_accepts_all(self):
        with patch("app.routers.zernio_webhook.settings") as s:
            s.ZERNIO_WEBHOOK_SECRET = ""
            self.assertTrue(_verify_zernio_token(self._request()))


class RestoreUploadLimitTests(unittest.TestCase):
    def setUp(self):
        from app.routers.system import router as system_router

        app = FastAPI()
        app.include_router(system_router)
        app.dependency_overrides[get_db] = lambda: MagicMock()
        from app.auth import require_auth
        app.dependency_overrides[require_auth] = lambda: None
        self.client = TestClient(app)

    def tearDown(self):
        self.client.close()

    def test_oversized_file_rejected_with_413(self):
        with patch("app.routers.system._MAX_RESTORE_BYTES", 100):
            response = self.client.post(
                "/system/restore",
                files={"file": ("backup.json", b"x" * 200, "application/json")},
            )
        self.assertEqual(response.status_code, 413)

    def test_non_json_extension_rejected(self):
        response = self.client.post(
            "/system/restore",
            files={"file": ("backup.txt", b"{}", "text/plain")},
        )
        self.assertEqual(response.status_code, 400)

    def test_valid_small_json_passes_validation(self):
        # فقط اعتبارسنجی حجم/پسوند را تست می‌کنیم؛ محتوای لیست (غیر-شیء) باید بعد از سقف رد شود
        with patch("app.routers.system._MAX_RESTORE_BYTES", 1024):
            response = self.client.post(
                "/system/restore",
                files={"file": ("backup.json", b"[1,2,3]", "application/json")},
            )
        # لیست معتبر JSON ولی فرمت بکاپ نیست → خطای ساختاری (500 از ریستور یا 400)
        self.assertIn(response.status_code, (400, 500))


class NormalizedKeywordDupTests(unittest.TestCase):
    def setUp(self):
        from app.routers.keyword import router as keyword_router
        from app.auth import require_auth

        app = FastAPI()
        app.include_router(keyword_router)
        app.dependency_overrides[require_auth] = lambda: None
        app.dependency_overrides[get_db] = lambda: self._fake_db()
        self.client = TestClient(app)

    def _fake_db(self):
        row = SimpleNamespace(id=1, keyword="قیمت", response="پاسخ")
        q = MagicMock()
        q.all.return_value = [row]
        q.filter.return_value.first.return_value = row
        db = MagicMock()
        db.query.return_value = q
        db.get.return_value = None

        def _refresh(obj):
            # مدل‌های SQLAlchemy بعد از flush مقدار می‌گیرند؛ اینجا جایگزین می‌کنیم
            if getattr(obj, "id", None) is None:
                obj.id = 10
            if getattr(obj, "active", None) is None:
                obj.active = True
            if getattr(obj, "created_at", None) is None:
                obj.created_at = datetime.utcnow()

        db.refresh.side_effect = _refresh
        return db

    def tearDown(self):
        self.client.close()

    def test_arabic_variant_detected_as_duplicate(self):
        # «قيمت» با ي عربی باید تکراری «قیمت» با ي فارسی شناخته شود
        response = self.client.post(
            "/keywords/",
            json={"keyword": "قيمت", "response": "پاسخ"},
        )
        self.assertEqual(response.status_code, 409)

    def test_different_keyword_accepted(self):
        response = self.client.post(
            "/keywords/",
            json={"keyword": "ارزان", "response": "پاسخ"},
        )
        self.assertNotEqual(response.status_code, 409)


class MessagesEndpointLimitTests(unittest.TestCase):
    def setUp(self):
        from app.routers.message import router as message_router
        from app.auth import require_auth

        self.db = _make_session()
        cust = Customer(instagram_id="88888")
        self.db.add(cust)
        self.db.commit()
        self.db.refresh(cust)
        for i in range(5):
            self.db.add(Message(customer_id=cust.id, text=f"msg {i}", sender="customer"))
        self.db.commit()

        app = FastAPI()
        app.include_router(message_router)
        app.dependency_overrides[require_auth] = lambda: None
        app.dependency_overrides[get_db] = lambda: self.db
        self.client = TestClient(app)

    def tearDown(self):
        self.client.close()
        self.db.query(Message).delete()
        self.db.query(Customer).delete()
        self.db.commit()
        self.db.close()

    def test_limit_caps_results(self):
        response = self.client.get("/messages/?limit=2")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()), 2)

    def test_default_limit_returns_all_small_sets(self):
        response = self.client.get("/messages/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()), 5)

    def test_oversized_limit_is_clamped_to_1000(self):
        response = self.client.get("/messages/?limit=999999")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()), 5)


class SessionMiddlewareWiringTests(unittest.TestCase):
    def test_session_middleware_uses_configured_https_only(self):
        from app.main import app as main_app
        from starlette.middleware.sessions import SessionMiddleware as SM

        mw = [m for m in main_app.user_middleware if m.cls is SM]
        self.assertTrue(mw, "SessionMiddleware must be installed")
        kwargs = getattr(mw[0], "kwargs", None) or {}
        self.assertEqual(kwargs.get("https_only"), app_settings.SESSION_HTTPS_ONLY)
        self.assertEqual(kwargs.get("same_site"), "lax")

    def test_default_is_false_for_local_http_dev(self):
        self.assertFalse(
            app_settings.SESSION_HTTPS_ONLY,
            "پیش‌فرض باید false بماند تا توسعه لوکال با http خراب نشود",
        )


if __name__ == "__main__":
    unittest.main()
