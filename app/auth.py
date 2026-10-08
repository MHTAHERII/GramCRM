import secrets
import time

from fastapi import APIRouter, HTTPException, Request, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.service.bot_settings import get_bot_settings

router = APIRouter(prefix="/auth", tags=["Auth"])

# کلیدی که در سشن کوکی ذخیره می‌شود
SESSION_KEY = "authenticated"

# محدودیت نرخ ساده برای لاگین: حداکثر ۱۰ تلاش در ۵ دقیقه برای هر IP
_LOGIN_ATTEMPTS: dict[str, list[float]] = {}
_LOGIN_WINDOW_SECONDS = 300.0
_LOGIN_MAX_ATTEMPTS = 10


def _login_rate_ok(client_ip: str) -> bool:
    now = time.time()
    attempts = [t for t in _LOGIN_ATTEMPTS.get(client_ip, []) if now - t < _LOGIN_WINDOW_SECONDS]
    if len(attempts) >= _LOGIN_MAX_ATTEMPTS:
        return False
    attempts.append(now)
    _LOGIN_ATTEMPTS[client_ip] = attempts
    return True


class LoginRequest(BaseModel):
    username: str
    password: str


def require_auth(request: Request) -> None:
    """دیپندنسی محافظت از روترها؛ در صورت عدم ورود 401 برمی‌گرداند"""
    if not request.session.get(SESSION_KEY):
        raise HTTPException(status_code=401, detail="ابتدا وارد پنل شوید")


@router.post("/login")
def login(body: LoginRequest, request: Request, db: Session = Depends(get_db)):
    client_ip = request.client.host if request.client else "unknown"
    if not _login_rate_ok(client_ip):
        raise HTTPException(status_code=429, detail="تلاش‌های زیاد برای ورود؛ لطفاً چند دقیقه صبر کنید")

    bot_settings = get_bot_settings(db)
    expected_username = bot_settings.admin_username or "admin"
    expected_password = bot_settings.admin_password or settings.ADMIN_PASSWORD

    if not secrets.compare_digest(body.username.strip(), expected_username):
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
