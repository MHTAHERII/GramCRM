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
    # پاکسازی ورودی‌های منقضی‌شده سایر IP ها تا دیکشنری رشد نکند
    if len(_LOGIN_ATTEMPTS) > 1000:
        for ip in list(_LOGIN_ATTEMPTS):
            stale = [t for t in _LOGIN_ATTEMPTS[ip] if now - t < _LOGIN_WINDOW_SECONDS]
            if stale:
                _LOGIN_ATTEMPTS[ip] = stale
            else:
                _LOGIN_ATTEMPTS.pop(ip, None)
    return True


def _constant_time_equals(a: str, b: str) -> bool:
    """
    مقایسه زمان-ثابت امن برای هر نوع رشته (ASCII یا فارسی).
    secrets.compare_digest روی str غیر-ASCII استثنا می‌دهد؛ تبدیل به UTF-8
    هم مشکل را حل می‌کند و همچنان مقایسه را زمان-ثابت نگه می‌دارد.
    """
    return secrets.compare_digest(a.encode("utf-8"), b.encode("utf-8"))


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

    if not _constant_time_equals(body.username.strip(), expected_username):
        raise HTTPException(status_code=401, detail="نام کاربری یا رمز عبور اشتباه است")

    # مقایسه زمان-ثابت برای جلوگیری از حمله timing (پشتیبانی از رمزهای فارسی/غیر-ASCII)
    if not _constant_time_equals(body.password, expected_password):
        raise HTTPException(status_code=401, detail="نام کاربری یا رمز عبور اشتباه است")

    request.session[SESSION_KEY] = True
    return {"message": "ورود موفق"}


@router.post("/logout")
def logout(request: Request):
    request.session.clear()
    return {"message": "خارج شدید"}
