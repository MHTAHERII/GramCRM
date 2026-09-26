import collections
import datetime
import json
import logging
import os
import re
import shutil
import subprocess
import time
import urllib.request
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

# بافر حافظه‌ای حلقوی لاگ‌ها (حداکثر ۵۰۰ خط اخیر)
LOG_BUFFER = collections.deque(maxlen=500)


class LogBufferHandler(logging.Handler):
    """هندلر ثبت لاگ‌ها در بافر حافظه جهت نمایش زنده در پنل وب"""
    def __init__(self):
        super().__init__()
        self._last_id = None

    def emit(self, record: logging.LogRecord) -> None:
        try:
            # جلوگیری از ثبت تکراری یک لاگ در صورت انتشار از لاگر فرزند به روت
            rec_id = (record.created, record.name, record.getMessage())
            if rec_id == self._last_id:
                return
            self._last_id = rec_id

            log_entry = {
                "time": datetime.datetime.fromtimestamp(record.created).strftime("%Y-%m-%d %H:%M:%S"),
                "level": record.levelname,
                "logger": record.name,
                "message": record.getMessage(),
                "raw": self.format(record)
            }
            LOG_BUFFER.append(log_entry)
            try:
                from app.service.ws_manager import ws_manager
                ws_manager.broadcast_sync("system_log", log_entry)
            except Exception:
                pass
        except Exception:
            pass


log_buffer_handler = LogBufferHandler()
log_buffer_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s"))


def setup_logging():
    """تنظیم روت لاگر و اتصال هندلر بافر به تمام لاگرهای سیستم جهت مانیتورینگ زنده"""
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    if log_buffer_handler not in root.handlers:
        root.addHandler(log_buffer_handler)

    for logger_name in [
        "uvicorn",
        "uvicorn.access",
        "uvicorn.error",
        "fastapi",
        "ig_worker",
        "zernio_service",
        "zernio_webhook",
        "instagram_service",
        "system_service"
    ]:
        l = logging.getLogger(logger_name)
        l.setLevel(logging.INFO)
        if log_buffer_handler not in l.handlers:
            l.addHandler(log_buffer_handler)


# اجرای اولیه هنگام ایمپورت
setup_logging()

