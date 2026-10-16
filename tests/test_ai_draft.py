"""
تست‌های فاز ۲: پیشنهاد جواب هوشمند (AI Draft) با Google Gemini
"""
import unittest
from datetime import datetime
from uuid import uuid4

import requests as requests_lib
from fastapi import BackgroundTasks, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from unittest.mock import MagicMock, patch

from app.auth import require_auth
from app.database import Base, get_db
from app.models.customer import Customer
from app.models.message import Message
from app.models.product import Product
from app.routers.customer import router as customer_router
from app.routers.settings import update_settings
from app.schemas.bot_setting import BotSettingUpdate
from app.service import gemini_service
from app.service.bot_settings import get_bot_settings
from app.service.gemini_service import GeminiError

# دیتابیس SQLite درون‌حافظه‌ای مشترک این فایل
_engine = create_engine(
    "sqlite://",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
Base.metadata.create_all(_engine)
TestSession = sessionmaker(bind=_engine)

# کشف خودکار زرنیو نباید در تست‌ها درخواست HTTP واقعی بزند
_discovery_patch = None


def setUpModule():
    global _discovery_patch
    _discovery_patch = patch(
        "app.service.zernio_service.zernio_service.discover_account_and_profile",
        return_value=None,
    )
    _discovery_patch.start()


def tearDownModule():
    if _discovery_patch is not None:
        _discovery_patch.stop()


def _make_session():
    return TestSession()


def _seed(db, with_products=True, with_messages=True, username="perfume_fan"):
    cust = Customer(
        instagram_id=f"7{uuid4().hex[:8]}",
        username=username,
        name="مشتری تست",
    )
    db.add(cust)
    db.commit()
    db.refresh(cust)
    if with_messages:
        db.add(Message(customer_id=cust.id, text="قیمت اسانس یاس چنده؟", sender="customer",
                       created_at=datetime.utcnow()))
        db.add(Message(customer_id=cust.id, text="سلام خوش اومدید 🌸", sender="admin",
                       created_at=datetime.utcnow()))
    if with_products:
        db.add(Product(name="اسانس یاس", description="رایحه بهاری", price=150000,
                       stock=5, active=True, unit="میل"))
        db.add(Product(name="محصول مخفی", description="", price=999,
                       stock=1, active=False, unit="عدد"))
        db.commit()
    db.commit()
    return cust


def _ok_response(text="سلام! اسانس یاس ۱۵۰ هزار تومانه 🌸"):
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {
        "candidates": [{"content": {"parts": [{"text": text}]}}]
    }
    return resp


def _ok_openai_response(text="سلام! اسانس یاس ۱۵۰ هزار تومانه 🌸"):
    """پاسخ 200 از گیت‌وی سازگار با OpenAI (فرمت chat/completions)"""
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {"choices": [{"message": {"content": text}}]}
    return resp


class PromptBuildTests(unittest.TestCase):
    def setUp(self):
        self.db = _make_session()
        # دیتابیس این فایل بین تست‌ها مشترک است؛ این کلاس به حالت خالی نیاز دارد
        self.db.query(Message).delete()
        self.db.query(Customer).delete()
        self.db.query(Product).delete()
        self.db.commit()

    def tearDown(self):
        self.db.rollback()
        self.db.close()

    def test_prompt_contains_catalog_and_conversation(self):
        cust = _seed(self.db)
        system_text, user_text = gemini_service.build_prompt(self.db, cust)
        # کاتالوگ فقط محصولات فعال با قیمت و موجودی
        self.assertIn("اسانس یاس", user_text)
        self.assertIn("150,000", user_text)
        self.assertIn("موجودی: 5", user_text)
        self.assertNotIn("محصول مخفی", user_text)
        # تاریخچه مکالمه با برچسب فرستنده
        self.assertIn("مشتری: قیمت اسانس یاس چنده؟", user_text)
        self.assertIn("اپراتور پیج: سلام خوش اومدید", user_text)
        # برچسب مشتری از username
        self.assertIn("perfume_fan", user_text)
        # پرامپت سیستم: محدودیت‌ها
        self.assertIn("فقط فارسی", system_text)
        self.assertIn("۶۰۰", system_text)

    def test_prompt_handles_empty_conversation_and_catalog(self):
        cust = _seed(self.db, with_products=False, with_messages=False, username=None)
        _, user_text = gemini_service.build_prompt(self.db, cust)
        self.assertIn("فعلاً محصولی", user_text)
        self.assertIn("هنوز پیامی", user_text)
        # وقتی username و name هم ندارد → برچسب پیش‌فرض
        self.assertIn("با مشتری", user_text)


class GenerateDraftTests(unittest.TestCase):
    def setUp(self):
        self.db = _make_session()
        gemini_service._last_draft_at.clear()
        self.customer = _seed(self.db)
        self.bot = get_bot_settings(self.db)
        self.bot.gemini_api_key = "AIzaFAKEKEY1234567890"
        self.bot.gemini_model = None
        self.bot.ai_provider = None
        self.bot.ai_base_url = None
        self.db.commit()
        # کلید/سرویس AI از env نباید در تست دخالت کند
        self.env_patch = patch.multiple(
            gemini_service.env_settings,
            GEMINI_API_KEY="",
            AI_PROVIDER="gemini",
            AI_BASE_URL="",
        )
        self.env_patch.start()

    def tearDown(self):
        self.env_patch.stop()
        gemini_service._last_draft_at.clear()
        self.db.rollback()
        self.db.close()

    def _generate(self):
        return gemini_service.generate_draft(self.db, self.customer, self.bot)

    def test_missing_key_raises_400(self):
        self.bot.gemini_api_key = None
        self.db.commit()
        with patch.object(gemini_service.env_settings, "GEMINI_API_KEY", ""):
            with self.assertRaises(GeminiError) as ctx:
                self._generate()
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("تنظیم نشده", ctx.exception.message)

    def test_successful_draft_uses_key_and_model(self):
        with patch.object(gemini_service.requests, "post", return_value=_ok_response()) as mock_post:
            draft = self._generate()
        self.assertEqual(draft, "سلام! اسانس یاس ۱۵۰ هزار تومانه 🌸")
        mock_post.assert_called_once()
        args, kwargs = mock_post.call_args
        self.assertIn("gemini-2.5-flash", args[0])
        self.assertEqual(kwargs["params"]["key"], "AIzaFAKEKEY1234567890")
        self.assertIn("اسانس یاس", kwargs["json"]["contents"][0]["parts"][0]["text"])

    def test_draft_truncated_to_dm_limit(self):
        long_text = "متن خیلی طولانی " * 100
        with patch.object(gemini_service.requests, "post", return_value=_ok_response(long_text)):
            draft = self._generate()
        self.assertEqual(len(draft), gemini_service.MAX_DRAFT_CHARS)

    def test_cooldown_blocks_second_request(self):
        with patch.object(gemini_service.requests, "post", return_value=_ok_response()):
            self._generate()
            with self.assertRaises(GeminiError) as ctx:
                self._generate()
        self.assertEqual(ctx.exception.status_code, 429)
        self.assertIn("چند ثانیه", ctx.exception.message)

    def test_invalid_key_maps_to_400(self):
        resp = MagicMock(status_code=401, text="UNAUTHENTICATED")
        with patch.object(gemini_service.requests, "post", return_value=resp):
            with self.assertRaises(GeminiError) as ctx:
                self._generate()
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("نامعتبر", ctx.exception.message)

    def test_quota_maps_to_429(self):
        resp = MagicMock(status_code=429, text="RESOURCE_EXHAUSTED")
        with patch.object(gemini_service.requests, "post", return_value=resp):
            with self.assertRaises(GeminiError) as ctx:
                self._generate()
        self.assertEqual(ctx.exception.status_code, 429)
        self.assertIn("سهمیه", ctx.exception.message)

    def test_server_error_maps_to_502(self):
        resp = MagicMock(status_code=500, text="boom")
        with patch.object(gemini_service.requests, "post", return_value=resp):
            with self.assertRaises(GeminiError) as ctx:
                self._generate()
        self.assertEqual(ctx.exception.status_code, 502)

    def test_network_error_maps_to_502(self):
        with patch.object(gemini_service.requests, "post",
                          side_effect=requests_lib.ConnectionError("down")):
            with self.assertRaises(GeminiError) as ctx:
                self._generate()
        self.assertEqual(ctx.exception.status_code, 502)
        self.assertIn("اتصال", ctx.exception.message)

    def test_bad_payload_maps_to_502(self):
        resp = MagicMock(status_code=200, text="{}")
        resp.json.return_value = {}
        with patch.object(gemini_service.requests, "post", return_value=resp):
            with self.assertRaises(GeminiError) as ctx:
                self._generate()
        self.assertEqual(ctx.exception.status_code, 502)

    def test_custom_model_used_when_set(self):
        self.bot.gemini_model = "gemini-2.5-pro"
        self.db.commit()
        with patch.object(gemini_service.requests, "post", return_value=_ok_response()) as mock_post:
            self._generate()
        self.assertIn("gemini-2.5-pro", mock_post.call_args.args[0])


class DraftEndpointTests(unittest.TestCase):
    def setUp(self):
        gemini_service._last_draft_at.clear()
        self.db = _make_session()
        self.customer = _seed(self.db)
        self.bot = get_bot_settings(self.db)
        self.bot.gemini_api_key = "AIzaFAKEKEY1234567890"
        self.bot.ai_provider = None
        self.bot.ai_base_url = None
        self.db.commit()
        self.env_patch = patch.multiple(
            gemini_service.env_settings,
            AI_PROVIDER="gemini",
            AI_BASE_URL="",
        )
        self.env_patch.start()

        app = FastAPI()
        app.include_router(customer_router)
        app.dependency_overrides[require_auth] = lambda: None
        app.dependency_overrides[get_db] = lambda: self.db
        self.client = TestClient(app)

    def tearDown(self):
        self.env_patch.stop()
        self.client.close()
        gemini_service._last_draft_at.clear()
        self.db.rollback()
        self.db.close()

    def test_draft_endpoint_full_path(self):
        # مسیر کامل: endpoint → get_bot_settings → generate_draft → requests
        with patch.object(gemini_service.requests, "post",
                          return_value=_ok_response("پیشنهاد متن")):
            resp = self.client.post(f"/customers/{self.customer.id}/ai-draft")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["draft"], "پیشنهاد متن")

    def test_draft_endpoint_maps_service_error(self):
        with patch(
            "app.service.gemini_service.generate_draft",
            side_effect=GeminiError("کلید Gemini تنظیم نشده است", 400),
        ):
            resp = self.client.post(f"/customers/{self.customer.id}/ai-draft")
        self.assertEqual(resp.status_code, 400)
        self.assertIn("تنظیم نشده", resp.json()["detail"])

    def test_draft_endpoint_unknown_customer_404(self):
        resp = self.client.post("/customers/999999/ai-draft")
        self.assertEqual(resp.status_code, 404)


