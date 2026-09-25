from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker , declarative_base
from app.config import settings
DATABASE_URL = settings.DATABASE_URL
engine = create_engine(DATABASE_URL)#یک موتور ایجاد میکند ک مسئول مدیریت اتصالات به دیتابیس است

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()#یه کلاس پایه ایجاد میکند که همه مدل های جدول شما باید از آن ارث بری کنند

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

