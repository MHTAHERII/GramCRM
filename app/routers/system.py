import json
import datetime
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Response
from sqlalchemy.orm import Session

from app.auth import require_auth
from app.database import get_db
from app.service.system_service import (
    get_system_status,
    create_backup,
    restore_backup,
    get_logs,
    clear_logs,
    get_version_info,
    execute_system_update
)

router = APIRouter(prefix="/system", tags=["System"], dependencies=[Depends(require_auth)])


@router.get("/status", summary="استعلام وضعیت زنده منابع سرور و آمار CRM")
def get_status(db: Session = Depends(get_db)):
    """اطلاعات کامل مصرف CPU، حافظه RAM، دیسک، آپتایم و آمارهای تعاملات اینستاگرام"""
    try:
        return get_system_status(db)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"خطا در دریافت وضعیت سیستم: {str(e)}")


@router.get("/backup", summary="دانلود فایل پشتیبان کامل از دیتابیس")
def download_backup(db: Session = Depends(get_db)):
    """تولید و دانلود خروجی JSON کامل از کلمات کلیدی، تنظیمات، محصولات و مشتریان"""
    try:
        backup_data = create_backup(db)
        json_content = json.dumps(backup_data, ensure_ascii=False, indent=2)
        filename = f"gramcrm_backup_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        
        return Response(
            content=json_content,
            media_type="application/json",
            headers={
                "Content-Disposition": f"attachment; filename={filename}",
                "Cache-Control": "no-cache"
            }
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"خطا در تولید فایل پشتیبان: {str(e)}")


@router.post("/restore", summary="بازیابی دیتابیس از فایل پشتیبان JSON")
async def upload_restore(file: UploadFile = File(...), db: Session = Depends(get_db)):
    """آپلود فایل JSON پشتیبان و بازیابی کامل اطلاعات با تطبیق خودکار و بدون تداخل"""
    if not file.filename.endswith(".json"):
        raise HTTPException(status_code=400, detail="فایل باید دارای پسوند .json باشد")

    try:
        content = await file.read()
        backup_data = json.loads(content.decode("utf-8"))
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"فایل نامعتبر است یا ساختار JSON خراب است: {str(e)}")

    try:
        result = restore_backup(db, backup_data)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"خطا در بازیابی اطلاعات: {str(e)}")


@router.get("/logs", summary="مشاهده زنده لاگ‌های کنسول سیستم")
def read_logs(limit: int = 150):
    """دریافت آخرین لاگ‌های سرور جهت عیب‌یابی بدون نیاز به ترمینال SSH"""
    return {
        "logs": get_logs(limit)
    }


@router.delete("/logs", summary="پاکسازی لاگ‌های کنسول")
def purge_logs():
    """خالی کردن بافر لاگ‌های سرور"""
    clear_logs()
    return {"success": True, "message": "لاگ‌های سیستم پاکسازی شدند"}


@router.get("/version", summary="استعلام وضعیت نسخه پنل و بررسی آخرین تغییرات گیت‌هاب")
def check_version():
    """بررسی نسخه فعلی سرور در مقایسه با آخرین کامیت مخزن گیت‌هاب جهت تشخیص آپدیت"""
    try:
        return get_version_info()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"خطا در بررسی نسخه: {str(e)}")


@router.post("/update", summary="اجرای به‌روزرسانی پنل به آخرین نسخه با یک کلیک")
def trigger_update():
    """دریافت آخرین کدهای پروژه از گیت‌هاب، بروزرسانی پکیج‌ها، و راه‌اندازی مجدد سرویس"""
    try:
        result = execute_system_update()
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"خطا در اجرای به‌روزرسانی: {str(e)}")

