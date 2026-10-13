import time
import unittest

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


if __name__ == '__main__':
    unittest.main()
