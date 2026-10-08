import unittest
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.middleware.sessions import SessionMiddleware

from app.auth import require_auth
from app.database import get_db
from app.routers.keyword import router as keyword_router
from app.routers.message import router as message_router
from app.service.instagram_service import _bounded_put, instagram_client
from app.service.bot_settings import REMINDER_NOT_FOLLOWED


class BoundedCacheTests(unittest.TestCase):
    """کش‌های درون‌حافظه‌ای نباید بدون سقف رشد کنند"""

    def test_cache_evicts_oldest_beyond_limit(self):
        cache = {}
        for i in range(50):
            _bounded_put(cache, i, i, maxsize=10)
        self.assertLessEqual(len(cache), 10)
        self.assertIn(49, cache)
        self.assertNotIn(0, cache)

    def test_existing_key_is_updated_in_place(self):
        cache = {}
        _bounded_put(cache, "a", 1, maxsize=5)
        _bounded_put(cache, "a", 2, maxsize=5)
        self.assertEqual(cache["a"], 2)
        self.assertEqual(len(cache), 1)


class FakeMessageDb:
    def add(self, obj):
        self.obj = obj

    def commit(self):
        pass

    def refresh(self, obj):
        if getattr(obj, "id", None) is None:
            obj.id = 1
        if getattr(obj, "created_at", None) is None:
            obj.created_at = datetime.utcnow()


class CreateMessageTests(unittest.TestCase):
    """ثبت پیام با فرستنده customer از مسیر API مسدود است (جلوگیری از جعل تاریخچه)"""

    def setUp(self):
        app = FastAPI()
        app.add_middleware(SessionMiddleware, secret_key="test-session-secret")
        app.include_router(message_router)
        app.dependency_overrides[get_db] = lambda: FakeMessageDb()
        app.dependency_overrides[require_auth] = lambda: None
        self.client = TestClient(app)

    def tearDown(self):
        self.client.close()

    def test_customer_sender_is_rejected(self):
        response = self.client.post(
            "/messages/",
            json={"customer_id": 1, "text": "سلام", "sender": "customer"},
        )
        self.assertEqual(response.status_code, 400)

    def test_admin_sender_is_allowed(self):
        response = self.client.post(
            "/messages/",
            json={"customer_id": 1, "text": "سلام", "sender": "admin"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["sender"], "admin")


class DocsDisabledTests(unittest.TestCase):
    def test_openapi_and_docs_are_not_public_by_default(self):
        from app.main import app
        self.assertIsNone(app.docs_url)
        self.assertIsNone(app.openapi_url)
        self.assertIsNone(app.redoc_url)


class FakeKeywordDb:
    def __init__(self, keyword_row=None):
        self._row = keyword_row

    def get(self, *args):
        return None

    def query(self, *args):
        q = MagicMock()
        q.filter.return_value.first.return_value = self._row
        return q

    def add(self, obj):
        pass

    def commit(self):
        pass

    def refresh(self, obj):
        if getattr(obj, "id", None) is None:
            obj.id = 99
            obj.created_at = datetime.utcnow()


class EmptyKeywordTests(unittest.TestCase):
    def setUp(self):
        app = FastAPI()
        app.add_middleware(SessionMiddleware, secret_key="test-session-secret")
        app.include_router(keyword_router)
        app.dependency_overrides[require_auth] = lambda: None
        self.client = TestClient(app)

    def tearDown(self):
        self.client.close()

    def test_whitespace_keyword_rejected_on_create(self):
        app = self.client.app
        app.dependency_overrides[get_db] = lambda: FakeKeywordDb()
        response = self.client.post(
            "/keywords/",
            json={"keyword": "   ", "response": "پاسخ"},
        )
        self.assertIn(response.status_code, (400, 422))

    def test_whitespace_response_rejected_on_create(self):
        app = self.client.app
        app.dependency_overrides[get_db] = lambda: FakeKeywordDb()
        response = self.client.post(
            "/keywords/",
            json={"keyword": "قیمت", "response": "  "},
        )
        self.assertIn(response.status_code, (400, 422))

    def test_whitespace_keyword_rejected_on_update(self):
        app = self.client.app
        row = SimpleNamespace(
            id=1, keyword="قدیمی", response="پاسخ", active=True,
            product_id=None, comment_reply=None, buttons=None,
            button_title=None, button_url=None,
            comment_reply_delay_seconds=0, dm_delay_seconds=0,
            comment_reply_variations=None, dm_message_variations=None,
            platform_post_id=None,
        )
        app.dependency_overrides[get_db] = lambda: FakeKeywordDb(keyword_row=row)
        response = self.client.put("/keywords/1", json={"keyword": "   "})
        self.assertEqual(response.status_code, 400)


class FollowsPageTests(unittest.TestCase):
    def test_unknown_user_fails_open_as_follower(self):
        try:
            self.assertTrue(instagram_client.follows_page("never-seen-user-xyz"))
        finally:
            instagram_client._follower_cache.pop("never-seen-user-xyz", None)

    def test_cached_status_is_respected(self):
        instagram_client._follower_cache["cached-non-follower"] = False
        try:
            self.assertFalse(instagram_client.follows_page("cached-non-follower"))
        finally:
            instagram_client._follower_cache.pop("cached-non-follower", None)


class FollowGateUnificationTests(unittest.TestCase):
    """متن «هنوز فالو نشده» زرنیو باید با یادآوری بات داخلی یکی باشد"""

    def test_zernio_not_following_message_matches_internal_reminder(self):
        from app.service.zernio_service import zernio_service

        captured = {}

        def fake_post(url, headers=None, json=None, timeout=None):
            captured["payload"] = json
            response = MagicMock(status_code=201)
            response.json.return_value = {"ok": True}
            return response

        with patch.object(zernio_service, "is_configured", return_value=True), \
             patch("app.service.zernio_service.requests.post", side_effect=fake_post):
            zernio_service.create_comment_automation(
                name="KW_1_تست",
                keywords=["قیمت"],
                dm_message="سلام",
                follow_gate_message="برای ادامه فالو کنید",
            )

        self.assertIn("followGate", captured["payload"])
        self.assertEqual(
            captured["payload"]["followGate"]["notFollowingMessage"],
            REMINDER_NOT_FOLLOWED,
        )


if __name__ == "__main__":
    unittest.main()
