import secrets

from fastapi import APIRouter, HTTPException, Request, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.service.bot_settings import get_bot_settings

router = APIRouter(prefix="/auth", tags=["Auth"])

# کلیدی که در سشن کوکی ذخیره می‌شود
SESSION_KEY = "authenticated"


class LoginRequest(BaseModel):
    username: str | None = None
    password: str


def require_auth(request: Request) -> None:
    """دیپندنسی محافظت از روترها؛ در صورت عدم ورود 401 برمی‌گرداند"""
    if not request.session.get(SESSION_KEY):
        raise HTTPException(status_code=401, detail="ابتدا وارد پنل شوید")


@router.post("/login")
def login(body: LoginRequest, request: Request, db: Session = Depends(get_db)):
    bot_settings = get_bot_settings(db)
    expected_username = bot_settings.admin_username or "admin"
    expected_password = bot_settings.admin_password or settings.ADMIN_PASSWORD

    # اگر کاربر نام کاربری ارسال کرده باشد، با یوزرنیم ذخیره‌شده تطبیق داده می‌شود
    if body.username and body.username.strip():
        if body.username.strip() != expected_username:
            raise HTTPException(status_code=401, detail="نام کاربری یا رمز عبور اشتباه است")

    # مقایسه زمان-ثابت برای جلوگیری از حمله timing
    if not secrets.compare_digest(body.password, expected_password):
        raise HTTPException(status_code=401, detail="نام کاربری یا رمز عبور اشتباه است")

    request.session[SESSION_KEY] = True
    return {"message": "ورود موفق"}


@router.post("/logout")
def logout(request: Request):
    request.session.clear()
    return {"message": "خارج شدید"}
