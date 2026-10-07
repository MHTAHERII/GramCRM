import unittest
from unittest.mock import patch, MagicMock
from app.config import Settings
from app.service.postzen_service import PostZenService
from app.service.automation_service import AutomationService


class PostZenServiceTests(unittest.TestCase):
    def setUp(self):
        self.service = PostZenService()
        self.service.api_key = "test_key"
        self.service.account_id = "test_acc"

    def test_is_configured(self):
        self.assertTrue(self.service.is_configured())
        self.service.api_key = ""
        self.assertFalse(self.service.is_configured())

    @patch("requests.Session.get")
    def test_discover_account(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "accounts": [
                {"_id": "acc_123", "platform": "instagram", "isActive": True}
            ]
        }
        mock_get.return_value = mock_resp

        acc_id = self.service.discover_account(api_key="valid_key")
        self.assertEqual(acc_id, "acc_123")
        self.assertEqual(self.service.account_id, "acc_123")

    @patch("requests.Session.post")
    def test_create_comment_automation(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 201
        mock_resp.json.return_value = {
            "automation": {"id": "pzn_auto_1", "name": "KW_1_تست"}
        }
        mock_post.return_value = mock_resp

        res = self.service.create_comment_automation(
            name="KW_1_تست",
            keywords=["تست"],
            dm_message="سلام",
            comment_reply="پاسخ کامنت",
            comment_reply_delay_seconds=10,
            dm_delay_seconds=5,
            comment_reply_variations=["پاسخ ۱", "پاسخ ۲"],
            dm_message_variations=["دایرکت ۱", "دایرکت ۲"],
            platform_post_id="post_999"
        )
        self.assertIsNotNone(res)
        self.assertEqual(res["automation"]["id"], "pzn_auto_1")

        args, kwargs = mock_post.call_args
        payload = kwargs["json"]
        self.assertEqual(payload["accountId"], "test_acc")
        self.assertEqual(payload["name"], "KW_1_تست")
        self.assertEqual(payload["commentReplyDelaySeconds"], 10)
        self.assertEqual(payload["dmDelaySeconds"], 5)
        self.assertEqual(payload["commentReplyVariations"], ["پاسخ ۱", "پاسخ ۲"])
        self.assertEqual(payload["dmMessageVariations"], ["دایرکت ۱", "دایرکت ۲"])
        self.assertEqual(payload["platformPostId"], "post_999")

    @patch("requests.Session.patch")
    def test_set_active_status(self, mock_patch):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_patch.return_value = mock_resp

        self.assertTrue(self.service.set_comment_automation_active("auto_1", False))
        args, kwargs = mock_patch.call_args
        self.assertEqual(kwargs["json"], {"isActive": False})

    @patch("requests.Session.delete")
    def test_delete_comment_automation(self, mock_delete):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_delete.return_value = mock_resp

        self.assertTrue(self.service.delete_comment_automation("auto_1"))


class AutomationServiceSwitchTests(unittest.TestCase):
    def test_provider_switch(self):
        auto_svc = AutomationService()
        with patch("app.service.automation_service.settings.AUTOMATION_PROVIDER", "postzen"):
            self.assertEqual(auto_svc.provider, "postzen")
            self.assertEqual(auto_svc.active_service.__class__.__name__, "PostZenService")

        with patch("app.service.automation_service.settings.AUTOMATION_PROVIDER", "zernio"):
            self.assertEqual(auto_svc.provider, "zernio")
            self.assertEqual(auto_svc.active_service.__class__.__name__, "ZernioService")


if __name__ == "__main__":
    unittest.main()
