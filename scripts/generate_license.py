"""
اسکریپت صدور لایسنس دیجیتال برای نرم‌افزار GramCRM
استفاده:
    python scripts/generate_license.py --licensee "فروشگاه عطر لوکس" --tier enterprise --days 365
    python scripts/generate_license.py --licensee "مشتری دائمی" --tier pro --days 0  # مادام‌العمر
"""

import argparse
import sys
from pathlib import Path

# Add project root to path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

from app.service.licensing_service import generate_license, validate_license


def main():
    parser = argparse.ArgumentParser(description="صدور لایسنس دیجیتال GramCRM")
    parser.add_argument("--licensee", "-l", required=True, help="نام خریدار، شخص یا فروشگاه")
    parser.add_argument(
        "--tier", "-t", default="pro", choices=["starter", "pro", "enterprise"],
        help="پلن لایسنس (starter / pro / enterprise)"
    )
    parser.add_argument(
        "--days", "-d", type=int, default=365,
        help="تعداد روزهای اعتبار (۰ یعنی مادام‌العمر / Lifetime)"
    )
    parser.add_argument(
        "--features", "-f", default=None,
        help="فیچرهای مجاز با کاما جدا شوند (پیش‌فرض: همه فیچرهای اصلی)"
    )
    parser.add_argument(
        "--secret", "-s", default=None,
        help="کلید اختصاصی امضا (در صورت خالی بودن از تنظیمات .env خوانده می‌شود)"
    )

    args = parser.parse_args()

    features_list = None
    if args.features:
        features_list = [f.strip() for f in args.features.split(",") if f.strip()]

    license_key = generate_license(
        licensee=args.licensee,
        tier=args.tier,
        valid_days=args.days,
        features=features_list,
        secret_key=args.secret,
    )

    validation = validate_license(license_key, secret_key=args.secret)

    print("\n" + "=" * 60)
    print("🔑 لایسنس دیجیتال GramCRM با موفقیت صادر شد:")
    print("=" * 60)
    print(f"👤 نام خریدار:    {validation['licensee']}")
    print(f"💎 سطح دسترسی:    {validation['tier']}")
    print(f"📅 تاریخ صدور:    {validation['issued_at']}")
    print(f"⏳ تاریخ انقضا:    {validation['expires_at']} ({'مادام‌العمر' if args.days <= 0 else f'{args.days} روز'})")
    print(f"✨ فیچرهای فعال:  {', '.join(validation['features'])}")
    print("-" * 60)
    print("📜 کلید لایسنس (جهت ارسال به خریدار):")
    print(f"\n{license_key}\n")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    main()