class SettingsGeminiTests(unittest.TestCase):
    def setUp(self):
        self.db = _make_session()
        self.bot = get_bot_settings(self.db)
        self.bot.gemini_api_key = None
        self.bot.gemini_model = None
        self.bot.ai_provider = "gemini"
        self.bot.ai_base_url = None
        self.db.commit()

    def tearDown(self):
        self.db.rollback()
        self.db.close()

    def test_key_round_trip_is_masked_in_response(self):
        raw = "AIzaSyFakeKey1234567890abcdef"
        result = update_settings(
            BotSettingUpdate(gemini_api_key=raw, gemini_model="gemini-2.5-pro"),
            BackgroundTasks(),
            self.db,
        )
        # در پاسخ API کلید واقعی هرگز برنمی‌گردد
        self.assertIn("•••", result.gemini_api_key)
        self.assertNotIn(raw, result.gemini_api_key)
        self.assertEqual(result.gemini_model, "gemini-2.5-pro")
        # در دیتابیس کلید واقعی ذخیره شده
        self.assertEqual(get_bot_settings(self.db).gemini_api_key, raw)

    def test_masked_value_from_panel_is_ignored(self):
        update_settings(
            BotSettingUpdate(gemini_api_key="AIza•••abcdef"),
            BackgroundTasks(),
            self.db,
        )
        # مقدار ماسک‌شده نباید جایگزین کلید واقعی شود
        self.assertNotEqual(get_bot_settings(self.db).gemini_api_key, "AIza•••abcdef")
        self.assertIsNone(get_bot_settings(self.db).gemini_api_key)

    def test_empty_key_clears_stored_value(self):
        update_settings(
            BotSettingUpdate(gemini_api_key="AIzaWhatever1234567890"),
            BackgroundTasks(),
            self.db,
        )
        self.assertIsNotNone(get_bot_settings(self.db).gemini_api_key)
        update_settings(BotSettingUpdate(gemini_api_key=""), BackgroundTasks(), self.db)
        self.assertIsNone(get_bot_settings(self.db).gemini_api_key)

    def test_model_empty_falls_back_to_default(self):
        update_settings(BotSettingUpdate(gemini_model="  "), BackgroundTasks(), self.db)
        self.assertIsNone(get_bot_settings(self.db).gemini_model)
        # مدل خالی → مدل پیش‌فرض سیستم
        self.assertEqual(gemini_service._resolve_model(get_bot_settings(self.db)),
                         gemini_service.env_settings.GEMINI_MODEL or gemini_service.DEFAULT_MODEL)


