from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.message import Message
from app.schemas.message import MessageCreate, MessageResponse


router = APIRouter(
    prefix="/messages",
    tags=["Messages"]
)


# Create Message
@router.post("/", response_model=MessageResponse)
def create_message(
    message: MessageCreate,
    db: Session = Depends(get_db)
):
    new_message = Message(
        customer_id=message.customer_id,
        text=message.text,
        sender=message.sender
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