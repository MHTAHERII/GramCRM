from pydantic import BaseModel
from datetime import datetime


class MessageCreate(BaseModel):
    customer_id: int
    text: str
    sender: str


class MessageResponse(MessageCreate):
    id: int
    created_at: datetime

    class Config:
        from_attributes = True