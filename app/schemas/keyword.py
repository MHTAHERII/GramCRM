from pydantic import BaseModel, field_validator
from datetime import datetime


class KeywordButton(BaseModel):
    title: str
    url: str


class KeywordBase(BaseModel):
    keyword: str
    response: str
    button_title: str | None = None
    button_url: str | None = None
    buttons: list[KeywordButton] | None = None

    @field_validator("keyword", "response")
    @classmethod
    def not_blank(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("نمی‌تواند خالی باشد")
        return stripped


class KeywordCreate(KeywordBase):
    pass


class KeywordUpdate(BaseModel):
    keyword: str | None = None
    response: str | None = None
    button_title: str | None = None
    button_url: str | None = None
    buttons: list[KeywordButton] | None = None
    active: bool | None = None


class KeywordResponse(KeywordBase):
    id: int
    active: bool
    created_at: datetime

    class Config:
        from_attributes = True
