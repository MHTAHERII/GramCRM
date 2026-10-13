import unittest
from types import SimpleNamespace

from app.main import security_warnings


def _cfg(**overrides):
    """تنظیمات امن پیش‌فرض؛ هر مورد با overrides قابل تغییر است."""
    base = dict(
        ADMIN_SESSION_SECRET="custom-long-random-session-secret-value-123",
        ADMIN_PASSWORD="Str0ng-Panel-Pass!",
        ZERNIO_WEBHOOK_SECRET="hook-token-abc",
        SESSION_HTTPS_ONLY=True,
        ENABLE_DOCS=False,
        META_APP_SECRET="meta-secret-xyz",
    )
    base.update(overrides)
    return SimpleNamespace(**base)


class SecurityPostureWarningsTests(unittest.TestCase):
    def test_secure_config_has_no_warnings(self):
        self.assertEqual(security_warnings(_cfg()), [])

    def test_default_session_secret_warned(self):
        items = security_warnings(_cfg(ADMIN_SESSION_SECRET="perfume-panel-secret-change-me"))
        self.assertTrue(any("ADMIN_SESSION_SECRET" in w for w in items))

    def test_default_password_warned(self):
        items = security_warnings(_cfg(ADMIN_PASSWORD="admin123"))
        self.assertTrue(any("ADMIN_PASSWORD" in w for w in items))

    def test_missing_webhook_secret_warned(self):
        items = security_warnings(_cfg(ZERNIO_WEBHOOK_SECRET=""))
        self.assertTrue(any("ZERNIO_WEBHOOK_SECRET" in w for w in items))

    def test_https_only_off_warned(self):
        items = security_warnings(_cfg(SESSION_HTTPS_ONLY=False))
        self.assertTrue(any("SESSION_HTTPS_ONLY" in w for w in items))

    def test_docs_enabled_warned(self):
        items = security_warnings(_cfg(ENABLE_DOCS=True))
        self.assertTrue(any("ENABLE_DOCS" in w for w in items))

    def test_missing_meta_secret_warned(self):
        items = security_warnings(_cfg(META_APP_SECRET=""))
        self.assertTrue(any("META_APP_SECRET" in w for w in items))

    def test_warnings_never_contain_secret_values(self):
        """هیچ مقدار محرمانه‌ای نباید در متن هشدارها بیاید."""
        marker = "DoNotLeak-XYZ-98765"
        items = security_warnings(
            _cfg(
                ADMIN_SESSION_SECRET=marker,
                ZERNIO_WEBHOOK_SECRET="",
                SESSION_HTTPS_ONLY=False,
            )
        )
        for w in items:
            self.assertNotIn(marker, w)


if __name__ == "__main__":
    unittest.main()