# ثبت لاگ استارت اولیه سیستم در بافر
LOG_BUFFER.append({
    "time": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    "level": "INFO",
    "logger": "system",
    "message": "کنسول ثبت لاگ‌های زنده سرور GramCRM با موفقیت فعال شد.",
    "raw": f"{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')} [INFO] system: کنسول ثبت لاگ‌های زنده سرور GramCRM با موفقیت فعال شد."
})


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
            "instagram_connected": is_connected,
            "instagram_username": settings.instagram_username
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
            "follow_gate_buttons": settings.follow_gate_buttons or (
                [{"title": settings.follow_gate_button_title, "url": settings.follow_gate_button_url}]
                if (settings.follow_gate_button_title and settings.follow_gate_button_url) else []
            ),
            "follow_gate_button_title": settings.follow_gate_button_title,
            "follow_gate_button_url": settings.follow_gate_button_url,
            "comment_reply_enabled": settings.comment_reply_enabled,
            "comment_public_reply_enabled": settings.comment_public_reply_enabled,
            "comment_public_reply_text": settings.comment_public_reply_text,
            "admin_username": settings.admin_username,
            "zernio_api_key": settings.zernio_api_key,
            "zernio_profile_id": settings.zernio_profile_id,
            "zernio_account_id": settings.zernio_account_id,
            "instagram_username": settings.instagram_username,
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
                "instagram_id": c.instagram_id,
                "username": c.username,
                "name": c.name
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
            if "follow_gate_buttons" in s_data and isinstance(s_data["follow_gate_buttons"], list):
                setting.follow_gate_buttons = s_data["follow_gate_buttons"]
                if setting.follow_gate_buttons:
                    setting.follow_gate_button_title = setting.follow_gate_buttons[0].get("title")
                    setting.follow_gate_button_url = setting.follow_gate_buttons[0].get("url")
            elif "follow_gate_button_title" in s_data or "follow_gate_button_url" in s_data:
                setting.follow_gate_button_title = s_data.get("follow_gate_button_title")
                setting.follow_gate_button_url = s_data.get("follow_gate_button_url")
                if setting.follow_gate_button_title and setting.follow_gate_button_url:
                    setting.follow_gate_buttons = [{"title": setting.follow_gate_button_title, "url": setting.follow_gate_button_url}]
            if "comment_reply_enabled" in s_data: setting.comment_reply_enabled = s_data["comment_reply_enabled"]
            if "comment_public_reply_enabled" in s_data: setting.comment_public_reply_enabled = s_data["comment_public_reply_enabled"]
            if "comment_public_reply_text" in s_data: setting.comment_public_reply_text = s_data["comment_public_reply_text"]
            if "admin_username" in s_data and s_data["admin_username"]: setting.admin_username = s_data["admin_username"]
            if "zernio_api_key" in s_data: setting.zernio_api_key = s_data["zernio_api_key"]
            if "zernio_profile_id" in s_data: setting.zernio_profile_id = s_data["zernio_profile_id"]
            if "zernio_account_id" in s_data: setting.zernio_account_id = s_data["zernio_account_id"]
            if "instagram_username" in s_data: setting.instagram_username = s_data["instagram_username"]
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
                ig_id = str(c_item.get("instagram_id") or c_item.get("instagram_user_id") or "").strip()
                if not ig_id:
                    continue
                c_name = c_item.get("name") or c_item.get("full_name")
                c_username = c_item.get("username")
                c_exist = db.query(Customer).filter(Customer.instagram_id == ig_id).first()
                if c_exist:
                    if c_username:
                        c_exist.username = c_username
                    if c_name:
                        c_exist.name = c_name
                else:
                    new_c = Customer(
                        instagram_id=ig_id,
                        username=c_username,
                        name=c_name
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


def get_version_info() -> Dict[str, Any]:
    """
    استعلام نسخه فعلی کدها در سرور و مقایسه با آخرین کامیت مخزن گیت‌هاب (مشابه 3X-UI)
    """
    base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))

    # ۱. استخراج مشخصات مخزن گیت‌هاب
    repo_name = "MHTAHERII/GramCRM"
    try:
        remote_url = subprocess.check_output(
            ["git", "remote", "get-url", "origin"],
            cwd=base_dir,
            stderr=subprocess.DEVNULL
        ).decode("utf-8").strip()
        match = re.search(r"github\.com[:/](.+?)(?:\.git)?$", remote_url)
        if match:
            repo_name = match.group(1)
    except Exception:
        pass

    # ۲. استعلام کامیت و تاریخ لوکال
    local_commit = "نامشخص"
    local_date = ""
    local_message = ""
    try:
        local_commit = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=base_dir,
            stderr=subprocess.DEVNULL
        ).decode("utf-8").strip()
        local_date = subprocess.check_output(
            ["git", "log", "-1", "--format=%cd", "--date=short"],
            cwd=base_dir,
            stderr=subprocess.DEVNULL
        ).decode("utf-8").strip()
        local_message = subprocess.check_output(
            ["git", "log", "-1", "--pretty=%s"],
            cwd=base_dir,
            stderr=subprocess.DEVNULL
        ).decode("utf-8").strip()
    except Exception as e:
        logging.getLogger("system_service").warning(f"Could not read local git info: {e}")

    # ۳. استعلام آخرین کامیت از GitHub API
    remote_commit = "نامشخص"
    remote_date = ""
    remote_message = ""
    has_update = False
    check_error = None

    try:
        api_url = f"https://api.github.com/repos/{repo_name}/commits/main"
        req = urllib.request.Request(
            api_url,
            headers={
                "User-Agent": "GramCRM-Updater/1.0",
                "Accept": "application/vnd.github.v3+json"
            }
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            remote_full_sha = data.get("sha", "")
            remote_commit = remote_full_sha[:7] if remote_full_sha else "نامشخص"

            commit_obj = data.get("commit", {})
            full_msg = commit_obj.get("message", "")
            remote_message = full_msg.split("\n")[0] if full_msg else ""

            author_obj = commit_obj.get("author", {})
            date_raw = author_obj.get("date", "")
            remote_date = date_raw[:10] if date_raw else ""

            if local_commit != "نامشخص" and remote_commit != "نامشخص":
                if local_commit != remote_commit and not remote_full_sha.startswith(local_commit):
                    has_update = True

    except Exception as e:
        check_error = "امکان اتصال به گیت‌هاب وجود ندارد یا سقف درخواست موقت است."
        logging.getLogger("system_service").warning(f"GitHub API check failed: {e}")

    # وضعیت نهایی
    if check_error:
        status_text = check_error
    elif has_update:
        status_text = "نسخه جدید در دسترس است! می‌توانید سیستم را به‌روزرسانی کنید."
    else:
        status_text = "سیستم شما کاملاً به‌روز است (آخرین نسخه)."

    return {
        "repo": repo_name,
        "local_commit": local_commit,
        "local_date": local_date,
        "local_message": local_message,
        "remote_commit": remote_commit,
        "remote_date": remote_date,
        "remote_message": remote_message,
        "has_update": has_update,
        "status": status_text,
        "error": check_error
    }


def execute_system_update() -> Dict[str, Any]:
    """
    اجرای به‌روزرسانی پنل با یک کلیک:
    دریافت آخرین تغییرات از گیت‌هاب، نصب نیازمندی‌ها، و راه‌اندازی مجدد سرویس gramcrm
    """
    base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))

    # Railway Cloud: فقط git pull نیاز است چون Railway خودکار ری‌استارت می‌کند
    is_railway = os.environ.get("RAILWAY_ENVIRONMENT") or os.environ.get("RAILWAY_PROJECT_ID")

    if os.name == "nt":
        # محیط ویندوز (توسعه لوکال)
        try:
            res = subprocess.run(
                ["git", "pull", "origin", "main"],
                cwd=base_dir,
                capture_output=True,
                text=True,
                timeout=25
            )
            return {
                "success": True,
                "message": "دستور git pull در ویندوز با موفقیت انجام شد.",
                "output": (res.stdout or res.stderr).strip(),
                "restarting": False
            }
        except Exception as e:
            return {
                "success": False,
                "message": f"خطا در به‌روزرسانی روی ویندوز: {str(e)}",
                "restarting": False
            }
    else:
        # محیط لینوکس (VPS با systemd یا Railway Cloud)
        log_file = "/tmp/gramcrm_update.log"
        script_file = "/tmp/gramcrm_updater.sh"

        if is_railway:
            # روی Railway: git pull + pip install کافی است، ری‌استارت از طریق Railway صورت می‌گیرد
            script_content = f"""#!/bin/bash
sleep 1
cd "{base_dir}" >> {log_file} 2>&1
echo "=== GramCRM Update on Railway at $(date) ===" >> {log_file} 2>&1
git fetch --all >> {log_file} 2>&1
git reset --hard origin/main >> {log_file} 2>&1
pip install -r requirements.txt >> {log_file} 2>&1 || true
echo "=== Update done. Reload via Railway dashboard or push a new commit. ===" >> {log_file} 2>&1
"""
        else:
            # VPS با systemd
            script_content = f"""#!/bin/bash
sleep 1
cd "{base_dir}" >> {log_file} 2>&1
echo "=== شروع به‌روزرسانی GramCRM در $(date) ===" >> {log_file} 2>&1
git fetch --all >> {log_file} 2>&1
git reset --hard origin/main >> {log_file} 2>&1
if [ -d "./venv" ]; then
    ./venv/bin/pip install -r requirements.txt >> {log_file} 2>&1
else
    pip install -r requirements.txt >> {log_file} 2>&1 || true
fi
echo "=== راه‌اندازی مجدد سرویس gramcrm ===" >> {log_file} 2>&1
systemctl restart gramcrm >> {log_file} 2>&1 || true
"""
        try:
            with open(script_file, "w", encoding="utf-8") as f:
                f.write(script_content)
            os.chmod(script_file, 0o755)

            subprocess.Popen(
                ["bash", script_file],
                cwd=base_dir,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True
            )

            msg = "روی Railway: کد به‌روز شد. برای اعمال تغییرات، یک commit جدید push کنید یا از داشبورد Railway ری‌استارت بزنید." if is_railway else "فرآیند به‌روزرسانی آغاز شد. کدها از گیت‌هاب دریافت شده و پنل ظرف ۱۰ ثانیه آینده به‌صورت خودکار ریستارت خواهد شد."
            return {
                "success": True,
                "message": msg,
                "restarting": not bool(is_railway)
            }
        except Exception as e:
            return {
                "success": False,
                "message": f"خطا در اجرای اسکریپت به‌روزرسانی: {str(e)}",
                "restarting": False
            }

