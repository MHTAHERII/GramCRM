import hashlib
import hmac
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.middleware.sessions import SessionMiddleware

from app.auth import router as auth_router
from app.database import get_db
from app.service import automation_service as automation_service_module
from app.service.chat_service import _claims_followed
from app.service.system_service import create_backup
from app.routers.settings import _mask_secret
from app.routers.webhook import _verify_meta_signature


class FollowClaimTests(unittest.TestCase):
    """اعلام فالو باید «فالو نکردم» و «نفالو کردم» را نفی کند"""

    def test_positive_claims(self):
        self.assertTrue(_claims_followed("فالو کردم"))
        self.assertTrue(_claims_followed("سلام، فالو شدم ✅"))

    def test_negations_are_not_claims(self):
        self.assertFalse(_claims_followed("فالو نکردم"))
        self.assertFalse(_claims_followed("نفالو کردم"))
        self.assertFalse(_claims_followed("بابا فالو نکردم نه"))

    def test_unrelated_text(self):
        self.assertFalse(_claims_followed("سلام"))
        self.assertFalse(_claims_followed("قیمت اسانس گل محمدی چنده؟"))


class SecretMaskingTests(unittest.TestCase):
    def test_mask_hides_middle_of_key(self):
        masked = _mask_secret("sk_abc123xyz9")
        self.assertIn("•••", masked)
        self.assertTrue(masked.startswith("sk_a"))
        self.assertTrue(masked.endswith("xyz9"))
        self.assertNotIn("123", masked)

    def test_mask_short_and_empty(self):
        self.assertEqual(_mask_secret(None), None)
        self.assertEqual(_mask_secret(""), None)
        self.assertEqual(_mask_secret("short"), "••••••••")


class MetaWebhookSignatureTests(unittest.TestCase):
    def _signature(self, body: bytes, secret: str) -> str:
        return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()

    def test_valid_signature_accepted(self):
        body = b'{"object":"page"}'
        with patch("app.config.settings.META_APP_SECRET", "s3cr3t"):
            self.assertTrue(_verify_meta_signature(body, self._signature(body, "s3cr3t")))

    def test_invalid_signature_rejected(self):
        body = b'{"object":"page"}'
        with patch("app.config.settings.META_APP_SECRET", "s3cr3t"):
            self.assertFalse(_verify_meta_signature(body, "sha256=" + "0" * 64))

    def test_missing_signature_rejected_when_secret_set(self):
        with patch("app.config.settings.META_APP_SECRET", "s3cr3t"):
            self.assertFalse(_verify_meta_signature(b"{}", None))

    def test_no_secret_configured_accepts_all(self):
        with patch("app.config.settings.META_APP_SECRET", ""):
            self.assertTrue(_verify_meta_signature(b"{}", None))


class PauseAllAutomationsTests(unittest.TestCase):
    """خاموش کردن ربات باید اتوماسیون‌های هر دو ارائه‌دهنده رو متوقف کند"""

    def test_pauses_both_providers(self):
        zernio_autos = [
            {"id": "z1", "isActive": True},
            {"id": "z2", "isActive": False},
        ]
        postzen_autos = [
            {"id": "p1", "isActive": True},
        ]
        calls = []

        def fake_list(self):
            return zernio_autos if isinstance(self, type(automation_service_module.zernio_service)) else postzen_autos

        def fake_pause(self, automation_id, active):
            calls.append((type(self).__name__, automation_id, active))
            return True

        with patch.object(type(automation_service_module.zernio_service), "is_configured", return_value=True), \
             patch.object(type(automation_service_module.postzen_service), "is_configured", return_value=True), \
             patch.object(type(automation_service_module.zernio_service), "list_comment_automations", fake_list), \
             patch.object(type(automation_service_module.postzen_service), "list_comment_automations", lambda self: postzen_autos), \
             patch.object(type(automation_service_module.zernio_service), "set_comment_automation_active", fake_pause), \
             patch.object(type(automation_service_module.postzen_service), "set_comment_automation_active", fake_pause):
            paused = automation_service_module.automation_service.pause_all_automations()

        self.assertEqual(paused, 2)
        paused_ids = {c[1] for c in calls}
        self.assertEqual(paused_ids, {"z1", "p1"})


class BackupMaskingTests(unittest.TestCase):
    def test_backup_masks_zernio_key(self):
        setting = SimpleNamespace(
            bot_enabled=True, fallback_message="fb", follow_gate_enabled=False,
            follow_gate_message=None, follow_gate_buttons=None,
            follow_gate_button_title=None, follow_gate_button_url=None,
            comment_reply_enabled=True, comment_public_reply_enabled=False,
            comment_public_reply_text=None, admin_username="admin",
            zernio_api_key="sk_supersecretkey123", zernio_profile_id="prof",
            zernio_account_id="acc", instagram_username="page",
        )
        db = SimpleNamespace(
            query=lambda model: SimpleNamespace(
                all=lambda: [], first=lambda: None,
            )
        )
        with patch("app.service.system_service.get_bot_settings", return_value=setting):
            backup = create_backup(db)
        key = backup["settings"]["zernio_api_key"]
        self.assertIn("•••", key)
        self.assertNotIn("supersecretkey123", key)


class LoginRateLimitTests(unittest.TestCase):
    def setUp(self):
        from app.auth import _LOGIN_ATTEMPTS
        _LOGIN_ATTEMPTS.clear()
        app = FastAPI()
        app.add_middleware(SessionMiddleware, secret_key="test-session-secret")
        app.include_router(auth_router)
        app.dependency_overrides[get_db] = lambda: None
        self.settings_patch = patch(
            "app.auth.get_bot_settings",
            return_value=SimpleNamespace(admin_username="owner", admin_password="test-password"),
        )
        self.settings_patch.start()
        self.client = TestClient(app)

    def tearDown(self):
        self.client.close()
        self.settings_patch.stop()
        from app.auth import _LOGIN_ATTEMPTS
        _LOGIN_ATTEMPTS.clear()

    def test_too_many_login_attempts_are_blocked(self):
        for _ in range(10):
            self.client.post("/auth/login", json={"username": "owner", "password": "wrong"})
        response = self.client.post("/auth/login", json={"username": "owner", "password": "test-password"})
        self.assertEqual(response.status_code, 429)


if __name__ == "__main__":
    unittest.main()
