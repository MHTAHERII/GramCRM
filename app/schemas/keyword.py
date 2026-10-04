from pydantic import BaseModel, Field, field_validator
from datetime import datetime


class KeywordButton(BaseModel):
    title: str = Field(min_length=1, max_length=100)
    url: str | None = None
    type: str = "url"


class KeywordBase(BaseModel):
    product_id: int | None = None
    keyword: str = Field(min_length=1, max_length=100)
    response: str = Field(min_length=1, max_length=640)
    comment_reply: str | None = Field(default=None, max_length=640)
    button_title: str | None = None
    button_url: str | None = None
    buttons: list[KeywordButton] | None = None
    comment_reply_delay_seconds: int | None = Field(default=0, ge=0, le=86400)
    dm_delay_seconds: int | None = Field(default=0, ge=0, le=86400)
    comment_reply_variations: list[str] | None = None
    dm_message_variations: list[str] | None = None
    platform_post_id: str | None = None

    @field_validator("keyword", "response")
    @classmethod
    def not_blank(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("نمی‌تواند خالی باشد")
        if len(stripped) > 640:
            raise ValueError("متن پیام دایرکت نمی‌تواند بیشتر از ۶۴۰ کاراکتر باشد")
        return stripped


class KeywordCreate(KeywordBase):
    pass


class KeywordUpdate(BaseModel):
    product_id: int | None = None
    keyword: str | None = Field(default=None, min_length=1, max_length=100)
    response: str | None = Field(default=None, min_length=1, max_length=640)
    comment_reply: str | None = Field(default=None, max_length=640)
    button_title: str | None = None
    button_url: str | None = None
    buttons: list[KeywordButton] | None = None
    comment_reply_delay_seconds: int | None = Field(default=None, ge=0, le=86400)
    dm_delay_seconds: int | None = Field(default=None, ge=0, le=86400)
    comment_reply_variations: list[str] | None = None
    dm_message_variations: list[str] | None = None
    platform_post_id: str | None = None
    active: bool | None = None


class KeywordResponse(KeywordBase):
    id: int
    active: bool
    created_at: datetime

    class Config:
        from_attributes = True
