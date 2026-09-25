import collections
import datetime
import logging
import os
import shutil
import time
from typing import Any, Dict, List, Optional
from sqlalchemy.orm import Session

from app.models.keyword import Keyword
from app.models.product import Product
from app.models.customer import Customer
from app.models.message import Message
from app.models.bot_setting import BotSetting
from app.service.bot_settings import get_bot_settings, apply_credentials_to_services
from app.service.zernio_service import zernio_service

# ثبت زمان استارت پروسس برای محاسبه دقیق آپتایم
START_TIME = time.time()

# بافر حافظه‌ای حلقوی لاگ‌ها (حداکثر ۴۰۰ خط اخیر)
LOG_BUFFER = collections.deque(maxlen=400)


class LogBufferHandler(logging.Handler):
    """هندلر ثبت لاگ‌ها در بافر حافظه جهت نمایش زنده در پنل وب"""
    def emit(self, record: logging.LogRecord) -> None:
        try:
            log_entry = {
                "time": datetime.datetime.fromtimestamp(record.created).strftime("%Y-%m-%d %H:%M:%S"),
                "level": record.levelname,
                "logger": record.name,
                "message": record.getMessage(),
                "raw": self.format(record)
            }
            LOG_BUFFER.append(log_entry)
        except Exception:
            pass


log_buffer_handler = LogBufferHandler()
log_buffer_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s"))
logging.getLogger().addHandler(log_buffer_handler)


def get_logs(limit: int = 150) -> List[Dict[str, Any]]:
    """دریافت آخرین لاگ‌های سیستم"""
    logs_list = list(LOG_BUFFER)
    return logs_list[-limit:] if limit > 0 else logs_list


def clear_logs() -> None:
    """پاکسازی بافر لاگ‌ها"""
    LOG_BUFFER.clear()


