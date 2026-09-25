from pydantic import BaseModel, field_validator
from datetime import datetime

class CustomerCreate(BaseModel):#اطلاعاتی ک از کاربر میاد
    instagram_id:str
    username:str | None=None
    name:str | None=None

class CustomerResponse(CustomerCreate):# اطلاعاتی ک api برمیگردونه
    id: int
    created_at : datetime

    class Config:
        from_attributes = True

class CustomerUpdate(BaseModel):
    username: str | None = None
    name: str | None = None


class ManualSendRequest(BaseModel):
    text: str

    @field_validator("text")
    @classmethod
    def not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("متن پیام نمی‌تواند خالی باشد")
        return value