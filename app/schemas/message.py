from typing import Literal

from pydantic import BaseModel
from datetime import datetime
from app.schemas.customer import CustomerResponse


class MessageCreate(BaseModel):
    customer_id: int
    text: str
    sender: Literal["customer", "bot", "admin"] = "customer"
    instagram_message_id: str | None = None




class MessageResponse(MessageCreate):
    id: int
    created_at: datetime

    class Config:
        from_attributes = True


class ConversationResponse(BaseModel):
    """یک گفتگو: اطلاعات مشتری + آخرین پیام ردوبدل‌شده"""
    customer: "CustomerResponse"
    last_message: "MessageResponse | None" = None