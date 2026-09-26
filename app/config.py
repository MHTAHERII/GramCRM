import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(dotenv_path=BASE_DIR / '.env', override=True)
class Settings:
    # Railway uses "postgres://" but SQLAlchemy requires "postgresql://"
    _raw_db_url: str = os.getenv(
        "DATABASE_URL",
        "postgresql://postgres:73752@localhost:5432/perfume_bot"
    )
    DATABASE_URL: str = _raw_db_url.replace("postgres://", "postgresql://", 1) if _raw_db_url.startswith("postgres://") else _raw_db_url
    IG_USERNAME: str = os.getenv("IG_USERNAME", "")
    IG_PASSWORD: str = os.getenv("IG_PASSWORD", "")
    IG_SESSION_FILE: str = str(BASE_DIR / os.getenv("IG_SESSION_FILE", "session.json"))
    IG_PROXY: str = os.getenv("IG_PROXY", "")
    IG_POLL_INTERVAL: int = int(os.getenv("IG_POLL_INTERVAL", "15"))
    ENABLE_IG_WORKER: bool = os.getenv("ENABLE_IG_WORKER", "true").lower() in ("true", "1", "yes")
    ADMIN_PASSWORD: str = os.getenv("ADMIN_PASSWORD", "admin123")
    ADMIN_SESSION_SECRET: str = os.getenv("ADMIN_SESSION_SECRET", "perfume-panel-secret-change-me")

    # تنظیمات Meta Webhook و Graph API
    META_ACCESS_TOKEN: str = os.getenv("META_ACCESS_TOKEN", "")
    META_VERIFY_TOKEN: str = os.getenv("META_VERIFY_TOKEN", "perfume_bot_verify_token_2026")
    META_API_VERSION: str = os.getenv("META_API_VERSION", "v21.0")

    # تنظیمات پلتفرم Zernio (برای کامنت به دایرکت خودکار و اتوماسیون اینستاگرام)
    ZERNIO_API_KEY: str = os.getenv("ZERNIO_API_KEY", "")
    ZERNIO_PROFILE_ID: str = os.getenv("ZERNIO_PROFILE_ID", "")
    ZERNIO_ACCOUNT_ID: str = os.getenv("ZERNIO_ACCOUNT_ID", "")
settings = Settings()
