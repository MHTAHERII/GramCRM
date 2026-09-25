import asyncio
import logging
from typing import Any, Dict, List
from fastapi import WebSocket

logger = logging.getLogger("ws_manager")


class WebSocketManager:
    """
    مدیریت اتصالات وب‌سوکت برای ارسال بلادرنگ رویدادها (Real-Time Push)
    - رویداد پیام جدید (new_message)
    - رویداد به‌روزرسانی مکالمه (conversation_updated)
    - رویداد لاگ زنده سیستم (system_log)
    """

    def __init__(self):
        self.active_connections: List[WebSocket] = []
        self._loop: asyncio.AbstractEventLoop | None = None

    def set_loop(self, loop: asyncio.AbstractEventLoop):
        self._loop = loop

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        logger.info(f"WebSocket client connected. Active connections: {len(self.active_connections)}")

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
            logger.info(f"WebSocket client disconnected. Active connections: {len(self.active_connections)}")

    async def broadcast(self, event_type: str, data: Dict[str, Any]):
        """ارسال ناهمگام پیام به تمامی مرورگرهای متصل"""
        if not self.active_connections:
            return

        payload = {"type": event_type, "data": data}
        dead_connections = []

        for conn in list(self.active_connections):
            try:
                await conn.send_json(payload)
            except Exception as e:
                logger.debug(f"Failed to send WS message: {e}")
                dead_connections.append(conn)

        for dc in dead_connections:
            self.disconnect(dc)

    def broadcast_sync(self, event_type: str, data: Dict[str, Any]):
        """
        ارسال امن از درون توابع همگام یا نخ‌های پس‌زمینه (Worker Threads)
        """
        if not self.active_connections:
            return

        try:
            loop = self._loop
            if not loop or loop.is_closed():
                try:
                    loop = asyncio.get_running_loop()
                except RuntimeError:
                    loop = None

            if loop and loop.is_running():
                asyncio.run_coroutine_threadsafe(self.broadcast(event_type, data), loop)
            else:
                logger.debug("No running event loop found for broadcast_sync.")
        except Exception as e:
            logger.debug(f"Error in broadcast_sync: {e}")


ws_manager = WebSocketManager()
