from datetime import datetime

from sqlalchemy import Column, Integer, BigInteger, String, Text, DateTime, ForeignKey, LargeBinary
from sqlalchemy.orm import deferred

from app.database import Base


class Order(Base):
    __tablename__ = "orders"

    id = Column(Integer, primary_key=True)
    request_key = Column(String(36), unique=True, nullable=False)
    customer_id = Column(Integer, ForeignKey("customers.id"), nullable=False, index=True)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False, index=True)
    product_name = Column(String(150), nullable=False)
    unit = Column(String(30), nullable=False)
    quantity = Column(Integer, nullable=False)
    unit_price = Column(BigInteger, nullable=False)
    total_price = Column(BigInteger, nullable=False)
    recipient_name = Column(String(150), nullable=False)
    phone = Column(String(30), nullable=False)
    address = Column(Text, nullable=False)
    notes = Column(Text, nullable=False, default="")
    status = Column(String(30), nullable=False, default="pending")
    tracking_code = Column(String(100), nullable=False, default="")
    receipt_data = deferred(Column(LargeBinary, nullable=True))
    receipt_type = Column(String(50), nullable=True)
    version = Column(Integer, nullable=False, default=1)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
