from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from typing import Any

from app.auth import require_auth
from app.database import get_db
from app.service.licensing_service import (
    get_active_license,
    activate_license_key,
    validate_license,
)

router = APIRouter(
    prefix="/license",
    tags=["Licensing"],
    dependencies=[Depends(require_auth)]
)


class LicenseActivateRequest(BaseModel):
    license_key: str = Field(..., min_length=10, description="کلید لایسنس دیجیتال")


class LicenseStatusResponse(BaseModel):
    is_valid: bool
    status: str
    licensee: str | None = None
    tier: str | None = None
    issued_at: str | None = None
    expires_at: str | None = None
    days_remaining: int | None = None
    features: list[str] = []
    message: str


@router.get("/status", response_model=LicenseStatusResponse, summary="استعلام وضعیت لایسنس نرم‌افزار")
def check_license_status(db: Session = Depends(get_db)):
    """بررسی اعتبار، تاریخ انقضا و امکانات فعال لایسنس"""
    result = get_active_license(db)
    return LicenseStatusResponse(**result)


@router.post("/activate", response_model=LicenseStatusResponse, summary="فعال‌سازی یا تمدید لایسنس جدید")
def activate_license(payload: LicenseActivateRequest, db: Session = Depends(get_db)):
    """اعتبارسنجی و ثبت کلید لایسنس جدید در سیستم"""
    result = activate_license_key(payload.license_key, db)
    if not result.get("is_valid"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=result.get("message", "کلید لایسنس نامعتبر است.")
        )
    return LicenseStatusResponse(**result)