class GatewayModeTests(unittest.TestCase):
    """حالت گیت‌وی سازگار با OpenAI (مثل 9Router خودمیزبان روی VPS)"""
    BASE = "http://gw.local:3000/v1"

    def setUp(self):
        self.db = _make_session()
        gemini_service._last_draft_at.clear()
        self.customer = _seed(self.db)
        self.bot = get_bot_settings(self.db)
        self.bot.ai_provider = "openai"
        self.bot.ai_base_url = self.BASE
        self.bot.gemini_api_key = "gw-key-123"
        self.bot.gemini_model = "my-model"
        self.bot.order_notify_enabled = True
        self.db.commit()
        # env نباید در تست دخالت کند
        self.env_patch = patch.multiple(
            gemini_service.env_settings,
            GEMINI_API_KEY="",
            AI_BASE_URL="",
        )
        self.env_patch.start()

    def tearDown(self):
        self.env_patch.stop()
        # ریست برای بی‌طرفی نسبت به ترتیب اجرای کلاس‌ها (دیتابیس این فایل مشترک است)
        self.bot.ai_provider = "gemini"
        self.bot.ai_base_url = None
        self.bot.gemini_api_key = None
        self.bot.gemini_model = None
        self.db.commit()
        gemini_service._last_draft_at.clear()
        self.db.rollback()
        self.db.close()

    def _generate(self, bot=None):
        return gemini_service.generate_draft(self.db, self.customer, bot or self.bot)

    def test_gateway_success_calls_chat_completions(self):
        with patch.object(gemini_service.requests, "post",
                          return_value=_ok_openai_response("پاسخ گیت‌وی")) as mock_post:
            draft = self._generate()
        self.assertEqual(draft, "پاسخ گیت‌وی")
        args, kwargs = mock_post.call_args
        self.assertEqual(args[0], f"{self.BASE}/chat/completions")
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer gw-key-123")
        payload = kwargs["json"]
        self.assertEqual(payload["model"], "my-model")
        self.assertEqual(payload["messages"][0]["role"], "system")
        self.assertEqual(payload["messages"][1]["role"], "user")
        self.assertIn("اسانس یاس", payload["messages"][1]["content"])

    def test_gateway_missing_base_url_raises_400(self):
        self.bot.ai_base_url = None
        self.db.commit()
        with self.assertRaises(GeminiError) as ctx:
            self._generate()
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("آدرس گیت‌وی", ctx.exception.message)

    def test_gateway_without_key_sends_no_auth_header(self):
        self.bot.gemini_api_key = None
        self.db.commit()
        with patch.object(gemini_service.requests, "post",
                          return_value=_ok_openai_response("ok")) as mock_post:
            self._generate()
        self.assertNotIn("Authorization", mock_post.call_args.kwargs["headers"])

    def test_gateway_unauthorized_maps_to_400(self):
        resp = MagicMock(status_code=401, text="unauthorized")
        with patch.object(gemini_service.requests, "post", return_value=resp):
            with self.assertRaises(GeminiError) as ctx:
                self._generate()
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("کلید", ctx.exception.message)

    def test_gateway_unknown_model_maps_to_400(self):
        resp = MagicMock(status_code=400, text="model not found")
        with patch.object(gemini_service.requests, "post", return_value=resp):
            with self.assertRaises(GeminiError) as ctx:
                self._generate()
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("مدل", ctx.exception.message)

    def test_gateway_quota_maps_to_429(self):
        resp = MagicMock(status_code=429, text="rate limit")
        with patch.object(gemini_service.requests, "post", return_value=resp):
            with self.assertRaises(GeminiError) as ctx:
                self._generate()
        self.assertEqual(ctx.exception.status_code, 429)

    def test_gateway_server_error_maps_to_502(self):
        resp = MagicMock(status_code=503, text="unavailable")
        with patch.object(gemini_service.requests, "post", return_value=resp):
            with self.assertRaises(GeminiError) as ctx:
                self._generate()
        self.assertEqual(ctx.exception.status_code, 502)

    def test_gateway_network_error_maps_to_502(self):
        with patch.object(gemini_service.requests, "post",
                          side_effect=requests_lib.ConnectionError("down")):
            with self.assertRaises(GeminiError) as ctx:
                self._generate()
        self.assertEqual(ctx.exception.status_code, 502)
        self.assertIn("اتصال", ctx.exception.message)

    def test_gateway_bad_payload_maps_to_502(self):
        resp = MagicMock(status_code=200, text="{}")
        resp.json.return_value = {}
        with patch.object(gemini_service.requests, "post", return_value=resp):
            with self.assertRaises(GeminiError) as ctx:
                self._generate()
        self.assertEqual(ctx.exception.status_code, 502)

    def test_gateway_truncated_to_dm_limit(self):
        long_text = "متن خیلی طولانی " * 100
        with patch.object(gemini_service.requests, "post",
                          return_value=_ok_openai_response(long_text)):
            draft = self._generate()
        self.assertEqual(len(draft), gemini_service.MAX_DRAFT_CHARS)

    def test_cooldown_shared_between_modes(self):
        with patch.object(gemini_service.requests, "post", return_value=_ok_openai_response()):
            self._generate()
            with self.assertRaises(GeminiError) as ctx:
                self._generate()
        self.assertEqual(ctx.exception.status_code, 429)

    def test_provider_defaults_to_gemini_when_empty(self):
        self.bot.ai_provider = None
        self.db.commit()
        with patch.object(gemini_service.env_settings, "AI_PROVIDER", "gemini"):
            self.assertEqual(gemini_service._resolve_provider(self.bot), "gemini")

    def test_unknown_provider_falls_back_to_gemini(self):
        self.bot.ai_provider = "something"
        self.db.commit()
        with patch.object(gemini_service.env_settings, "AI_PROVIDER", "gemini"):
            self.assertEqual(gemini_service._resolve_provider(self.bot), "gemini")

    def test_provider_and_base_url_round_trip_via_settings(self):
        result = update_settings(
            BotSettingUpdate(ai_provider="OPENAI ", ai_base_url=f" {self.BASE} "),
            BackgroundTasks(),
            self.db,
        )
        # در پاسخ API مقادیر عادی برمی‌گردند (آدرس مخفی نمی‌شود؛ کلید مخفی می‌شود)
        self.assertEqual(result.ai_provider, "openai")
        self.assertEqual(result.ai_base_url, self.BASE)
        stored = get_bot_settings(self.db)
        self.assertEqual(stored.ai_provider, "openai")
        # پس از ذخیره، درخواست واقعاً به گیت‌وی می‌رود
        fresh_bot = get_bot_settings(self.db)
        gemini_service._last_draft_at.clear()
        with patch.object(gemini_service.requests, "post",
                          return_value=_ok_openai_response("از گیت‌وی")) as mock_post:
            draft = gemini_service.generate_draft(self.db, self.customer, fresh_bot)
        self.assertEqual(draft, "از گیت‌وی")
        self.assertTrue(mock_post.call_args.args[0].endswith("/v1/chat/completions"))

    def test_invalid_provider_ignored_on_update(self):
        update_settings(BotSettingUpdate(ai_provider="gemini"), BackgroundTasks(), self.db)
        update_settings(BotSettingUpdate(ai_provider="foo"), BackgroundTasks(), self.db)
        # مقدار نامعتبر پذیرفته نمی‌شود و حالت قبلی حفظ می‌شود
        self.assertEqual(get_bot_settings(self.db).ai_provider, "gemini")

    def test_empty_base_url_clears_stored_value(self):
        update_settings(
            BotSettingUpdate(ai_base_url="http://tmp.local:1/v1"),
            BackgroundTasks(),
            self.db,
        )
        self.assertIsNotNone(get_bot_settings(self.db).ai_base_url)
        update_settings(BotSettingUpdate(ai_base_url=""), BackgroundTasks(), self.db)
        self.assertIsNone(get_bot_settings(self.db).ai_base_url)


if __name__ == "__main__":
    unittest.main()
