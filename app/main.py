import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import RedirectResponse, FileResponse
from sqlalchemy import text, inspect
from starlette.middleware.sessions import SessionMiddleware

from app.database import engine, Base, SessionLocal
from app.models.bot_setting import BotSetting
from app.routers.product import router as product_router
from app.routers.order import router as order_router
from app.routers.customer import router as customer_router
from app.routers.message import router as message_router, conversations_router
from app.routers.keyword import router as keyword_router
from app.routers.settings import router as settings_router
from app.routers.webhook import router as webhook_router
from app.routers.zernio_webhook import router as zernio_webhook_router
from app.routers.system import router as system_router
from app.routers.websocket import router as websocket_router
from app.service.ws_manager import ws_manager
from app.service.system_service import setup_logging
from app.auth import router as auth_router
from app.config import settings

setup_logging()
logger = logging.getLogger("main")

PANEL_DIR = Path(__file__).resolve().parent / "static" / "panel"


def security_warnings(cfg=None) -> list[str]:
    """
    بررسی وضعیت امنیتی env هنگام استارت و بازگرداندن فهرست هشدارها.
    هیچ مقدار محرمانه‌ای در متن هشدارها قرار نمی‌گیرد (فقط وضعیت).
    """
    cfg = cfg or settings
    warnings: list[str] = []
    if cfg.ADMIN_SESSION_SECRET == "perfume-panel-secret-change-me":
        warnings.append(
            "ADMIN_SESSION_SECRET پیش‌فرض فعال است؛ هرکسی می‌تواند کوکی سشن جعل کند. "
            "فوراً یک مقدار تصادفی طولانی در .env قرار دهید."
        )
    if cfg.ADMIN_PASSWORD == "admin123":
        warnings.append(
            "ADMIN_PASSWORD پیش‌فرض (admin123) فعال است؛ این مقدار در گیت عمومیه. "
            "در .env سرور یک رمز قوی بگذارید."
        )
    if not cfg.ZERNIO_WEBHOOK_SECRET:
        warnings.append(
            "ZERNIO_WEBHOOK_SECRET خالی است؛ هرکسی می‌تواند رویداد جعلی برای وب‌هوک زرنیو بفرستد. "
            "یک مقدار تصادفی بسازید و آدرس وب‌هوک را با ?token= مقدار را تنظیم کنید."
        )
    if not cfg.SESSION_HTTPS_ONLY:
        warnings.append(
            "SESSION_HTTPS_ONLY=true نشده؛ کوکی سشن بدون پرچم Secure ارسال می‌شود. "
            "روی سرور عملیاتی حتماً true کنید."
        )
    if cfg.ENABLE_DOCS:
        warnings.append(
            "ENABLE_DOCS فعال است؛ مستندات OpenAPI در محیط عملیاتی باید غیرفعال باشد."
        )
    if not cfg.META_APP_SECRET:
        warnings.append(
            "META_APP_SECRET خالی است؛ امضای وب‌هوک متا (X-Hub-Signature-256) تأیید نمی‌شود."
        )
    return warnings


