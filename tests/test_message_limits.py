import unittest
from unittest.mock import patch, MagicMock

from pydantic import ValidationError
from app.schemas.keyword import KeywordCreate, KeywordUpdate
from app.schemas.customer import ManualSendRequest
from app.schemas.bot_setting import BotSettingUpdate
from app.service.product_response import render_product_response
from app.service.zernio_service import ZernioService


class MessageLimitTests(unittest.TestCase):
    def test_keyword_response_cannot_exceed_640_chars(self):
        long_text = "ا" * 641
        with self.assertRaises(ValidationError):
            KeywordCreate(keyword="test", response=long_text)

        valid_text = "ا" * 640
        kw = KeywordCreate(keyword="test", response=valid_text)
        self.assertEqual(len(kw.response), 640)

    def test_keyword_update_cannot_exceed_640_chars(self):
        long_text = "ب" * 641
        with self.assertRaises(ValidationError):
            KeywordUpdate(response=long_text)

    def test_manual_send_request_cannot_exceed_640_chars(self):
        long_text = "پ" * 641
        with self.assertRaises(ValidationError):
            ManualSendRequest(text=long_text)

        valid_text = "پ" * 640
        req = ManualSendRequest(text=valid_text)
        self.assertEqual(len(req.text), 640)

    def test_bot_setting_messages_cannot_exceed_640_chars(self):
        long_text = "ت" * 641
        with self.assertRaises(ValidationError):
            BotSettingUpdate(follow_gate_message=long_text)

    def test_render_product_response_caps_at_640_chars(self):
        template = "توضیحات: {description}"
        mock_product = MagicMock(name="عطر", price=1000, stock=5, unit="عدد", description="خ" * 700)
        rendered = render_product_response(template, mock_product)
        self.assertLessEqual(len(rendered), 640)

    def test_zernio_service_trims_dm_message_to_640_chars(self):
        service = ZernioService()
        service.api_key = "key"
        service.account_id = "account"
        service.profile_id = "profile"

        mock_resp = MagicMock(status_code=201, json=lambda: {"id": "auto-1"})
        with patch("app.service.zernio_service.requests.post", return_value=mock_resp) as mock_post:
            service.create_comment_automation(
                name="KW_test",
                keywords=["test"],
                dm_message="د" * 700,
                follow_gate_message="ف" * 700
            )

        payload = mock_post.call_args.kwargs["json"]
        self.assertEqual(len(payload["dmMessage"]), 640)
        self.assertEqual(len(payload["followGate"]["message"]), 640)


if __name__ == "__main__":
    unittest.main()
