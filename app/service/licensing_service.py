import base64
import hashlib
import hmac
import json
import logging
import secrets
import time
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.config import settings
from app.models.bot_setting import BotSetting

logger = logging.getLogger("licensing_service")

PREFIX = "GCRM-v1"


def _b64encode_str(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("utf-8").rstrip("=")


def _b64decode_str(s: str) -> bytes:
    padding = 4 - (len(s) % 4)
    if padding and padding != 4:
        s += "=" * padding
    return base64.urlsafe_b64decode(s.encode("utf-8"))


def generate_license(
    licensee: str,
    tier: str = "pro",
    valid_days: int = 365,
    features: list[str] | None = None,
    secret_key: str | None = None,
) -> str:
    """
    تولید کلید لایسنس دیجیتال امضا شده با HMAC-SHA256.
    در صورتی که valid_days=0 باشد، لایسنس مادام‌العمر (Lifetime) محسوب می‌شود.
    """
    secret = (secret_key or settings.LICENSE_SECRET_KEY).encode("utf-8")
    now_ts = int(time.time())
    expires_ts = 0 if valid_days == 0 else now_ts + (valid_days * 86400)

    payload: dict[str, Any] = {
        "v": 1,
        "licensee": licensee.strip(),
        "tier": tier.strip().lower(),
        "issued_at": now_ts,
        "expires_at": expires_ts,
        "features": features or ["core", "auto_comment", "ai_reply", "analytics", "bulk_message"],
        "nonce": secrets.token_hex(8),
    }

    payload_json = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    payload_b64 = _b64encode_str(payload_json)

    signature = hmac.new(secret, payload_b64.encode("utf-8"), hashlib.sha256).digest()
    sig_b64 = _b64encode_str(signature)

    return f"{PREFIX}.{payload_b64}.{sig_b64}"


def validate_license(license_key: str | None, secret_key: str | None = None) -> dict[str, Any]:
    """
    اعتبارسنجی امضای دیجیتال و تاریخ انقضای لایسنس.
    از مقایسه زمان‌ثابت (constant-time) جهت جلوگیری از Timing Attacks استفاده می‌کند.
    """
    if not license_key or not license_key.strip():
        return {
            "is_valid": False,
            "status": "missing",
            "licensee": None,
            "tier": None,
            "issued_at": None,
            "expires_at": None,
            "days_remaining": 0,
            "features": [],
            "message": "لایسنس نرم‌افزار فعال نشده است.",
        }

    raw_key = license_key.strip()
    parts = raw_key.split(".")
    if len(parts) != 3 or parts[0] != PREFIX:
        return {
            "is_valid": False,
            "status": "malformed",
            "licensee": None,
            "tier": None,
            "issued_at": None,
            "expires_at": None,
            "days_remaining": 0,
            "features": [],
            "message": "فرمت کلید لایسنس نامعتبر است.",
        }

    _, payload_b64, received_sig_b64 = parts
    secret = (secret_key or settings.LICENSE_SECRET_KEY).encode("utf-8")

    expected_sig = hmac.new(secret, payload_b64.encode("utf-8"), hashlib.sha256).digest()
    expected_sig_b64 = _b64encode_str(expected_sig)

    # مقایسه ایمن بر اساس زمان‌ثابت
    if not hmac.compare_digest(expected_sig_b64, received_sig_b64):
        logger.warning("Digital license signature mismatch. Possible tampering.")
        return {
            "is_valid": False,
            "status": "invalid_signature",
            "licensee": None,
            "tier": None,
            "issued_at": None,
            "expires_at": None,
            "days_remaining": 0,
            "features": [],
            "message": "امضای دیجیتال لایسنس نامعتبر است یا کلید دستکاری شده است.",
        }

    try:
        payload_bytes = _b64decode_str(payload_b64)
        payload = json.loads(payload_bytes.decode("utf-8"))
    except Exception as e:
        logger.error(f"Failed to decode license payload: {e}")
        return {
            "is_valid": False,
            "status": "malformed",
            "licensee": None,
            "tier": None,
            "issued_at": None,
            "expires_at": None,
            "days_remaining": 0,
            "features": [],
            "message": "محتوای لایسنس قابل بازخوانی نیست.",
        }

    now_ts = int(time.time())
    expires_at_ts = payload.get("expires_at", 0)
    issued_at_ts = payload.get("issued_at", now_ts)

    issued_at_str = datetime.fromtimestamp(issued_at_ts, tz=timezone.utc).isoformat()
    expires_at_str = (
        "lifetime"
        if expires_at_ts == 0
        else datetime.fromtimestamp(expires_at_ts, tz=timezone.utc).isoformat()
    )

    days_remaining = None
    if expires_at_ts > 0:
        sec_left = expires_at_ts - now_ts
        if sec_left < 0:
            return {
                "is_valid": False,
                "status": "expired",
                "licensee": payload.get("licensee"),
                "tier": payload.get("tier"),
                "issued_at": issued_at_str,
                "expires_at": expires_at_str,
                "days_remaining": 0,
                "features": payload.get("features", []),
                "message": "اعتبار لایسنس به پایان رسیده است.",
            }
        days_remaining = max(1, sec_left // 86400)

    return {
        "is_valid": True,
        "status": "active",
        "licensee": payload.get("licensee"),
        "tier": payload.get("tier"),
        "issued_at": issued_at_str,
        "expires_at": expires_at_str,
        "days_remaining": days_remaining,
        "features": payload.get("features", []),
        "message": "لایسنس معتبر و فعال است.",
    }


def get_active_license(db: Session) -> dict[str, Any]:
    """دریافت و اعتبارسنجی لایسنس فعلی ذخیره شده در سیستم"""
    setting = db.query(BotSetting).filter(BotSetting.id == 1).first()
    key = setting.license_key if setting else None
    return validate_license(key)


def has_feature(feature_name: str, db: Session) -> bool:
    """بررسی مجاز بودن یک فیچر بر اساس لایسنس فعال"""
    lic = get_active_license(db)
    if not lic.get("is_valid"):
        return False
    features = lic.get("features", [])
    if "*" in features or lic.get("tier") == "enterprise":
        return True
    return feature_name in features


def activate_license_key(key: str, db: Session) -> dict[str, Any]:
    """فعال‌سازی و ذخیره کلید لایسنس در دیتابیس"""
    res = validate_license(key)
    if not res.get("is_valid"):
        return res

    setting = db.query(BotSetting).filter(BotSetting.id == 1).first()
    if not setting:
        setting = BotSetting(id=1, fallback_message="درود، به زودی پاسخگوی شما هستیم.")
        db.add(setting)

    setting.license_key = key.strip()
    db.commit()
    db.refresh(setting)
    return res
