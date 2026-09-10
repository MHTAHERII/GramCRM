from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker , declarative_base

DATABASE_URL = "postgresql://postgres:73752@localhost:5432/perfume_bot"
engine = create_engine(DATABASE_URL)#یک موتور ایجاد میکند ک مسئول مدیریت اتصالات به دیتابیس است

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()#یه کلاس پایه ایجاد میکند که همه مدل های جدول شما باید از آن ارث بری کنند
print(engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

