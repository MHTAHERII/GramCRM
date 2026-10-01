from pydantic import BaseModel, Field, field_validator
from datetime import datetime

class CustomerCreate(BaseModel):#اطلاعاتی ک از کاربر میاد
    instagram_id:str
    username:str | None=None
    name:str | None=None

class CustomerResponse(CustomerCreate):# اطلاعاتی ک api برمیگردونه
    bot_paused: bool = False
    id: int
    created_at : datetime

    class Config:
        from_attributes = True

class CustomerUpdate(BaseModel):
    bot_paused: bool | None = None
    username: str | None = None
    name: str | None = None


class ManualSendRequest(BaseModel):
    text: str = Field(min_length=1, max_length=640)

    @field_validator("text")
    @classmethod
    def not_blank(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("متن پیام نمی‌تواند خالی باشد")
        if len(stripped) > 640:
            raise ValueError("متن پیام دایرکت نمی‌تواند بیشتر از ۶۴۰ کاراکتر باشد")
        return stripped
