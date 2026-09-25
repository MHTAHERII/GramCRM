import secrets

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from app.config import settings

router = APIRouter(prefix="/auth", tags=["Auth"])

# کلیدی که در سشن کوکی ذخیره می‌شود
SESSION_KEY = "authenticated"


class LoginRequest(BaseModel):
    password: str


def require_auth(request: Request) -> None:
    """دیپندنسی محافظت از روترها؛ در صورت عدم ورود 401 برمی‌گرداند"""
    if not request.session.get(SESSION_KEY):
        raise HTTPException(status_code=401, detail="ابتدا وارد پنل شوید")


@router.post("/login")
def login(body: LoginRequest, request: Request):
    # مقایسه زمان-ثابت برای جلوگیری از حمله timing
    if not secrets.compare_digest(body.password, settings.ADMIN_PASSWORD):
        raise HTTPException(status_code=401, detail="رمز عبور اشتباه است")

    request.session[SESSION_KEY] = True
    return {"message": "ورود موفق"}


@router.post("/logout")
def logout(request: Request):
    request.session.clear()
    return {"message": "خارج شدید"}
