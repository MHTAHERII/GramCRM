from pydantic import BaseModel
from datetime import datetime


class BotSettingUpdate(BaseModel):
    bot_enabled: bool | None = None
    fallback_message: str | None = None
    follow_gate_enabled: bool | None = None
    follow_gate_message: str | None = None
    comment_reply_enabled: bool | None = None
    comment_public_reply_enabled: bool | None = None
    comment_public_reply_text: str | None = None


class BotSettingResponse(BotSettingUpdate):
    id: int
    bot_enabled: bool
    fallback_message: str
    follow_gate_enabled: bool
    follow_gate_message: str
    comment_reply_enabled: bool
    comment_public_reply_enabled: bool
    comment_public_reply_text: str | None
    updated_at: datetime

    class Config:
        from_attributes = True
