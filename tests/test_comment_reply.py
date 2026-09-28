import unittest
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import BackgroundTasks
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.database import Base
from app.models.keyword import Keyword
from app.models.bot_setting import BotSetting
from app.routers.keyword import create_keyword, update_keyword
from app.schemas.keyword import KeywordCreate, KeywordResponse, KeywordUpdate
from app.service.zernio_service import ZernioService, comment_keyword_variants


class CommentReplyTests(unittest.TestCase):
    def test_keyword_field_can_be_created_edited_and_cleared(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        try:
            with Session(engine) as db:
                keyword = create_keyword(
                    KeywordCreate(keyword="7", response="دایرکت", comment_reply="  پاسخ عمومی  "),
                    BackgroundTasks(), db,
                )
                self.assertEqual(keyword.comment_reply, "پاسخ عمومی")
                self.assertEqual(KeywordResponse.model_validate(keyword).comment_reply, "پاسخ عمومی")
                update_keyword(keyword.id, KeywordUpdate(comment_reply="  "), BackgroundTasks(), db)
                self.assertIsNone(db.query(Keyword).first().comment_reply)
        finally:
            engine.dispose()

    def test_contains_match_and_public_reply_are_sent_to_zernio(self):
        service = ZernioService()
        service.api_key = "test-key"
        service.account_id = "test-account"
        service.profile_id = "test-profile"
        response = SimpleNamespace(status_code=201, json=lambda: {"id": "test-automation"})
        with patch("app.service.zernio_service.requests.post", return_value=response) as post:
            service.create_comment_automation(
                name="KW_1_7", keywords=comment_keyword_variants("7"),
                dm_message="جزئیات در دایرکت", comment_reply="  اطلاعات ارسال شد  ",
                follow_gate_message="اول فالو را تأیید کن",
            )
        payload = post.call_args.kwargs["json"]
        self.assertEqual(payload["keywords"], ["7", "۷", "٧"])
        self.assertEqual(payload["matchMode"], "contains")
        self.assertEqual(payload["commentReply"], "اطلاعات ارسال شد")
        self.assertFalse(payload["alsoMatchInDms"])
        self.assertEqual(payload["audience"], {"followerStatus": "follower", "whenUnknown": "verify"})
        self.assertEqual(payload["followGate"]["message"], "اول فالو را تأیید کن")
        self.assertEqual(payload["dmMessage"], "جزئیات در دایرکت")

    def test_sync_passes_saved_public_reply_to_automation(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        try:
            with Session(engine) as db:
                db.add(Keyword(keyword="7", response="جزئیات", comment_reply="ریپلای عمومی", active=True))
                db.commit()
                service = ZernioService()
                service.api_key = "test-key"
                service.account_id = "test-account"
                service.profile_id = "test-profile"
                with patch.object(service, "list_comment_automations", return_value=[]), \
                     patch.object(service, "create_comment_automation", return_value={"id": "a"}) as create, \
                     patch("time.sleep"):
                    result = service.sync_all_keywords(db)
                self.assertEqual(result["synced_count"], 1)
                self.assertEqual(create.call_args.kwargs["comment_reply"], "ریپلای عمومی")
                self.assertEqual(create.call_args.kwargs["keywords"], ["7", "۷", "٧"])
                self.assertIsNone(create.call_args.kwargs["follow_gate_message"])
        finally:
            engine.dispose()

    def test_sync_keeps_existing_global_follow_gate(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        try:
            with Session(engine) as db:
                db.add(BotSetting(id=1, fallback_message="پیش‌فرض", follow_gate_enabled=True,
                                  follow_gate_message="ابتدا فالو کنید"))
                db.add(Keyword(keyword="7", response="دایرکت", comment_reply="ریپلای", active=True))
                db.commit()
                service = ZernioService()
                service.api_key = "test-key"
                service.account_id = "test-account"
                service.profile_id = "test-profile"
                with patch.object(service, "list_comment_automations", return_value=[]), \
                     patch.object(service, "create_comment_automation", return_value={"id": "a"}) as create, \
                     patch("time.sleep"):
                    service.sync_all_keywords(db)
                self.assertEqual(create.call_args.kwargs["follow_gate_message"], "ابتدا فالو کنید")
        finally:
            engine.dispose()

    def test_existing_keyword_without_public_reply_keeps_exact_match(self):
        service = ZernioService()
        service.api_key = "test-key"
        service.account_id = "test-account"
        service.profile_id = "test-profile"
        response = SimpleNamespace(status_code=201, json=lambda: {"id": "test-automation"})
        with patch("app.service.zernio_service.requests.post", return_value=response) as post:
            service.create_comment_automation(name="KW_2_price", keywords=["price"], dm_message="DM")
        payload = post.call_args.kwargs["json"]
        self.assertEqual(payload["matchMode"], "exact")
        self.assertNotIn("commentReply", payload)
        self.assertTrue(payload["alsoMatchInDms"])


if __name__ == "__main__":
    unittest.main()
