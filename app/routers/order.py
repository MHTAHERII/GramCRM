from datetime import datetime

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, UploadFile, File, Response
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth import require_auth
from app.database import get_db
from app.models.customer import Customer
from app.models.product import Product
from app.models.order import Order
from app.schemas.order import OrderCreate, OrderUpdate, OrderResponse
from app.routers.keyword import _sync_zernio_bg


router = APIRouter(prefix="/orders", tags=["Orders"], dependencies=[Depends(require_auth)])


@router.get("/", response_model=list[OrderResponse])
def list_orders(offset: int = 0, db: Session = Depends(get_db)):
    return db.query(Order).order_by(Order.id.desc()).offset(max(offset, 0)).limit(100).all()


@router.post("/", response_model=OrderResponse)
def create_order(data: OrderCreate, db: Session = Depends(get_db)):
    existing = db.query(Order).filter(Order.request_key == str(data.request_key)).first()
    if existing:
        return existing
    if not db.get(Customer, data.customer_id):
        raise HTTPException(404, "مشتری پیدا نشد")
    product = db.get(Product, data.product_id)
    if not product or not product.active:
        raise HTTPException(404, "محصول فعال پیدا نشد")
    if product.stock < data.quantity:
        raise HTTPException(409, "موجودی محصول کافی نیست")
    order = Order(**data.model_dump(exclude={"request_key"}), request_key=str(data.request_key),
                  product_name=product.name, unit=product.unit, unit_price=product.price,
                  total_price=product.price * data.quantity)
    db.add(order)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = db.query(Order).filter(Order.request_key == str(data.request_key)).first()
        if existing:
            return existing
        raise
    db.refresh(order)
    return order


@router.patch("/{order_id}", response_model=OrderResponse)
def update_order(order_id: int, data: OrderUpdate, background_tasks: BackgroundTasks,
                 db: Session = Depends(get_db)):
    order = db.get(Order, order_id)
    if not order:
        raise HTTPException(404, "سفارش پیدا نشد")
    transitions = {"pending": {"confirmed", "cancelled"}, "confirmed": {"shipped", "cancelled"},
                   "shipped": set(), "cancelled": set()}
    if order.version != data.version:
        raise HTTPException(409, "سفارش تغییر کرده است؛ فهرست را بازخوانی کنید")
    if data.status != order.status and data.status not in transitions[order.status]:
        raise HTTPException(409, "این تغییر وضعیت مجاز نیست")
    if data.status == "shipped" and not data.tracking_code.strip():
        raise HTTPException(422, "کد پیگیری ارسال را وارد کنید")
    previous_status = order.status
    product_id, quantity = order.product_id, order.quantity
    changed = db.query(Order).filter(Order.id == order_id, Order.version == data.version).update({
        Order.status: data.status, Order.tracking_code: data.tracking_code.strip(),
        Order.version: Order.version + 1, Order.updated_at: datetime.utcnow(),
    }, synchronize_session=False)
    if changed != 1:
        db.rollback()
        raise HTTPException(409, "سفارش هم‌زمان تغییر کرده است؛ دوباره بازخوانی کنید")
    stock_changed = False
    if previous_status == "pending" and data.status == "confirmed":
        changed = db.query(Product).filter(Product.id == product_id, Product.stock >= quantity,
                                           Product.active.is_(True)).update(
            {Product.stock: Product.stock - quantity}, synchronize_session=False)
        if changed != 1:
            db.rollback()
            raise HTTPException(409, "موجودی برای تأیید سفارش کافی نیست")
        stock_changed = True
    elif previous_status == "confirmed" and data.status == "cancelled":
        db.query(Product).filter(Product.id == product_id).update(
            {Product.stock: Product.stock + quantity}, synchronize_session=False)
        stock_changed = True
    db.commit()
    db.refresh(order)
    if stock_changed:
        background_tasks.add_task(_sync_zernio_bg)
    return order


@router.post("/{order_id}/receipt", response_model=OrderResponse)
def upload_receipt(order_id: int, file: UploadFile = File(...), db: Session = Depends(get_db)):
    order = db.get(Order, order_id)
    if not order:
        raise HTTPException(404, "سفارش پیدا نشد")
    content = file.file.read(5 * 1024 * 1024 + 1)
    if len(content) > 5 * 1024 * 1024:
        raise HTTPException(413, "حداکثر حجم رسید ۵ مگابایت است")
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        mime = "image/png"
    elif content.startswith(b"\xff\xd8\xff"):
        mime = "image/jpeg"
    else:
        raise HTTPException(422, "رسید باید تصویر PNG یا JPG باشد")
    order.receipt_data, order.receipt_type = content, mime
    db.commit()
    db.refresh(order)
    return order


@router.get("/{order_id}/receipt")
def download_receipt(order_id: int, db: Session = Depends(get_db)):
    order = db.get(Order, order_id)
    if not order or not order.receipt_data:
        raise HTTPException(404, "رسید پیدا نشد")
    extension = "png" if order.receipt_type == "image/png" else "jpg"
    return Response(order.receipt_data, media_type=order.receipt_type, headers={
        "Content-Disposition": f'attachment; filename="receipt-{order.id}.{extension}"',
        "X-Content-Type-Options": "nosniff", "Cache-Control": "no-store",
    })
