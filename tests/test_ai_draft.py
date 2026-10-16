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
        self.db.commit()
        # کلید env نباید در تست دخالت کند
        self.env_patch = patch.object(gemini_service.env_settings, "GEMINI_API_KEY", "")
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
        self.db.commit()

        app = FastAPI()
        app.include_router(customer_router)
        app.dependency_overrides[require_auth] = lambda: None
        app.dependency_overrides[get_db] = lambda: self.db
        self.client = TestClient(app)

    def tearDown(self):
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


if __name__ == "__main__":
    unittest.main()
