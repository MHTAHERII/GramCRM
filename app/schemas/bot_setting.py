from pydantic import BaseModel, Field
from datetime import datetime


class BotSettingUpdate(BaseModel):
    bot_enabled: bool | None = None
    fallback_message: str | None = Field(default=None, max_length=640)
    follow_gate_enabled: bool | None = None
    follow_gate_message: str | None = Field(default=None, max_length=640)
    follow_gate_buttons: list[dict] | None = None
    follow_gate_button_title: str | None = None
    follow_gate_button_url: str | None = None
    comment_reply_enabled: bool | None = None
    comment_public_reply_enabled: bool | None = None
    comment_public_reply_text: str | None = Field(default=None, max_length=640)
    admin_username: str | None = None
    admin_password: str | None = None
    zernio_api_key: str | None = None
    zernio_profile_id: str | None = None
    zernio_account_id: str | None = None
    instagram_username: str | None = None
    automation_provider: str | None = None
    postzen_api_key: str | None = None
    postzen_account_id: str | None = None
    license_key: str | None = None
    gemini_api_key: str | None = Field(default=None, max_length=255)
    gemini_model: str | None = Field(default=None, max_length=100)
    ai_provider: str | None = Field(default=None, max_length=20)
    ai_base_url: str | None = Field(default=None, max_length=255)
    order_notify_enabled: bool | None = None
    order_notify_confirmed: str | None = Field(default=None, max_length=640)
    order_notify_shipped: str | None = Field(default=None, max_length=640)
    order_notify_cancelled: str | None = Field(default=None, max_length=640)



class BotSettingResponse(BaseModel):
    id: int
    bot_enabled: bool
    fallback_message: str
    follow_gate_enabled: bool
    follow_gate_message: str | None
    follow_gate_buttons: list[dict] | None = None
    follow_gate_button_title: str | None = None
    follow_gate_button_url: str | None = None
    comment_reply_enabled: bool
    comment_public_reply_enabled: bool
    comment_public_reply_text: str | None
    admin_username: str = "admin"
    has_custom_password: bool = False
    zernio_api_key: str | None = None
    zernio_profile_id: str | None = None
    zernio_account_id: str | None = None
    instagram_username: str | None = None
    automation_provider: str = "zernio"
    postzen_api_key: str | None = None
    postzen_account_id: str | None = None
    license_key: str | None = None
    gemini_api_key: str | None = None
    gemini_model: str | None = None
    ai_provider: str = "gemini"
    ai_base_url: str | None = None
    order_notify_enabled: bool = True
    order_notify_confirmed: str | None = None
    order_notify_shipped: str | None = None
    order_notify_cancelled: str | None = None
    updated_at: datetime


    class Config:
        from_attributes = True
