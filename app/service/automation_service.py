import logging
from sqlalchemy.orm import Session
from app.config import settings
from app.service.zernio_service import zernio_service
from app.service.postzen_service import postzen_service

logger = logging.getLogger("automation_service")


class AutomationService:
    @property
    def provider(self) -> str:
        return settings.AUTOMATION_PROVIDER.lower()

    @property
    def active_service(self):
        if self.provider == "postzen":
            return postzen_service
        return zernio_service

    def is_configured(self) -> bool:
        return self.active_service.is_configured()

    def list_comment_automations(self) -> list[dict]:
        return self.active_service.list_comment_automations()

    def create_comment_automation(self, *args, **kwargs) -> dict | None:
        return self.active_service.create_comment_automation(*args, **kwargs)

    def set_comment_automation_active(self, automation_id: str, active: bool) -> bool:
        return self.active_service.set_comment_automation_active(automation_id, active)

    def delete_comment_automation(self, automation_id: str) -> bool:
        return self.active_service.delete_comment_automation(automation_id)

    def sync_all_keywords(self, db: Session, force_recreate: bool = False) -> dict:
        result = self.active_service.sync_all_keywords(db, force_recreate=force_recreate)
        result["provider"] = self.provider
        return result

    def pause_all_automations(self) -> int:
        """
        غیرفعال کردن تمام اتوماسیون‌های ریموت در زمان خاموش شدن ربات برای جلوگیری از هرگونه تداخل.
        هر دو ارائه‌دهنده (زرنیو و پست‌زن) بررسی می‌شوند؛ اتوماسیون‌های ارائه‌دهنده
        غیرفعال هم نباید روی اکانت کاربر رها شوند.
        """
        paused = 0
        for svc in (zernio_service, postzen_service):
            try:
                if not svc.is_configured():
                    continue
                automations = svc.list_comment_automations()
                for auto in automations:
                    auto_id = auto.get("id") or auto.get("_id")
                    if auto_id and auto.get("isActive", True):
                        if svc.set_comment_automation_active(auto_id, False):
                            paused += 1
            except Exception as e:
                logger.error(f"Error pausing automations on provider: {e}")
        logger.info(f"Paused {paused} automations across all providers")
        return paused


automation_service = AutomationService()
