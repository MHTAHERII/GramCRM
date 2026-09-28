import unittest
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
            self.assertEqual(socket.receive_json(), {"type": "pong"})


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


if __name__ == "__main__":
    unittest.main()
