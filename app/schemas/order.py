from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class OrderCreate(BaseModel):
    request_key: UUID
    customer_id: int = Field(gt=0)
    product_id: int = Field(gt=0)
    quantity: int = Field(gt=0, le=1_000_000)
    recipient_name: str = Field(min_length=1, max_length=150)
    phone: str = Field(min_length=3, max_length=30)
    address: str = Field(min_length=1, max_length=2000)
    notes: str = Field(default="", max_length=4000)

    @field_validator("recipient_name", "phone", "address")
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError("این فیلد نمی‌تواند خالی باشد")
        return value.strip()


class OrderUpdate(BaseModel):
    version: int = Field(gt=0)
    status: Literal["pending", "confirmed", "shipped", "cancelled"]
    tracking_code: str = Field(default="", max_length=100)


class OrderResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    customer_id: int
    product_id: int
    product_name: str
    unit: str
    quantity: int
    unit_price: int
    total_price: int
    recipient_name: str
    phone: str
    address: str
    notes: str
    status: str
    tracking_code: str
    receipt_type: str | None
    version: int
    created_at: datetime
    updated_at: datetime
