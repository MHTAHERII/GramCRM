import unittest
from types import SimpleNamespace
from unittest.mock import patch

import requests
from fastapi import HTTPException
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool
from starlette.middleware.sessions import SessionMiddleware

from app.database import Base, get_db
from app.models.bot_setting import BotSetting
from app.models.keyword import Keyword
from app.routers.keyword import get_keyword_diagnostics, router as keyword_router
from app.service import keyword_diagnostics as diagnostics


class KeywordDiagnosticsTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def test_preview_matches_persian_digit_and_shows_other_active_rules(self):
        self.db.add(BotSetting(id=1, fallback_message="پیش‌فرض", follow_gate_enabled=True,
                               follow_gate_message="ابتدا فالو کنید"))
        self.db.add(Keyword(keyword="قیمت", response="پاسخ دیگر", active=True))
        self.db.commit()

        result = diagnostics.preview_comment(self.db, "قیمت ۷ چنده؟", "7", "دایرکت محصول",
                                             "دایرکتت رو چک کن")
        self.assertEqual([m["keyword"] for m in result["matches"]], ["7"])
        self.assertEqual(result["matches"][0]["comment_reply"], "دایرکتت رو چک کن")
        self.assertTrue(result["follow_gate_enabled"])
        self.assertEqual(result["follow_gate_message"], "ابتدا فالو کنید")

    def test_preview_replaces_edited_rule_and_respects_disabled_state(self):
        old = Keyword(keyword="۷", response="قدیمی", comment_reply="قدیمی", active=True)
        self.db.add(old)
        self.db.commit()
        result = diagnostics.preview_comment(self.db, "عدد 7", "7", "جدید", "عمومی",
                                             editing_id=old.id)
        self.assertEqual(len(result["matches"]), 1)
        self.assertEqual(result["matches"][0]["dm_message"], "جدید")

        result = diagnostics.preview_comment(self.db, "عدد 7", "7", "جدید", "عمومی",
                                             editing_id=old.id, draft_active=False)
        self.assertTrue(result["draft_disabled"])
        self.assertEqual(result["matches"], [])

    def test_preview_without_public_reply_stays_exact(self):
        result = diagnostics.preview_comment(self.db, "قیمت 7 چنده؟", "7", "دایرکت", None)
        self.assertEqual(result["matches"], [])
        result = diagnostics.preview_comment(self.db, "7", "7", "دایرکت", None)
        self.assertEqual(result["matches"][0]["match_mode"], "exact")

    def test_delivery_diagnostics_separate_dm_and_public_reply(self):
        sent = Keyword(keyword="7", response="جزئیات", comment_reply="عمومی", active=True)
        disabled = Keyword(keyword="8", response="جزئیات", active=False)
        missing = Keyword(keyword="9", response="جزئیات", active=True)
        self.db.add_all([sent, disabled, missing])
        self.db.commit()
        automations = [
            {"id": "a1", "name": f"KW_{sent.id}_7", "accountId": "a",
             "isActive": True, "stats": {"triggered": 4, "dmsSent": 3, "dmsFailed": 1}},
            {"id": "a2", "name": f"KW_{disabled.id}_8", "accountId": "a", "isActive": True},
            {"id": "a3", "name": "KW_999_deleted", "accountId": "a", "isActive": True},
        ]

        def fake_get(url, **kwargs):
            if url.endswith("/comment-automations"):
                return SimpleNamespace(raise_for_status=lambda: None,
                                       json=lambda: {"automations": automations})
            logs = [{"source": "dm", "status": "sent", "createdAt": "2026-01-02T00:00:00Z"},
                    {"source": "comment", "status": "sent", "commentReplyStatus": "failed",
                     "commentReplyError": "reply rejected", "createdAt": "2026-01-01T00:00:00Z"}]
            return SimpleNamespace(raise_for_status=lambda: None, json=lambda: {"logs": logs})

        with patch.object(diagnostics.zernio_service, "api_key", "test"), \
             patch.object(diagnostics.zernio_service, "profile_id", "p"), \
             patch.object(diagnostics.zernio_service, "account_id", "a"), \
             patch.object(diagnostics.requests, "get", side_effect=fake_get):
            data = diagnostics.keyword_delivery_statuses(self.db)

        by_id = {row["keyword_id"]: row for row in data["keywords"]}
        self.assertEqual(by_id[sent.id]["state"], "synced")
        self.assertEqual(by_id[sent.id]["stats"]["dms_failed"], 1)
        self.assertEqual(by_id[sent.id]["last_comment"]["dm_status"], "sent")
        self.assertEqual(by_id[sent.id]["last_comment"]["reply_status"], "failed")
        self.assertEqual(by_id[disabled.id]["state"], "disabled_remote")
        self.assertEqual(by_id[missing.id]["state"], "not_synced")
        self.assertEqual(data["orphan_automations"], ["KW_999_deleted"])

    def test_remote_error_is_not_displayed_as_no_automations(self):
        with patch.object(diagnostics.zernio_service, "api_key", "test"), \
             patch.object(diagnostics.zernio_service, "profile_id", "p"), \
             patch.object(diagnostics.requests, "get", side_effect=requests.Timeout):
            with self.assertRaises(HTTPException) as error:
                get_keyword_diagnostics(self.db)
        self.assertEqual(error.exception.status_code, 502)

    def test_outdated_remote_reply_is_reported_as_mismatch(self):
        kw = Keyword(keyword="7", response="دایرکت", comment_reply="ریپلای جدید", active=True)
        self.db.add(kw)
        self.db.commit()
        remote = [{"id": "a1", "name": f"KW_{kw.id}_7", "accountId": "a",
                   "isActive": True, "matchMode": "contains", "keywords": ["7", "۷", "٧"],
                   "dmMessage": "دایرکت", "commentReply": "ریپلای قدیمی"}]

        def fake_get(url, **kwargs):
            data = {"automations": remote} if url.endswith("/comment-automations") else {"logs": []}
            return SimpleNamespace(raise_for_status=lambda: None, json=lambda: data)

        with patch.object(diagnostics.zernio_service, "api_key", "test"), \
             patch.object(diagnostics.zernio_service, "profile_id", "p"), \
             patch.object(diagnostics.zernio_service, "account_id", "a"), \
             patch.object(diagnostics.requests, "get", side_effect=fake_get):
            result = diagnostics.keyword_delivery_statuses(self.db)
        self.assertEqual(result["keywords"][0]["state"], "config_mismatch")

    def test_renamed_rule_retains_its_old_remote_log_until_sync(self):
        kw = Keyword(keyword="new", response="DM", active=True)
        self.db.add(kw)
        self.db.commit()
        remote = [{"id": "old-id", "name": f"KW_{kw.id}_old", "accountId": "a", "isActive": True}]

        def fake_get(url, **kwargs):
            data = {"automations": remote} if url.endswith("/comment-automations") else {"logs": []}
            return SimpleNamespace(raise_for_status=lambda: None, json=lambda: data)

        with patch.object(diagnostics.zernio_service, "api_key", "test"), \
             patch.object(diagnostics.zernio_service, "profile_id", "p"), \
             patch.object(diagnostics.zernio_service, "account_id", "a"), \
             patch.object(diagnostics.requests, "get", side_effect=fake_get):
            result = diagnostics.keyword_delivery_statuses(self.db)
        self.assertEqual(result["keywords"][0]["state"], "config_mismatch")
        self.assertEqual(result["orphan_automations"], [])

    def test_preview_api_requires_login_and_does_not_save(self):
        engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False},
                               poolclass=StaticPool)
        Base.metadata.create_all(engine)
        app = FastAPI()
        app.add_middleware(SessionMiddleware, secret_key="test-secret")
        app.include_router(keyword_router)

        def session_override():
            with Session(engine) as db:
                yield db

        app.dependency_overrides[get_db] = session_override
        request_body = {"text": "قیمت ۷ چنده؟", "keyword": "7", "response": "دایرکت",
                        "comment_reply": "کامنت"}
        try:
            with TestClient(app) as client:
                self.assertEqual(client.post("/keywords/preview", json=request_body).status_code, 401)
                # Signed session cookie for this isolated API test.
                from itsdangerous import TimestampSigner
                import base64
                import json
                cookie = base64.b64encode(json.dumps({"authenticated": True}).encode()).decode()
                client.cookies.set("session", TimestampSigner("test-secret").sign(cookie).decode())
                result = client.post("/keywords/preview", json=request_body)
                self.assertEqual(result.status_code, 200)
                self.assertEqual(result.json()["matches"][0]["keyword"], "7")
            with Session(engine) as db:
                self.assertEqual(db.query(Keyword).count(), 0)
        finally:
            engine.dispose()


if __name__ == "__main__":
    unittest.main()
