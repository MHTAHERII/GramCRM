import os
import time
import unittest
from unittest.mock import MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routers import webhook as webhook_mod
from app.config import settings


class WebhookQueueTests(unittest.TestCase):
    def setUp(self):
        # create a tiny app that only mounts the webhook router so no global workers start
        self.app = FastAPI()
        self.app.include_router(webhook_mod.router)
        self.client = TestClient(self.app)
        # clear any leftover queue/cache
        try:
            while not webhook_mod.webhook_queue.empty():
                webhook_mod.webhook_queue.get_nowait()
        except Exception:
            pass
        webhook_mod._processed_event_cache.clear()

    def tearDown(self):
        self.client.close()

    def test_ack_and_enqueue(self):
        payload = {
            "object": "instagram",
            "entry": [
                {"messaging": [{"sender": {"id": "u1"}, "message": {"mid": "m1", "text": "hello"}}]}
            ]
        }
        r = self.client.post("/webhook", json=payload)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json().get("status"), "EVENT_RECEIVED")
        self.assertEqual(webhook_mod.get_queue_size(), 1)

    def test_dedupe_prevents_immediate_duplicate(self):
        payload = {
            "object": "instagram",
            "entry": [
                {"messaging": [{"sender": {"id": "u2"}, "message": {"mid": "mdupe", "text": "dup"}}]}
            ]
        }
        r1 = self.client.post("/webhook", json=payload)
        r2 = self.client.post("/webhook", json=payload)
        self.assertEqual(r1.status_code, 200)
        self.assertEqual(r2.status_code, 200)
        # second should be deduped, queue size stays 1
        self.assertEqual(webhook_mod.get_queue_size(), 1)

    def test_dedupe_expires_after_ttl(self):
        # set a short TTL for test
        orig_ttl = settings.WEBHOOK_DEDUP_TTL_SECONDS
        try:
            settings.WEBHOOK_DEDUP_TTL_SECONDS = 1
            payload = {
                "object": "instagram",
                "entry": [
                    {"messaging": [{"sender": {"id": "u3"}, "message": {"mid": "mttl", "text": "later"}}]}
                ]
            }
            r1 = self.client.post("/webhook", json=payload)
            self.assertEqual(r1.status_code, 200)
            self.assertEqual(webhook_mod.get_queue_size(), 1)
            time.sleep(1.1)
            r2 = self.client.post("/webhook", json=payload)
            self.assertEqual(r2.status_code, 200)
            # after ttl expired, second is accepted
            self.assertEqual(webhook_mod.get_queue_size(), 2)
        finally:
            settings.WEBHOOK_DEDUP_TTL_SECONDS = orig_ttl


class WebhookInlineModeTests(unittest.TestCase):
    """با ENABLE_WEBHOOK_QUEUE=false باید پردازش مستقیم انجام شود، نه سیاه‌چاله صف."""

    def setUp(self):
        self.app = FastAPI()
        self.app.include_router(webhook_mod.router)
        self.client = TestClient(self.app)
        while not webhook_mod.webhook_queue.empty():
            webhook_mod.webhook_queue.get_nowait()
        webhook_mod._processed_event_cache.clear()

    def tearDown(self):
        self.client.close()

    def _payload(self, sender="u10", mid="minline"):
        return {
            "object": "instagram",
            "entry": [
                {"messaging": [{"sender": {"id": sender}, "message": {"mid": mid, "text": "hi"}}]}
            ],
        }

    def test_inline_mode_processes_without_queue(self):
        orig = settings.ENABLE_WEBHOOK_QUEUE
        try:
            settings.ENABLE_WEBHOOK_QUEUE = False
            with patch.object(webhook_mod, "_handle_event_sync") as handler:
                r = self.client.post("/webhook", json=self._payload())
            self.assertEqual(r.status_code, 200)
            self.assertEqual(r.json().get("status"), "EVENT_RECEIVED")
            handler.assert_called_once()
            self.assertEqual(webhook_mod.get_queue_size(), 0)
        finally:
            settings.ENABLE_WEBHOOK_QUEUE = orig

    def test_inline_mode_still_dedupes(self):
        orig = settings.ENABLE_WEBHOOK_QUEUE
        try:
            settings.ENABLE_WEBHOOK_QUEUE = False
            with patch.object(webhook_mod, "_handle_event_sync") as handler:
                self.client.post("/webhook", json=self._payload())
                self.client.post("/webhook", json=self._payload())
            handler.assert_called_once()  # بار دوم باید تشخیص تکرار بخورد
        finally:
            settings.ENABLE_WEBHOOK_QUEUE = orig


class WebhookHandleSyncTests(unittest.TestCase):
    def test_mark_processed_is_not_called(self):
        """mark_processed با کلید پولر یکی نبود و بی‌اثر بود؛ نباید صدا زده شود."""
        session = MagicMock()
        with patch.object(webhook_mod, "SessionLocal", return_value=session), \
                patch.object(webhook_mod, "process_incoming_message", return_value=None) as pim, \
                patch.object(webhook_mod, "instagram_client") as ig:
            webhook_mod._handle_event_sync({"sender_id": "u11", "text": "سلام", "mid": "m11"})
            pim.assert_called_once()
            ig.mark_processed.assert_not_called()
            session.close.assert_called_once()


class WebhookWorkerCountTests(unittest.TestCase):
    def test_default_worker_count_preserves_ordering(self):
        if os.environ.get("WEBHOOK_WORKER_COUNT"):
            self.skipTest("WEBHOOK_WORKER_COUNT در محیط تنظیم شده است")
        self.assertEqual(settings.WEBHOOK_WORKER_COUNT, 1)


if __name__ == '__main__':
    unittest.main()
