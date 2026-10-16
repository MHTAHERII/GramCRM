"""
تست‌های فاز ۱: اعلان خودکار وضعیت سفارش در دایرکت مشتری
"""
import unittest
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

from fastapi import BackgroundTasks, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth import require_auth
from app.database import Base, get_db
from app.models.bot_setting import BotSetting
from app.models.customer import Customer
from app.models.message import Message
from app.models.order import Order
from app.models.product import Product
from app.routers.settings import update_settings
from app.schemas.bot_setting import BotSettingUpdate
from app.service import order_notify_service as ons
from app.service.bot_settings import get_bot_settings
from app.service.instagram_service import instagram_client

# دیتابیس SQLite درون‌حافظه‌ای برای تست‌ها
_engine = create_engine(
    "sqlite://",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
Base.metadata.create_all(_engine)
TestSession = sessionmaker(bind=_engine)


def _make_session():
    return TestSession()


def _reset_notify_settings(db):
    """رکورد bot_settings بین تست‌ها مشترک است؛ هر کلاس باید از حالت پاک شروع کند."""
    bot = get_bot_settings(db)
    bot.order_notify_enabled = True
    bot.order_notify_confirmed = None
    bot.order_notify_shipped = None
    bot.order_notify_cancelled = None
    db.commit()


# کشف خودکار زرنیو در تست‌ها نباید درخواست HTTP واقعی بزند
_discovery_patch = None


def setUpModule():
    global _discovery_patch
    _discovery_patch = patch(
        "app.service.zernio_service.zernio_service.discover_account_and_profile",
        return_value=None,
    )
    _discovery_patch.start()


def tearDownModule():
    if _discovery_patch is not None:
        _discovery_patch.stop()


def _seed(db, status="confirmed", with_message=True, message_age_hours=1,
          tracking_code="", notify_pending=False, notified_status=None):
    cust = Customer(instagram_id=f"9{uuid4().hex[:8]}", username="shop_fan", name="مشتری تست")
    db.add(cust)
    db.commit()
    db.refresh(cust)
    if with_message:
        db.add(Message(
            customer_id=cust.id, text="سلام", sender="customer",
            created_at=datetime.utcnow() - timedelta(hours=message_age_hours),
        ))
    prod = Product(name="اسانس یاس", description="تست", price=150000, stock=10, active=True, unit="میل")
    db.add(prod)
    db.commit()
    db.refresh(prod)
    order = Order(
        request_key=str(uuid4()), customer_id=cust.id, product_id=prod.id,
        product_name=prod.name, unit=prod.unit, quantity=2,
        unit_price=prod.price, total_price=prod.price * 2,
        recipient_name="علی رضایی", phone="09121234567", address="تهران",
        notes="", status=status, tracking_code=tracking_code, version=1,
        notify_pending=notify_pending, notified_status=notified_status,
    )
    db.add(order)
    db.commit()
    db.refresh(order)
    return order


class TemplateRenderTests(unittest.TestCase):
    def test_render_replaces_all_variables(self):
        order = SimpleNamespace(
            product_name="اسانس یاس", quantity=2, unit="میل", total_price=300000,
            tracking_code="RA123", recipient_name="علی", id=7, status="shipped",
        )
        text = ons.render_template(
            "{recipient} سلام | {product} × {quantity} {unit} | {total} تومان | {tracking} | #{order_id} | {status}",
            order,
        )
        self.assertIn("علی سلام", text)
        self.assertIn("اسانس یاس × 2 میل", text)
        self.assertIn("300,000 تومان", text)
        self.assertIn("RA123", text)
        self.assertIn("#7", text)
        self.assertIn("ارسال شد", text)
        self.assertNotIn("{", text)  # همه متغیرها جایگزین شدند

    def test_render_keeps_unknown_placeholders_intact(self):
        order = SimpleNamespace(
            product_name="X", quantity=1, unit="عدد", total_price=10,
            tracking_code="", recipient_name="Y", id=1, status="confirmed",
        )
        text = ons.render_template("{unknown} {recipient}", order)
        self.assertIn("{unknown}", text)
        self.assertIn("Y", text)

    def test_render_shows_dash_when_tracking_missing(self):
        order = SimpleNamespace(
            product_name="X", quantity=1, unit="عدد", total_price=10,
            tracking_code="", recipient_name="Y", id=1, status="confirmed",
        )
        self.assertIn("—", ons.render_template("{tracking}", order))

    def test_get_template_falls_back_to_default(self):
        bot = SimpleNamespace(order_notify_confirmed=None, order_notify_shipped="  ",
                              order_notify_cancelled="متن سفارشی")
        self.assertEqual(ons.get_template(bot, "confirmed"), ons.DEFAULT_TEMPLATES["confirmed"])
        self.assertEqual(ons.get_template(bot, "shipped"), ons.DEFAULT_TEMPLATES["shipped"])
        self.assertEqual(ons.get_template(bot, "cancelled"), "متن سفارشی")


class WindowTests(unittest.TestCase):
    def setUp(self):
        self.db = _make_session()

    def tearDown(self):
        self.db.rollback()
        self.db.close()

    def test_no_customer_message_means_window_closed(self):
        order = _seed(self.db, with_message=False)
        self.assertFalse(ons.within_messaging_window(self.db, order.customer_id))
        self.assertIsNone(ons.last_customer_message_at(self.db, order.customer_id))

    def test_recent_message_opens_window(self):
        order = _seed(self.db, message_age_hours=1)
        self.assertTrue(ons.within_messaging_window(self.db, order.customer_id))

    def test_old_message_closes_window(self):
        order = _seed(self.db, message_age_hours=25)
        self.assertFalse(ons.within_messaging_window(self.db, order.customer_id))

    def test_only_customer_messages_count(self):
        order = _seed(self.db, with_message=False)
        self.db.add(Message(customer_id=order.customer_id, text="پاسخ ربات", sender="bot",
                            created_at=datetime.utcnow()))
        self.db.commit()
        self.assertFalse(ons.within_messaging_window(self.db, order.customer_id))


class NotifyOrderStatusTests(unittest.TestCase):
    def setUp(self):
        self.db = _make_session()
        _reset_notify_settings(self.db)

    def tearDown(self):
        self.db.rollback()
        self.db.close()

    def _notify(self, order_id):
        return ons.notify_order_status(self.db, order_id)

    def test_successful_send_marks_notified(self):
        order = _seed(self.db, status="confirmed")
        with patch.object(instagram_client, "find_conversation_id", return_value="t-1"), \
                patch.object(instagram_client, "send_direct_message_with_retry", return_value=True) as mock_send:
            result = self._notify(order.id)
        self.assertEqual(result, "sent")
        mock_send.assert_called_once()
        sent_text = mock_send.call_args.kwargs.get("text") or mock_send.call_args.args[0]
        self.assertIn("اسانس یاس", sent_text)
        self.assertIn("300,000", sent_text)
        self.db.refresh(order)
        self.assertFalse(order.notify_pending)
        self.assertEqual(order.notified_status, "confirmed")
        self.assertIsNone(order.notify_error)

    def test_shipped_notification_contains_tracking_code(self):
        order = _seed(self.db, status="shipped", tracking_code="RA999")
        with patch.object(instagram_client, "find_conversation_id", return_value=None), \
                patch.object(instagram_client, "send_direct_message_with_retry", return_value=True) as mock_send:
            result = self._notify(order.id)
        self.assertEqual(result, "sent")
        sent_text = mock_send.call_args.kwargs.get("text") or mock_send.call_args.args[0]
        self.assertIn("RA999", sent_text)

    def test_outside_window_queues_without_sending(self):
        order = _seed(self.db, status="confirmed", with_message=False, notify_pending=True)
        with patch.object(instagram_client, "send_direct_message_with_retry", return_value=True) as mock_send:
            result = self._notify(order.id)
        self.assertEqual(result, "queued_window")
        mock_send.assert_not_called()
        self.db.refresh(order)
        self.assertTrue(order.notify_pending)
        self.assertIn("پنجره", order.notify_error)

    def test_disabled_setting_clears_pending_without_send(self):
        order = _seed(self.db, status="confirmed", notify_pending=True)
        bot = get_bot_settings(self.db)
        bot.order_notify_enabled = False
        self.db.commit()
        with patch.object(instagram_client, "send_direct_message_with_retry", return_value=True) as mock_send:
            result = self._notify(order.id)
        self.assertEqual(result, "disabled")
        mock_send.assert_not_called()
        self.db.refresh(order)
        self.assertFalse(order.notify_pending)

    def test_already_notified_is_skipped(self):
        order = _seed(self.db, status="confirmed", notified_status="confirmed")
        with patch.object(instagram_client, "send_direct_message_with_retry", return_value=True) as mock_send:
            result = self._notify(order.id)
        self.assertEqual(result, "already")
        mock_send.assert_not_called()

    def test_failed_send_keeps_pending_for_retry(self):
        order = _seed(self.db, status="confirmed", notify_pending=True)
        with patch.object(instagram_client, "find_conversation_id", return_value=None), \
                patch.object(instagram_client, "send_direct_message_with_retry", return_value=False):
            result = self._notify(order.id)
        self.assertEqual(result, "failed")
        self.db.refresh(order)
        self.assertTrue(order.notify_pending)
        self.assertIn("ارسال ناموفق", order.notify_error)

    def test_pending_order_outside_status_set_is_skipped(self):
        order = _seed(self.db, status="pending")
        with patch.object(instagram_client, "send_direct_message_with_retry", return_value=True) as mock_send:
            result = self._notify(order.id)
        self.assertEqual(result, "skipped")
        mock_send.assert_not_called()


class FlushPendingTests(unittest.TestCase):
    def setUp(self):
        self.db = _make_session()
        _reset_notify_settings(self.db)

    def tearDown(self):
        self.db.rollback()
        self.db.close()

    def test_old_pending_order_is_flushed(self):
        order = _seed(self.db, status="confirmed", notify_pending=True)
        order.notify_updated_at = datetime.utcnow() - timedelta(seconds=120)
        self.db.commit()
        with patch.object(instagram_client, "find_conversation_id", return_value=None), \
                patch.object(instagram_client, "send_direct_message_with_retry", return_value=True):
            sent = ons.flush_pending_notifications(db=self.db)
        self.assertEqual(sent, 1)
        self.db.refresh(order)
        self.assertFalse(order.notify_pending)
        self.assertEqual(order.notified_status, "confirmed")

    def test_recent_attempt_respects_grace_period(self):
        order = _seed(self.db, status="confirmed", notify_pending=True)
        # تلاش ارسال همین لحظه انجام شده — نباید دوباره تلاش شود
        order.notify_updated_at = datetime.utcnow()
        self.db.commit()
        with patch.object(instagram_client, "send_direct_message_with_retry", return_value=True) as mock_send:
            sent = ons.flush_pending_notifications(db=self.db)
        self.assertEqual(sent, 0)
        mock_send.assert_not_called()

    def test_never_attempted_order_flushed_immediately(self):
        # notify_updated_at خالی = هرگز تلاش نشده → باید همین چرخه برداشته شود
        order = _seed(self.db, status="confirmed", notify_pending=True)
        self.assertIsNone(order.notify_updated_at)
        with patch.object(instagram_client, "find_conversation_id", return_value=None), \
                patch.object(instagram_client, "send_direct_message_with_retry", return_value=True):
            sent = ons.flush_pending_notifications(db=self.db)
        self.assertEqual(sent, 1)
        self.db.refresh(order)
        self.assertFalse(order.notify_pending)

    def test_non_pending_orders_ignored(self):
        _seed(self.db, status="confirmed", notify_pending=False)
        with patch.object(instagram_client, "send_direct_message_with_retry", return_value=True) as mock_send:
            sent = ons.flush_pending_notifications(db=self.db)
        self.assertEqual(sent, 0)
        mock_send.assert_not_called()


class OrderStatusChangeEndpointTests(unittest.TestCase):
    """تغییر وضعیت در پنل باید اعلان را در صف بگذارد و ارسال پس‌زمینه را ماشه‌گذاری کند."""

    def setUp(self):
        from app.routers.order import router as order_router
        self.db = _make_session()
        self.order = _seed(self.db, status="pending")

        app = FastAPI()
        app.include_router(order_router)
        app.dependency_overrides[require_auth] = lambda: None
        app.dependency_overrides[get_db] = lambda: self.db
        self.client = TestClient(app)

        self.notify_patch = patch("app.routers.order.send_order_notification_task")
        self.sync_patch = patch("app.routers.order._sync_zernio_bg")
        self.mock_notify = self.notify_patch.start()
        self.sync_patch.start()

    def tearDown(self):
        self.client.close()
        self.notify_patch.stop()
        self.sync_patch.stop()
        self.db.rollback()
        self.db.close()

    def _patch(self, payload):
        return self.client.patch(f"/orders/{self.order.id}", json=payload)

    def test_confirm_queues_notification_and_fires_background_task(self):
        resp = self._patch({"version": 1, "status": "confirmed", "tracking_code": ""})
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertTrue(body["notify_pending"])
        self.mock_notify.assert_called_once_with(self.order.id)

    def test_ship_with_tracking_queues_notification(self):
        self._patch({"version": 1, "status": "confirmed", "tracking_code": ""})
        resp = self._patch({"version": 2, "status": "shipped", "tracking_code": "RA777"})
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()["notify_pending"])
        self.assertEqual(self.mock_notify.call_count, 2)

    def test_ship_without_tracking_rejected(self):
        self._patch({"version": 1, "status": "confirmed", "tracking_code": ""})
        resp = self._patch({"version": 2, "status": "shipped", "tracking_code": "  "})
        self.assertEqual(resp.status_code, 422)
        self.assertEqual(self.mock_notify.call_count, 1)  # فقط تأیید، بدون اعلان ارسال

    def test_invalid_transition_still_rejected(self):
        resp = self._patch({"version": 1, "status": "shipped", "tracking_code": "X"})
        self.assertEqual(resp.status_code, 409)
        self.mock_notify.assert_not_called()

    def test_version_conflict_still_rejected(self):
        self._patch({"version": 1, "status": "confirmed", "tracking_code": ""})
        resp = self._patch({"version": 1, "status": "cancelled", "tracking_code": ""})
        self.assertEqual(resp.status_code, 409)
        self.assertEqual(self.mock_notify.call_count, 1)

    def test_list_orders_exposes_notify_fields(self):
        resp = self.client.get("/orders/")
        self.assertEqual(resp.status_code, 200)
        item = resp.json()[0]
        for key in ("notify_pending", "notified_status", "notify_error", "notify_updated_at"):
            self.assertIn(key, item)


