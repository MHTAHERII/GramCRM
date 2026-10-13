#!/usr/bin/env python3
"""
ممیزی امنیتی GramCRM — بدون نمایش هیچ مقدار محرمانه‌ای.

روی سرور (یا لوکال) اجرا کنید:
    python scripts/security_audit.py
    python scripts/security_audit.py --env /path/to/.env

وضعیت هر متغیر را ✅ / ⚠️ / ❌ چاپ می‌کند و فقط در صورت وجود مشکلِ حیاتی
کد خروج ۱ برمی‌گرداند (مناسب برای CI).
"""
import argparse
import os
import re
import sys

DEFAULT_SESSION_SECRET = "perfume-panel-secret-change-me"
DEFAULT_PASSWORD = "admin123"

OK, WARN, FAIL = "✅", "⚠️", "❌"


def load_env(path: str | None) -> dict:
    """خواندن .env (مقدارها هرگز چاپ نمی‌شوند؛ فقط همین‌جا نگه داشته می‌شوند)."""
    values: dict = {}
    candidates = [path] if path else [
        os.path.join(os.getcwd(), ".env"),
        os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"),
    ]
    for candidate in candidates:
        if candidate and os.path.isfile(candidate):
            with open(candidate, "r", encoding="utf-8", errors="replace") as fh:
                for line in fh:
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    key, _, val = line.partition("=")
                    values[key.strip()] = val.strip().strip('"').strip("'")
            break
    return values


def get(env: dict, key: str) -> str:
    """اولویت با متغیر محیطی سیستم، سپس فایل .env (مثل خود اپ)."""
    return os.environ.get(key) or env.get(key, "")


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    parser = argparse.ArgumentParser(description="GramCRM security audit")
    parser.add_argument("--env", help="مسیر فایل .env")
    args = parser.parse_args()

    env = load_env(args.env)
    if not env and not any(
        os.environ.get(k) for k in ("ADMIN_PASSWORD", "ADMIN_SESSION_SECRET", "SESSION_HTTPS_ONLY")
    ):
        print("⚠️  فایل .env پیدا نشد؛ فقط متغیرهای محیطی سیستم بررسی می‌شوند.")

    results: list[tuple[str, str, str]] = []  # (عنوان, وضعیت, راهنمای اقدام)
    critical = 0

    # ۱) رمز پنل
    pw = get(env, "ADMIN_PASSWORD")
    if pw == DEFAULT_PASSWORD:
        results.append(("ADMIN_PASSWORD", FAIL,
                        "هنوز admin123 است! رمز قوی بگذارید (همون رمزی که در پنل گذاشته‌اید)."))
        critical += 1
    elif not pw:
        results.append(("ADMIN_PASSWORD", WARN, "در env خالی است؛ رمز دیتابیس مبناست (فالبک ندارد)."))
    elif len(pw) < 8:
        results.append(("ADMIN_PASSWORD", WARN, "کوتاه است؛ حداقل ۸ کاراکتر توصیه می‌شود."))
    else:
        results.append(("ADMIN_PASSWORD", OK, f"سفارشی (طول {len(pw)})."))

    # ۲) کلید امضای سشن
    secret = get(env, "ADMIN_SESSION_SECRET")
    if secret == DEFAULT_SESSION_SECRET or not secret:
        results.append(("ADMIN_SESSION_SECRET", FAIL,
                        "پیش‌فرض/خالی است؛ کوکی سشن قابل جعله. تولید کنید: "
                        "[guid]::NewGuid().ToString('N') + [guid]::NewGuid().ToString('N')"))
        critical += 1
    elif len(secret) < 32:
        results.append(("ADMIN_SESSION_SECRET", WARN, f"سفارشی ولی کوتاه (طول {len(secret)})."))
    else:
        results.append(("ADMIN_SESSION_SECRET", OK, f"سفارشی و قوی (طول {len(secret)})."))

    # ۳) فقط HTTPS برای کوکی سشن
    https = get(env, "SESSION_HTTPS_ONLY").lower()
    if https in ("true", "1", "yes"):
        results.append(("SESSION_HTTPS_ONLY", OK, "فعال."))
    else:
        results.append(("SESSION_HTTPS_ONLY", WARN,
                        "غیرفعال؛ روی سرور عملیاتی SESSION_HTTPS_ONLY=true بگذارید و ری‌استارت کنید."))

    # ۴) توکن وب‌هوک زرنیو
    hook = get(env, "ZERNIO_WEBHOOK_SECRET")
    if hook:
        results.append(("ZERNIO_WEBHOOK_SECRET", OK,
                        f"تنظیم (طول {len(hook)}) — آدرس وب‌هوک باید ?token= داشته باشد."))
    else:
        results.append(("ZERNIO_WEBHOOK_SECRET", WARN,
                        "خالی؛ وب‌هوک بدون توکن پذیرفته می‌شود. تولید: python -c \"import secrets;print(secrets.token_hex(32))\""))

    # ۵) امضای وب‌هوک متا
    meta = get(env, "META_APP_SECRET")
    if meta:
        results.append(("META_APP_SECRET", OK, "تنظیم؛ امضای متا بررسی می‌شود."))
    else:
        results.append(("META_APP_SECRET", WARN,
                        "خالی؛ فقط اگر از وب‌هوک متا استفاده می‌کنید لازم است (از Meta App Dashboard)."))

    # ۶) مستندات OpenAPI
    docs = get(env, "ENABLE_DOCS").lower()
    if docs in ("true", "1", "yes"):
        results.append(("ENABLE_DOCS", WARN, "فعال است؛ در سرور اصلی غیرفعالش کنید."))
    else:
        results.append(("ENABLE_DOCS", OK, "غیرفعال (پیش‌فرض امن)."))

    # ۷) کلید زرنیو (فقط وضعیت، بدون مقدار)
    zkey = get(env, "ZERNIO_API_KEY")
    if zkey:
        fmt = "فرمت sk_ ✓" if zkey.startswith("sk_") else "فرمت نامتعارف!"
        results.append(("ZERNIO_API_KEY", OK if zkey.startswith("sk_") else WARN,
                        f"تنظیم (طول {len(zkey)}) — {fmt}"))
    else:
        results.append(("ZERNIO_API_KEY", WARN, "خالی؛ پنل به اینستاگرام وصل نیست."))

    # چاپ گزارش
    print("\n=== گزارش ممیزی امنیتی GramCRM ===")
    for title, status, note in results:
        print(f"  {status} {title:<24} {note}")
    print("==================================")
    if critical:
        print(f"\n{critical} مشکل حیاتی! فوراً رفع شود.")
    else:
        print("\nمشکل حیاتی یافت نشد.")
    return 1 if critical else 0


if __name__ == "__main__":
    sys.exit(main())
