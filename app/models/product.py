from sqlalchemy import Column, Integer, String, Text, Boolean

from app.database import Base


class Product(Base):#این کلاس قراره به جدول دیتابیس تبدیل شه
    __tablename__ = "products"
    id = Column(Integer, primary_key=True,index=True)
    name = Column(String(150), nullable=False)
    description = Column(Text, nullable=False)
    price = Column(Integer, nullable=False)
    stock = Column(Integer, nullable=False)
    active = Column(Boolean, default=True)