class SettingsNotifyFieldsTests(unittest.TestCase):
    def setUp(self):
        from app.routers.settings import update_settings
        self._update_settings = update_settings
        self.db = _make_session()
        _reset_notify_settings(self.db)

    def tearDown(self):
        self.db.rollback()
        self.db.close()

    def test_templates_round_trip_and_empty_restores_default(self):
        result = self._update_settings(
            BotSettingUpdate(
                order_notify_enabled=False,
                order_notify_confirmed="متن تأیید سفارشی",
                order_notify_shipped="متن ارسال سفارشی",
            ),
            BackgroundTasks(),
            self.db,
        )
        self.assertFalse(result.order_notify_enabled)
        self.assertEqual(result.order_notify_confirmed, "متن تأیید سفارشی")
        self.assertEqual(result.order_notify_shipped, "متن ارسال سفارشی")

        # متن خالی → بازگشت به پیش‌فرض
        result2 = self._update_settings(
            BotSettingUpdate(order_notify_confirmed=""),
            BackgroundTasks(),
            self.db,
        )
        self.assertIsNone(result2.order_notify_confirmed)
        bot = get_bot_settings(self.db)
        self.assertEqual(ons.get_template(bot, "confirmed"), ons.DEFAULT_TEMPLATES["confirmed"])

    def test_other_settings_untouched_by_partial_update(self):
        bot = get_bot_settings(self.db)
        original_fallback = bot.fallback_message
        self._update_settings(
            BotSettingUpdate(order_notify_cancelled="متن لغو"),
            BackgroundTasks(),
            self.db,
        )
        bot2 = get_bot_settings(self.db)
        self.assertEqual(bot2.fallback_message, original_fallback)
        self.assertEqual(bot2.order_notify_cancelled, "متن لغو")
        self.assertTrue(bot2.order_notify_enabled)  # پیش‌فرض روشن


if __name__ == "__main__":
    unittest.main()
