from contextlib import contextmanager
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, declarative_base
from app.config import settings

DATABASE_URL = settings.DATABASE_URL

connect_args = {}
if DATABASE_URL.startswith("sqlite"):
    connect_args["check_same_thread"] = False

# یک موتور ایجاد میکند ک مسئول مدیریت اتصالات به دیتابیس است
engine = create_engine(
    DATABASE_URL,
    connect_args=connect_args,
    pool_pre_ping=True
)

if DATABASE_URL.startswith("sqlite"):
    @event.listens_for(engine, "connect")
    def _set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA journal_mode=WAL;")
            cursor.execute("PRAGMA busy_timeout=5000;")
            cursor.execute("PRAGMA synchronous=NORMAL;")
            cursor.execute("PRAGMA foreign_keys=ON;")
        finally:
            cursor.close()

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
# یه کلاس پایه ایجاد میکند که همه مدل های جدول شما باید از آن ارث بری کنند
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


@contextmanager
def db_context(session_factory=None):
    """Context manager ایمن برای ورکرها و اسکریپت‌های پس‌زمینه بدون وابستگی به رکوئست FastAPI"""
    factory = session_factory or SessionLocal
    db = factory()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


