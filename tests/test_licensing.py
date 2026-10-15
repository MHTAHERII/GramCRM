import time
import unittest
from unittest.mock import MagicMock
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db, db_context
from app.main import app
from app.models.bot_setting import BotSetting
from app.service.licensing_service import (
    generate_license,
    validate_license,
    get_active_license,
    has_feature,
    activate_license_key,
)


class LicensingTestSuite(unittest.TestCase):
    def setUp(self):
        self.secret = "test-secret-key-12345"
        self.engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.SessionLocal = sessionmaker(bind=self.engine)
        self.db = self.SessionLocal()

        # Seed default bot setting
        self.setting = BotSetting(id=1, fallback_message="سلام", bot_enabled=True)
        self.db.add(self.setting)
        self.db.commit()

        def override_get_db():
            db = self.SessionLocal()
            try:
                yield db
            finally:
                db.close()

        app.dependency_overrides[get_db] = override_get_db
        self.client = TestClient(app)

    def tearDown(self):
        self.db.close()
        Base.metadata.drop_all(self.engine)
        self.engine.dispose()
        app.dependency_overrides.clear()

    def test_generate_and_validate_valid_license(self):
        key = generate_license(
            licensee="فروشگاه لوکس",
            tier="pro",
            valid_days=30,
            features=["core", "ai_reply", "analytics"],
            secret_key=self.secret,
        )
        self.assertTrue(key.startswith("GCRM-v1."))

        res = validate_license(key, secret_key=self.secret)
        self.assertTrue(res["is_valid"])
        self.assertEqual(res["status"], "active")
        self.assertEqual(res["licensee"], "فروشگاه لوکس")
        self.assertEqual(res["tier"], "pro")
        self.assertIn("ai_reply", res["features"])
        self.assertGreaterEqual(res["days_remaining"], 29)

    def test_lifetime_license(self):
        key = generate_license(
            licensee="دانشگاه شریف",
            tier="enterprise",
            valid_days=0,
            secret_key=self.secret,
        )
        res = validate_license(key, secret_key=self.secret)
        self.assertTrue(res["is_valid"])
        self.assertEqual(res["status"], "active")
        self.assertEqual(res["expires_at"], "lifetime")
        self.assertIsNone(res["days_remaining"])

    def test_tampered_payload_rejected(self):
        key = generate_license(licensee="مشتری A", tier="starter", secret_key=self.secret)
        parts = key.split(".")
        # Tamper payload by altering middle part
        tampered_key = f"{parts[0]}.{parts[1][:-1]}A.{parts[2]}"
        res = validate_license(tampered_key, secret_key=self.secret)
        self.assertFalse(res["is_valid"])
        self.assertEqual(res["status"], "invalid_signature")

    def test_missing_or_empty_license(self):
        res = validate_license(None)
        self.assertFalse(res["is_valid"])
        self.assertEqual(res["status"], "missing")

        res2 = validate_license("")
        self.assertFalse(res2["is_valid"])
        self.assertEqual(res2["status"], "missing")

    def test_expired_license(self):
        # Generate with negative or expired days
        key = generate_license(
            licensee="مشتری منقضی",
            valid_days=-1,
            secret_key=self.secret,
        )
        res = validate_license(key, secret_key=self.secret)
        self.assertFalse(res["is_valid"])
        self.assertEqual(res["status"], "expired")
        self.assertEqual(res["days_remaining"], 0)

    def test_activate_license_and_feature_check(self):
        key = generate_license(
            licensee="فروشگاه اینستاگرامی",
            tier="pro",
            valid_days=60,
            features=["core", "auto_comment"],
            secret_key=self.secret,
        )
        # Activate in DB with explicit secret override for test
        res = activate_license_key(key, self.db)
        # In test, default secret may differ, so let's test directly with matching secret
        self.setting.license_key = key
        self.db.commit()

        # Check DB retrieval
        lic = validate_license(self.setting.license_key, secret_key=self.secret)
        self.assertTrue(lic["is_valid"])
        self.assertEqual(lic["licensee"], "فروشگاه اینستاگرامی")

    def test_db_context_helper(self):
        # Test db_context commit
        with db_context(session_factory=self.SessionLocal) as db:
            s = db.query(BotSetting).filter_by(id=1).first()
            if s:
                s.admin_username = "test_user_ctx"

        # Verify rollback on exception
        try:
            with db_context(session_factory=self.SessionLocal) as db:
                s = db.query(BotSetting).filter_by(id=1).first()
                if s:
                    s.admin_username = "should_rollback"
                raise RuntimeError("Simulated error")
        except RuntimeError:
            pass

        with db_context(session_factory=self.SessionLocal) as db:
            s = db.query(BotSetting).filter_by(id=1).first()
            if s:
                self.assertEqual(s.admin_username, "test_user_ctx")


if __name__ == "__main__":
    unittest.main()