def run_schema_migrations() -> None:
    """
    تغییرات اسکیمایی که create_all روی جدول‌های موجود اعمال نمی‌کند.
    هر دستور idempotent است و اگر قبلاً اجرا شده باشد خطایی نمی‌دهد.
    """
    additions = {
        "products": {"unit": "VARCHAR(30) NOT NULL DEFAULT 'عدد'"},
        "customers": {"bot_paused": "BOOLEAN NOT NULL DEFAULT FALSE"},
        "keywords": {
            "product_id": "INTEGER REFERENCES products(id)",
            "comment_reply_delay_seconds": "INTEGER DEFAULT 0",
            "dm_delay_seconds": "INTEGER DEFAULT 0",
            "comment_reply_variations": "JSON",
            "dm_message_variations": "JSON",
            "platform_post_id": "VARCHAR(100)",
        },
        "bot_settings": {
            "automation_provider": "VARCHAR(50) DEFAULT 'zernio'",
            "postzen_api_key": "VARCHAR(255)",
            "postzen_account_id": "VARCHAR(100)",
        },
    }

    with engine.begin() as conn:
        for table_name, columns in additions.items():
            existing = {column["name"] for column in inspect(conn).get_columns(table_name)}
            for column_name, definition in columns.items():
                if column_name not in existing:
                    conn.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {definition}"))
    if engine.dialect.name == "postgresql":
        with engine.begin() as conn:
            conn.execute(text(
                "ALTER TABLE messages ALTER COLUMN instagram_message_id DROP NOT NULL;"
            ))
            conn.execute(text(
                "ALTER TABLE messages ALTER COLUMN instagram_message_id TYPE VARCHAR(255);"
            ))
            conn.execute(text(
                "ALTER TABLE bot_settings ADD COLUMN IF NOT EXISTS follow_gate_enabled BOOLEAN NOT NULL DEFAULT FALSE;"
            ))
            conn.execute(text(
                "ALTER TABLE bot_settings ADD COLUMN IF NOT EXISTS follow_gate_message TEXT;"
            ))
            conn.execute(text(
                "ALTER TABLE bot_settings ADD COLUMN IF NOT EXISTS comment_reply_enabled BOOLEAN NOT NULL DEFAULT TRUE;"
            ))
            conn.execute(text(
                "ALTER TABLE bot_settings ADD COLUMN IF NOT EXISTS comment_public_reply_enabled BOOLEAN NOT NULL DEFAULT FALSE;"
            ))
            conn.execute(text(
                "ALTER TABLE bot_settings ADD COLUMN IF NOT EXISTS comment_public_reply_text TEXT;"
            ))
            conn.execute(text(
                "ALTER TABLE bot_settings ADD COLUMN IF NOT EXISTS follow_gate_button_title VARCHAR(100);"
            ))
            conn.execute(text(
                "ALTER TABLE bot_settings ADD COLUMN IF NOT EXISTS follow_gate_button_url VARCHAR(500);"
            ))
            conn.execute(text(
                "ALTER TABLE bot_settings ADD COLUMN IF NOT EXISTS follow_gate_buttons JSON;"
            ))
            conn.execute(text(
                "ALTER TABLE keywords ADD COLUMN IF NOT EXISTS button_title VARCHAR(100);"
            ))
            conn.execute(text(
                "ALTER TABLE keywords ADD COLUMN IF NOT EXISTS button_url VARCHAR(500);"
            ))
            conn.execute(text(
                "ALTER TABLE keywords ADD COLUMN IF NOT EXISTS buttons JSON;"
            ))
            conn.execute(text(
                "ALTER TABLE keywords ADD COLUMN IF NOT EXISTS comment_reply TEXT;"
            ))
            conn.execute(text(
                "ALTER TABLE keywords ADD COLUMN IF NOT EXISTS comment_reply_delay_seconds INTEGER DEFAULT 0;"
            ))
            conn.execute(text(
                "ALTER TABLE keywords ADD COLUMN IF NOT EXISTS dm_delay_seconds INTEGER DEFAULT 0;"
            ))
            conn.execute(text(
                "ALTER TABLE keywords ADD COLUMN IF NOT EXISTS comment_reply_variations JSON;"
            ))
            conn.execute(text(
                "ALTER TABLE keywords ADD COLUMN IF NOT EXISTS dm_message_variations JSON;"
            ))
            conn.execute(text(
                "ALTER TABLE keywords ADD COLUMN IF NOT EXISTS platform_post_id VARCHAR(100);"
            ))
            conn.execute(text(
                "ALTER TABLE bot_settings ADD COLUMN IF NOT EXISTS admin_username VARCHAR(100) DEFAULT 'admin';"
            ))
            conn.execute(text(
                "ALTER TABLE bot_settings ADD COLUMN IF NOT EXISTS admin_password VARCHAR(100);"
            ))
            conn.execute(text(
                "ALTER TABLE bot_settings ADD COLUMN IF NOT EXISTS zernio_api_key VARCHAR(255);"
            ))
            conn.execute(text(
                "ALTER TABLE bot_settings ADD COLUMN IF NOT EXISTS zernio_profile_id VARCHAR(100);"
            ))
            conn.execute(text(
                "ALTER TABLE bot_settings ADD COLUMN IF NOT EXISTS zernio_account_id VARCHAR(100);"
            ))
            conn.execute(text(
                "ALTER TABLE bot_settings ADD COLUMN IF NOT EXISTS instagram_username VARCHAR(100);"
            ))
            conn.execute(text(
                "ALTER TABLE bot_settings ADD COLUMN IF NOT EXISTS automation_provider VARCHAR(50) DEFAULT 'zernio';"
            ))
            conn.execute(text(
                "ALTER TABLE bot_settings ADD COLUMN IF NOT EXISTS postzen_api_key VARCHAR(255);"
            ))
            conn.execute(text(
                "ALTER TABLE bot_settings ADD COLUMN IF NOT EXISTS postzen_account_id VARCHAR(100);"
            ))
            conn.execute(text(
                "CREATE INDEX IF NOT EXISTS ix_messages_customer_id ON messages (customer_id);"
            ))



