import logging

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from typing import List
from app.auth import require_auth
from app.database import get_db
from app.models.customer import Customer
from app.models.message import Message
from app.schemas.customer import CustomerCreate, CustomerResponse, ManualSendRequest
from app.schemas.message import MessageResponse
from fastapi import HTTPException
from app.schemas.customer import (
    CustomerCreate,
    CustomerResponse,
    CustomerUpdate
)

router = APIRouter(
    prefix="/customers",
    tags=["Customers"],
    dependencies=[Depends(require_auth)]
)
logger = logging.getLogger(__name__)
#prefix: بخش مشترک url های این router
#tags: در swagger با چه عنوانی گروهبندی بشن

@router.post("/", response_model=CustomerResponse)
def create_customer(
    customer: CustomerCreate,
    db: Session = Depends(get_db)
):
    new_customer = Customer(
        instagram_id=customer.instagram_id,
        username=customer.username,
        name=customer.name
    )

    db.add(new_customer)
    db.commit()
    db.refresh(new_customer)

    return new_customer

@router.get("/", response_model=List[CustomerResponse])
def get_customers(
    db: Session = Depends(get_db)
):
    return db.query(Customer).all()

@router.get("/{customer_id}", response_model=CustomerResponse)
def get_customer(
    customer_id: int,
    db: Session = Depends(get_db)
):
    customer = (
        db.query(Customer)
        .filter(Customer.id == customer_id)
        .first()#اولین رکوردی ک پیدا شد رو برگردون اگه چیزی پیدا نشد none رو برگردون
    )

    if not customer:
        raise HTTPException(
            status_code=404,
            detail="Customer not found"
        )
    return customer

@router.put("/{customer_id}", response_model=CustomerResponse)
def update_customer(
    customer_id: int,
    customer_data: CustomerUpdate,
    db: Session = Depends(get_db)
):

    customer = (
        db.query(Customer)
        .filter(Customer.id == customer_id)
        .first()
    )

    if not customer:
        raise HTTPException(
            status_code=404,
            detail="Customer not found"
        )

    if customer_data.username is not None:
        customer.username = customer_data.username

    if customer_data.name is not None:
        customer.name = customer_data.name

    db.commit()
    db.refresh(customer)

    return customer

@router.delete("/{customer_id}")
def delete_customer(
        customer_id: int,
        db: Session = Depends(get_db)
):
    customer = db.query(Customer).filter(Customer.id==customer_id).first()
    if not customer:
        raise HTTPException(
            status_code=404,
            detail="Customer not found"
        )
    db.delete(customer)
    db.commit()
    return {"message": "customer deleted"}


@router.get("/{customer_id}/messages", response_model=List[MessageResponse])
def get_customer_messages(
        customer_id: int,
        db: Session = Depends(get_db)
):
    """تاریخچه کامل رد و بدل شده با یک مشتری (کوئری مستقیم با ایندکس بدون کوئری اضافه)"""
    return (
        db.query(Message)
        .filter(Message.customer_id == customer_id)
        .order_by(Message.created_at.asc(), Message.id.asc())
        .limit(250)
        .all()
    )


@router.post("/{customer_id}/send")
def send_manual_message(
        customer_id: int,
        payload: ManualSendRequest,
        db: Session = Depends(get_db)
):
    """ارسال پاسخ دستی از پنل؛ پیام به دایرکت اینستاگرام ارسال و در سوابق ثبت می‌شود"""
    customer = _get_customer_or_404(db, customer_id)
    text = payload.text.strip()
    if not text:
        raise HTTPException(status_code=400, detail="متن پیام نمی‌تواند خالی باشد")

    # ایمپورت داخل تابع تا بدون اینستاگرام هم بقیه API بالا بیاید
    from app.service.instagram_service import instagram_client

    # پیدا کردن conversation ID از Zernio با بررسی سریع کش حافظه
    conv_id = instagram_client.find_conversation_id(customer.instagram_id)
    if conv_id:
        sent = instagram_client.send_direct_message(text=text, thread_id=conv_id)
    else:
        # فالبک: تلاش مستقیم با instagram_id
        sent = instagram_client.send_direct_message(text=text, user_id=customer.instagram_id)

    if not sent:
        logger.warning(f"ارسال دستی به مشتری {customer.id} در اینستاگرام ناموفق بود.")

    outbound = Message(
        customer_id=customer.id,
        text=text,
        sender="admin"
    )
    db.add(outbound)
    db.commit()
    db.refresh(outbound)

    # اطلاع‌رسانی بلادرنگ به پنل
    try:
        from app.service.ws_manager import ws_manager
        ws_manager.broadcast_sync("new_message", {
            "message": {
                "id": outbound.id,
                "customer_id": customer.id,
                "text": outbound.text,
                "sender": outbound.sender,
                "created_at": outbound.created_at.isoformat() if outbound.created_at else None
            },
            "customer": {
                "id": customer.id,
                "name": customer.name,
                "username": customer.username,
                "instagram_id": customer.instagram_id
            }
        })
    except Exception as e:
        logger.debug(f"WS manual message broadcast failed: {e}")

    return {
        "sent": sent,
        "detail": "پیام ارسال شد" if sent else "ارسال به اینستاگرام ناموفق بود ولی در سوابق ثبت شد",
        "message": {
            "id": outbound.id,
            "customer_id": outbound.customer_id,
            "text": outbound.text,
            "sender": outbound.sender,
            "created_at": outbound.created_at.isoformat() if outbound.created_at else None
        }
    }


def _get_customer_or_404(db: Session, customer_id: int) -> Customer:
    customer = db.query(Customer).filter(Customer.id == customer_id).first()
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")
    return customer
