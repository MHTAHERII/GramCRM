import logging
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from app.service.ws_manager import ws_manager
from app.auth import SESSION_KEY

logger = logging.getLogger("ws_router")
router = APIRouter(tags=["WebSocket"])


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """
    اندپوینت ارتباط زنده وب‌سوکت برای ارسال بلادرنگ رویدادها، پیام‌ها و لاگ‌ها به پنل
    """
    await ws_manager.connect(websocket)
    try:
        while True:
            # دریافت پیام‌های ارسالی از سمت کلاینت (مثل پینگ هارت‌بیت)
            data = await websocket.receive_json()
            if isinstance(data, dict) and data.get("type") == "ping":
                await websocket.send_json({"type": "pong"})
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket)
    except Exception as e:
        logger.debug(f"WebSocket client error: {e}")
        ws_manager.disconnect(websocket)