@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    ws_manager.set_loop(asyncio.get_running_loop())
    logger.info("GramCRM server started. All logs are actively recorded.")

    # گزارش وضعیت امنیتی env هنگام استارت (بدون نمایش مقادیر محرمانه)
    posture = security_warnings()
    if posture:
        logger.warning("=" * 70)
        for item in posture:
            logger.warning(f"⚠️ امنیت: {item}")
        logger.warning("=" * 70)
    # ساخت جداول دیتابیس
    Base.metadata.create_all(bind=engine)
    logger.info("Database tables created/verified.")

    try:
        run_schema_migrations()
        logger.info("Schema migrations applied.")
    except Exception as e:
        logger.error(f"Schema migration failed: {e}")

    # تنظیمات ذخیره‌شده در دیتابیس باید قبل از شروع ورکر روی کلاینت‌های API اعمال شوند.
    with SessionLocal() as db:
        saved_settings = db.query(BotSetting).filter(BotSetting.id == 1).first()
        if saved_settings:
            from app.service.bot_settings import apply_credentials_to_services
            apply_credentials_to_services(saved_settings)

    # راه‌اندازی ورکر اینستاگرام
    stop_event = asyncio.Event()
    worker_task = None

    if settings.ENABLE_IG_WORKER:
        from app.service.instagram_service import instagram_client
        from app.worker import run_worker

        logger.info("Starting Instagram DM background worker (Zernio API)...")
        instagram_client.login()
        worker_task = asyncio.create_task(run_worker(stop_event))
    else:
        logger.info("Instagram DM worker is disabled in settings.")

    # راه‌اندازی ورکر داخلی وب‌هوک (صف درون‌فرآیندی)
    webhook_stop_event = asyncio.Event()
    webhook_task = None
    if settings.ENABLE_WEBHOOK_QUEUE:
        from app.routers.webhook import start_webhook_workers
        logger.info("Starting webhook background workers...")
        webhook_task = asyncio.create_task(start_webhook_workers(webhook_stop_event, settings.WEBHOOK_WORKER_COUNT))
    else:
        logger.info("Webhook queue worker is disabled in settings.")

    yield  # اینجا سرور در حال اجراست

    # خاموش کردن ورکرها هنگام shutdown
    if worker_task:
        stop_event.set()
        await asyncio.gather(worker_task, return_exceptions=True)
        logger.info("Instagram worker stopped.")

    if webhook_task:
        webhook_stop_event.set()
        await asyncio.gather(webhook_task, return_exceptions=True)
        logger.info("Webhook workers stopped.")


app = FastAPI(
    title="GramCRM API",
    description="پلتفرم جامع مدیریت ارتباط با مشتری (CRM) و اتوماسیون هوشمند دایرکت و فروش اینستاگرام",
    version="2.0.0",
    lifespan=lifespan,
    # غیرفعال بودن مستندات عمومی در محیط عملیاتی (قابل فعال‌سازی با ENABLE_DOCS=true)
    docs_url="/docs" if settings.ENABLE_DOCS else None,
    redoc_url="/redoc" if settings.ENABLE_DOCS else None,
    openapi_url="/openapi.json" if settings.ENABLE_DOCS else None,
)

# کوکی امضاشده برای سشن ورود به پنل
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.ADMIN_SESSION_SECRET,
    # روی سرور عملیاتی با SESSION_HTTPS_ONLY=true کوکی فقط با HTTPS ارسال می‌شود
    https_only=settings.SESSION_HTTPS_ONLY,
    same_site="lax",
)

app.include_router(auth_router)
app.include_router(product_router)
app.include_router(order_router)
app.include_router(customer_router)
app.include_router(message_router)
app.include_router(conversations_router)
app.include_router(keyword_router)
app.include_router(settings_router)
app.include_router(webhook_router)
app.include_router(zernio_webhook_router)
app.include_router(system_router)
app.include_router(websocket_router)


@app.get("/favicon.ico", include_in_schema=False)
def favicon():
    icon_path = PANEL_DIR / "favicon.ico"
    if icon_path.exists():
        return FileResponse(path=str(icon_path), media_type="image/x-icon")
    raise HTTPException(status_code=404, detail="Favicon not found")


@app.get("/favicon.png", include_in_schema=False)
def favicon_png():
    icon_path = PANEL_DIR / "favicon-32x32.png"
    if icon_path.exists():
        return FileResponse(path=str(icon_path), media_type="image/png")
    raise HTTPException(status_code=404, detail="Favicon not found")


@app.get("/", include_in_schema=False)
def root():
    return RedirectResponse(url="/panel")


@app.get("/guide.pdf", include_in_schema=False)
@app.get("/download-guide", include_in_schema=False)
def download_guide():
    base_dir = Path(__file__).resolve().parent.parent
    pdf_path = base_dir / "docs" / "GramCRM_User_Guide.pdf"
    if not pdf_path.exists():
        pdf_path = base_dir / "GramCRM_User_Guide.pdf"
    if not pdf_path.exists():
        pdf_path = PANEL_DIR / "GramCRM_User_Guide.pdf"
    if not pdf_path.exists():
        raise HTTPException(status_code=404, detail="فایل راهنما یافت نشد")
    return FileResponse(
        path=str(pdf_path),
        filename="GramCRM_User_Guide.pdf",
        media_type="application/pdf"
    )


# پنل مدیریت (فایل‌های استاتیک؛ خود APIها محافظت‌شده هستند)
app.mount("/panel", StaticFiles(directory=str(PANEL_DIR), html=True), name="panel")
