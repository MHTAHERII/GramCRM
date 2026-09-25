from typing import List

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.orm import Session

from app.auth import require_auth
from app.database import get_db, SessionLocal
from app.models.keyword import Keyword
from app.schemas.keyword import (
    KeywordCreate,
    KeywordUpdate,
    KeywordResponse
)
from app.service.zernio_service import zernio_service

router = APIRouter(
    prefix="/keywords",
    tags=["Keywords"],
    dependencies=[Depends(require_auth)]
)


def _sync_zernio_bg():
    """همگام‌سازی کلیدواژه‌ها با Zernio در پس‌زمینه بدون معطل کردن کاربر"""
    try:
        db = SessionLocal()
        zernio_service.sync_all_keywords(db)
    except Exception as e:
        import logging
        logging.getLogger("keyword_router").error(f"Failed to auto-sync to Zernio: {e}")
    finally:
        db.close()


@router.post("/", response_model=KeywordResponse)
def create_keyword(
    keyword: KeywordCreate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db)
):
    exists = (
        db.query(Keyword)
        .filter(Keyword.keyword == keyword.keyword.strip())
        .first()
    )
    if exists:
        raise HTTPException(status_code=409, detail="این کلیدواژه قبلاً ثبت شده است")

    new_keyword = Keyword(
        keyword=keyword.keyword.strip(),
        response=keyword.response.strip(),
        button_title=keyword.button_title.strip() if keyword.button_title else None,
        button_url=keyword.button_url.strip() if keyword.button_url else None
    )

    db.add(new_keyword)
    db.commit()
    db.refresh(new_keyword)

    background_tasks.add_task(_sync_zernio_bg)
    return new_keyword


@router.get("/", response_model=List[KeywordResponse])
def get_keywords(
    db: Session = Depends(get_db)
):
    return db.query(Keyword).all()


@router.post("/sync-zernio", summary="همگام‌سازی کلیدواژه‌ها با اتوماسیون کامنت به دایرکت Zernio")
def sync_keywords_zernio(db: Session = Depends(get_db)):
    """ارسال تمام کلیدواژه‌های فعال به Zernio برای ارسال خودکار دایرکت در صورت کامنت شدن کلیدواژه"""
    return zernio_service.sync_all_keywords(db)


@router.put("/{keyword_id}", response_model=KeywordResponse)
def update_keyword(
    keyword_id: int,
    keyword_data: KeywordUpdate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db)
):
    keyword = _get_keyword_or_404(db, keyword_id)

    if keyword_data.keyword is not None:
        stripped = keyword_data.keyword.strip()
        duplicate = (
            db.query(Keyword)
            .filter(Keyword.keyword == stripped, Keyword.id != keyword_id)
            .first()
        )
        if duplicate:
            raise HTTPException(status_code=409, detail="این کلیدواژه قبلاً ثبت شده است")
        keyword.keyword = stripped

    if keyword_data.response is not None:
        keyword.response = keyword_data.response.strip()

    if keyword_data.button_title is not None:
        keyword.button_title = keyword_data.button_title.strip() if keyword_data.button_title.strip() else None

    if keyword_data.button_url is not None:
        keyword.button_url = keyword_data.button_url.strip() if keyword_data.button_url.strip() else None

    if keyword_data.active is not None:
        keyword.active = keyword_data.active

    db.commit()
    db.refresh(keyword)

    background_tasks.add_task(_sync_zernio_bg)
    return keyword


@router.patch("/{keyword_id}/toggle", response_model=KeywordResponse)
def toggle_keyword(
    keyword_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db)
):
    keyword = _get_keyword_or_404(db, keyword_id)
    keyword.active = not keyword.active
    db.commit()
    db.refresh(keyword)

    background_tasks.add_task(_sync_zernio_bg)
    return keyword


@router.delete("/{keyword_id}")
def delete_keyword(
    keyword_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db)
):
    keyword = _get_keyword_or_404(db, keyword_id)
    db.delete(keyword)
    db.commit()

    background_tasks.add_task(_sync_zernio_bg)
    return {"message": "keyword deleted"}


def _get_keyword_or_404(db: Session, keyword_id: int) -> Keyword:
    keyword = db.query(Keyword).filter(Keyword.id == keyword_id).first()
    if not keyword:
        raise HTTPException(status_code=404, detail="Keyword not found")
    return keyword
