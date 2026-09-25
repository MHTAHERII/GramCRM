from typing import List
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.auth import require_auth
from app.database import get_db
from app.models.customer import Customer
from app.models.message import Message
from app.schemas.message import MessageCreate, MessageResponse, ConversationResponse


router = APIRouter(
    prefix="/messages",
    tags=["Messages"],
    dependencies=[Depends(require_auth)]
)

conversations_router = APIRouter(
    prefix="/conversations",
    tags=["Conversations"],
    dependencies=[Depends(require_auth)]
)


@conversations_router.get("/", response_model=List[ConversationResponse])
def get_conversations(db: Session = Depends(get_db)):
    """لیست گفتگوها برای صندوق پنل: بهینه‌سازی‌شده در ۲ کوئری فوق‌سریع بدون N+1"""
    customers = db.query(Customer).all()
    if not customers:
        return []

    # استخراج آخرین پیام هر مشتری در ۱ کوئری فوق‌سریع
    subq = (
        db.query(
            Message.customer_id,
            func.max(Message.id).label("max_id")
        )
        .group_by(Message.customer_id)
        .subquery()
    )
    last_messages = db.query(Message).join(subq, Message.id == subq.c.max_id).all()
    last_msg_map = {m.customer_id: m for m in last_messages}

    conversations = [
        {
            "customer": cust,
            "last_message": last_msg_map.get(cust.id)
        }
        for cust in customers
    ]

    # گفتگوهای دارای پیام از تازه‌ترین، بقیه در انتها
    conversations.sort(
        key=lambda c: (
            c["last_message"].created_at if c["last_message"] else datetime.min
        ),
        reverse=True,
    )
    return conversations


# Create Message
@router.post("/", response_model=MessageResponse)
def create_message(
    message: MessageCreate,
    db: Session = Depends(get_db)
):
    new_message = Message(
        customer_id=message.customer_id,
        text=message.text,
        sender=message.sender,
        instagram_message_id=message.instagram_message_id
    )

    db.add(new_message)
    db.commit()
    db.refresh(new_message)

    return new_message


# Get All Messages
@router.get("/", response_model=List[MessageResponse])
def get_messages(
    db: Session = Depends(get_db)
):
    return db.query(Message).all()


# Get Message By ID
@router.get("/{message_id}", response_model=MessageResponse)
def get_message(
    message_id: int,
    db: Session = Depends(get_db)
):
    message = (
        db.query(Message)
        .filter(Message.id == message_id)
        .first()
    )

    if not message:
        raise HTTPException(
            status_code=404,
            detail="Message not found"
        )

    return message