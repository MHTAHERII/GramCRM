import unittest
import io
import urllib.error
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.middleware.sessions import SessionMiddleware
from starlette.websockets import WebSocketDisconnect

from app.auth import router as auth_router
from app.database import get_db
from app.routers.websocket import router as websocket_router
from app.service.bot_settings import apply_credentials_to_services
from app.service.instagram_service import instagram_client
from app.service.zernio_service import zernio_service
from app.service.system_service import execute_system_update, get_version_info
from app.routers import keyword as keyword_router_module
from app.routers import settings as settings_router_module


class AuthAndWebSocketTests(unittest.TestCase):
    def setUp(self):
        app = FastAPI()
        app.add_middleware(SessionMiddleware, secret_key="test-session-secret")
        app.include_router(auth_router)
        app.include_router(websocket_router)
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

    def test_login_requires_username_and_password(self):
        self.assertEqual(self.client.post("/auth/login", json={"password": "test-password"}).status_code, 422)
        self.assertEqual(
            self.client.post("/auth/login", json={"username": "wrong", "password": "test-password"}).status_code,
            401,
        )
        self.assertEqual(
            self.client.post("/auth/login", json={"username": "owner", "password": "test-password"}).status_code,
            200,
        )

    def test_websocket_requires_login(self):
        with self.assertRaises(WebSocketDisconnect) as error:
            with self.client.websocket_connect("/ws"):
                pass
        self.assertEqual(error.exception.code, 1008)

        self.client.post("/auth/login", json={"username": "owner", "password": "test-password"})
        with self.client.websocket_connect("/ws") as socket:
            socket.send_json({"type": "ping"})
            for _ in range(5):
                if socket.receive_json().get("type") == "pong":
                    break
            else:
                self.fail("WebSocket did not answer ping")


class CredentialTests(unittest.TestCase):
    def test_switching_account_clears_old_account_and_conversation_cache(self):
        original = (instagram_client.api_key, instagram_client.account_id,
                    zernio_service.api_key, zernio_service.account_id, zernio_service.profile_id)
        caches = [instagram_client._conv_cache, instagram_client._conv_updated_times,
                  instagram_client._follower_cache, instagram_client._last_processed]
        originals = [cache.copy() for cache in caches]
        try:
            instagram_client.api_key = "old-key"
            instagram_client.account_id = "old-account"
            for cache in caches:
                cache["old-account"] = "stale"
            with patch("app.config.settings.ZERNIO_API_KEY", ""), patch("app.config.settings.ZERNIO_ACCOUNT_ID", ""), \
                 patch("app.config.settings.ZERNIO_PROFILE_ID", ""):
                apply_credentials_to_services(SimpleNamespace(
                    zernio_api_key=None, zernio_account_id=None, zernio_profile_id=None
                ))
            self.assertFalse(instagram_client.account_id)
            self.assertFalse(zernio_service.account_id)
            self.assertTrue(all(not cache for cache in caches))
        finally:
            (instagram_client.api_key, instagram_client.account_id,
             zernio_service.api_key, zernio_service.account_id, zernio_service.profile_id) = original
            for cache, contents in zip(caches, originals):
                cache.clear()
                cache.update(contents)


class VersionCheckTests(unittest.TestCase):
    def test_railway_without_git_falls_back_to_public_feed_on_api_rate_limit(self):
        sha = "a" * 40
        atom = (f'<feed xmlns="http://www.w3.org/2005/Atom"><entry>'
                f'<id>tag:github.com,2008:Grit::Commit/{sha}</id>'
                f'<title>Recent change</title><updated>2026-09-28T12:00:00Z</updated>'
                f'</entry></feed>').encode()
        def fake_open(request, timeout):
            if "api.github.com" in request.full_url:
                raise urllib.error.HTTPError(request.full_url, 403, "rate limit exceeded", {}, None)
            return io.BytesIO(atom)

        with patch("app.service.system_service.shutil.which", return_value=None), \
             patch.dict("os.environ", {"RAILWAY_GIT_COMMIT_SHA": sha}, clear=False), \
             patch("app.service.system_service.urllib.request.urlopen", side_effect=fake_open) as open_url:
            result = get_version_info()
        self.assertEqual(open_url.call_count, 2)
        self.assertEqual(result["local_commit"], sha[:7])
        self.assertEqual(result["remote_commit"], sha[:7])
        self.assertEqual(result["remote_date"], "2026-09-28")
        self.assertIsNone(result["error"])
        self.assertFalse(result["has_update"])
        self.assertTrue(result["comparison_available"])

    def test_unavailable_remote_does_not_report_current_version(self):
        with patch("app.service.system_service.shutil.which", return_value=None), \
             patch.dict("os.environ", {"RAILWAY_GIT_COMMIT_SHA": ""}, clear=False), \
             patch("app.service.system_service.urllib.request.urlopen", side_effect=TimeoutError):
            result = get_version_info()
        self.assertFalse(result["comparison_available"])
        self.assertIsNotNone(result["error"])
        self.assertNotIn("به‌روز است", result["status"])

    def test_updater_without_git_reports_failure_instead_of_starting(self):
        with patch("app.service.system_service.shutil.which", return_value=None), \
             patch.dict("os.environ", {"RAILWAY_ENVIRONMENT": "", "RAILWAY_PROJECT_ID": ""}, clear=False):
            result = execute_system_update()
        self.assertFalse(result["success"])
        self.assertFalse(result["restarting"])


class BackgroundSyncTests(unittest.TestCase):
    def test_keyword_sync_does_not_mask_session_creation_error(self):
        with patch.object(keyword_router_module, "SessionLocal", side_effect=RuntimeError("db unavailable")):
            keyword_router_module._sync_zernio_bg()

    def test_settings_sync_does_not_mask_session_creation_error(self):
        with patch.object(settings_router_module, "SessionLocal", side_effect=RuntimeError("db unavailable")):
            settings_router_module._sync_zernio_bg()


if __name__ == "__main__":
    unittest.main()