def format_uptime(seconds: float) -> str:
    """تبدیل ثانیه به فرمت خوانا (روز، ساعت، دقیقه)"""
    days = int(seconds // 86400)
    hours = int((seconds % 86400) // 3600)
    minutes = int((seconds % 3600) // 60)
    parts = []
    if days > 0:
        parts.append(f"{days} روز")
    if hours > 0:
        parts.append(f"{hours} ساعت")
    parts.append(f"{minutes} دقیقه")
    return " و ".join(parts) if parts else "کمتر از ۱ دقیقه"


def get_system_status(db: Session) -> Dict[str, Any]:
    """
    استعلام وضعیت زنده منابع سرور و آمار کلی CRM
    مشابه ویجت‌های پنل 3X-UI
    """
    # ۱. محاسبه Uptime
    uptime_seconds = time.time() - START_TIME
    uptime_str = format_uptime(uptime_seconds)

    # ۲. اطلاعات سخت‌افزاری با psutil (همراه با فال‌بک ایمن)
    cpu_percent = 0.0
    cpu_cores = os.cpu_count() or 1
    memory_info = {"total_mb": 1024, "used_mb": 256, "percent": 25.0}

    try:
        import psutil
        cpu_percent = psutil.cpu_percent(interval=None)
        vm = psutil.virtual_memory()
        memory_info = {
            "total_mb": round(vm.total / (1024 * 1024)),
            "used_mb": round(vm.used / (1024 * 1024)),
            "free_mb": round(vm.available / (1024 * 1024)),
            "percent": vm.percent
        }
    except Exception:
        pass

    # ۳. فضای دیسک با کتابخانه استاندارد shutil
    disk_info = {"total_gb": 20, "used_gb": 5, "free_gb": 15, "percent": 25.0}
    try:
        disk_path = "/" if os.name != "nt" else "C:\\"
        total, used, free = shutil.disk_usage(disk_path)
        disk_info = {
            "total_gb": round(total / (1024 ** 3), 1),
            "used_gb": round(used / (1024 ** 3), 1),
            "free_gb": round(free / (1024 ** 3), 1),
            "percent": round((used / total) * 100, 1) if total > 0 else 0
        }
    except Exception:
        pass

    # ۴. آمار دیتابیس CRM
    try:
        total_customers = db.query(Customer).count()
        total_messages = db.query(Message).count()
        total_keywords = db.query(Keyword).count()
        active_keywords = db.query(Keyword).filter(Keyword.active == True).count()
        total_products = db.query(Product).count()
    except Exception as e:
        logging.getLogger("system_service").error(f"Error querying CRM counts: {e}")
        total_customers = total_messages = total_keywords = active_keywords = total_products = 0

    # ۵. وضعیت ربات و اتصال اینستاگرام
    settings = get_bot_settings(db)
    is_connected = zernio_service.is_configured()

    return {
        "system": {
            "uptime": uptime_str,
            "uptime_seconds": int(uptime_seconds),
            "cpu_percent": cpu_percent,
            "cpu_cores": cpu_cores,
            "memory": memory_info,
            "disk": disk_info,
        },
        "crm": {
            "total_customers": total_customers,
            "total_messages": total_messages,
            "total_keywords": total_keywords,
            "active_keywords": active_keywords,
            "total_products": total_products,
        },
        "bot": {
            "enabled": settings.bot_enabled,
            "follow_gate_enabled": settings.follow_gate_enabled,
            "instagram_connected": is_connected
        }
    }


def create_backup(db: Session) -> Dict[str, Any]:
    """تولید خروجی کامل و ساختاریافته از تمام داده‌های دیتابیس"""
    settings = get_bot_settings(db)
    keywords = db.query(Keyword).all()
    products = db.query(Product).all()
    customers = db.query(Customer).all()

    return {
        "version": "2.0.0",
        "app": "GramCRM",
        "exported_at": datetime.datetime.utcnow().isoformat(),
        "settings": {
            "bot_enabled": settings.bot_enabled,
            "fallback_message": settings.fallback_message,
            "follow_gate_enabled": settings.follow_gate_enabled,
            "follow_gate_message": settings.follow_gate_message,
            "comment_reply_enabled": settings.comment_reply_enabled,
            "comment_public_reply_enabled": settings.comment_public_reply_enabled,
            "comment_public_reply_text": settings.comment_public_reply_text,
            "admin_username": settings.admin_username,
            "zernio_api_key": settings.zernio_api_key,
            "zernio_profile_id": settings.zernio_profile_id,
            "zernio_account_id": settings.zernio_account_id,
        },
        "keywords": [
            {
                "keyword": kw.keyword,
                "response": kw.response,
                "button_title": kw.button_title,
                "button_url": kw.button_url,
                "buttons": kw.buttons,
                "active": kw.active
            }
            for kw in keywords
        ],
        "products": [
            {
                "name": p.name,
                "price": p.price,
                "stock": p.stock,
                "description": p.description
            }
            for p in products
        ],
        "customers": [
            {
                "instagram_user_id": c.instagram_user_id,
                "username": c.username,
                "full_name": c.full_name,
                "notes": c.notes
            }
            for c in customers
        ]
    }


def restore_backup(db: Session, backup_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    بازیابی امن و تراکنشی دیتابیس از فایل پشتیبان
    در صورت هرگونه خطا، تغییرات rollback می‌شوند.
    """
    if not isinstance(backup_data, dict):
        raise ValueError("فرمت فایل نامعتبر است (باید ساختار JSON باشد)")

    restored_counts = {"keywords": 0, "products": 0, "customers": 0, "settings": False}

    try:
        # ۱. بازیابی تنظیمات
        if "settings" in backup_data and isinstance(backup_data["settings"], dict):
            s_data = backup_data["settings"]
            setting = get_bot_settings(db)
            if "bot_enabled" in s_data: setting.bot_enabled = s_data["bot_enabled"]
            if "fallback_message" in s_data and s_data["fallback_message"]: setting.fallback_message = s_data["fallback_message"]
            if "follow_gate_enabled" in s_data: setting.follow_gate_enabled = s_data["follow_gate_enabled"]
            if "follow_gate_message" in s_data: setting.follow_gate_message = s_data["follow_gate_message"]
            if "comment_reply_enabled" in s_data: setting.comment_reply_enabled = s_data["comment_reply_enabled"]
            if "comment_public_reply_enabled" in s_data: setting.comment_public_reply_enabled = s_data["comment_public_reply_enabled"]
            if "comment_public_reply_text" in s_data: setting.comment_public_reply_text = s_data["comment_public_reply_text"]
            if "admin_username" in s_data and s_data["admin_username"]: setting.admin_username = s_data["admin_username"]
            if "zernio_api_key" in s_data: setting.zernio_api_key = s_data["zernio_api_key"]
            if "zernio_profile_id" in s_data: setting.zernio_profile_id = s_data["zernio_profile_id"]
            if "zernio_account_id" in s_data: setting.zernio_account_id = s_data["zernio_account_id"]
            apply_credentials_to_services(setting)
            restored_counts["settings"] = True

        # ۲. بازیابی کلمات کلیدی (Upsert)
        if "keywords" in backup_data and isinstance(backup_data["keywords"], list):
            for kw_item in backup_data["keywords"]:
                word = str(kw_item.get("keyword", "")).strip()
                resp = str(kw_item.get("response", "")).strip()
                if not word or not resp:
                    continue

                existing = db.query(Keyword).filter(Keyword.keyword == word).first()
                if existing:
                    existing.response = resp
                    existing.button_title = kw_item.get("button_title")
                    existing.button_url = kw_item.get("button_url")
                    existing.buttons = kw_item.get("buttons")
                    existing.active = kw_item.get("active", True)
                else:
                    new_kw = Keyword(
                        keyword=word,
                        response=resp,
                        button_title=kw_item.get("button_title"),
                        button_url=kw_item.get("button_url"),
                        buttons=kw_item.get("buttons"),
                        active=kw_item.get("active", True)
                    )
                    db.add(new_kw)
                restored_counts["keywords"] += 1

        # ۳. بازیابی محصولات (Upsert بر اساس نام)
        if "products" in backup_data and isinstance(backup_data["products"], list):
            for p_item in backup_data["products"]:
                name = str(p_item.get("name", "")).strip()
                if not name:
                    continue
                price = int(p_item.get("price", 0))
                stock = int(p_item.get("stock", 0))
                desc = p_item.get("description")

                p_exist = db.query(Product).filter(Product.name == name).first()
                if p_exist:
                    p_exist.price = price
                    p_exist.stock = stock
                    p_exist.description = desc
                else:
                    new_p = Product(name=name, price=price, stock=stock, description=desc)
                    db.add(new_p)
                restored_counts["products"] += 1

        # ۴. بازیابی مشتریان
        if "customers" in backup_data and isinstance(backup_data["customers"], list):
            for c_item in backup_data["customers"]:
                ig_id = str(c_item.get("instagram_user_id", "")).strip()
                if not ig_id:
                    continue
                c_exist = db.query(Customer).filter(Customer.instagram_user_id == ig_id).first()
                if c_exist:
                    c_exist.username = c_item.get("username")
                    c_exist.full_name = c_item.get("full_name")
                    c_exist.notes = c_item.get("notes")
                else:
                    new_c = Customer(
                        instagram_user_id=ig_id,
                        username=c_item.get("username"),
                        full_name=c_item.get("full_name"),
                        notes=c_item.get("notes")
                    )
                    db.add(new_c)
                restored_counts["customers"] += 1

        db.commit()

        # ۵. همگام‌سازی فوری با اینستاگرام (Zernio)
        try:
            zernio_service.sync_all_keywords(db)
        except Exception as e:
            logging.getLogger("system_service").error(f"Error auto-syncing restored keywords: {e}")

        return {
            "success": True,
            "message": "اطلاعات فایل پشتیبان با موفقیت بازیابی شد.",
            "restored": restored_counts
        }

    except Exception as e:
        db.rollback()
        raise e
