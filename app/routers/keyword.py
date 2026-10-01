from typing import List
import requests

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth import require_auth
from app.database import get_db, SessionLocal
from app.models.keyword import Keyword
from app.models.product import Product
from app.service.product_response import render_product_response
from app.schemas.keyword import (
    KeywordCreate,
    KeywordUpdate,
    KeywordResponse
)
from app.service.zernio_service import zernio_service
from app.service.keyword_diagnostics import keyword_delivery_statuses, preview_comment

router = APIRouter(
    prefix="/keywords",
    tags=["Keywords"],
    dependencies=[Depends(require_auth)]
)


class KeywordPreviewRequest(BaseModel):
    product_id: int | None = None
    text: str = Field(min_length=1, max_length=2000)
    keyword: str = Field(min_length=1, max_length=100)
    response: str = Field(min_length=1, max_length=640)
    comment_reply: str | None = Field(default=None, max_length=640)
    editing_id: int | None = None
    draft_active: bool = True


def _sync_zernio_bg():
    """همگام‌سازی کلیدواژه‌ها با Zernio در پس‌زمینه بدون معطل کردن کاربر"""
    db = None
    try:
        db = SessionLocal()
        zernio_service.sync_all_keywords(db)
    except Exception as e:
        import logging
        logging.getLogger("keyword_router").error(f"Failed to auto-sync to Zernio: {e}")
    finally:
        if db is not None:
            db.close()


@router.post("/", response_model=KeywordResponse)
def create_keyword(
    keyword: KeywordCreate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db)
):
    if keyword.product_id is not None and not db.get(Product, keyword.product_id):
        raise HTTPException(404, "محصول پیدا نشد")
    exists = (
        db.query(Keyword)
        .filter(Keyword.keyword == keyword.keyword.strip())
        .first()
    )
    if exists:
        raise HTTPException(status_code=409, detail="این کلیدواژه قبلاً ثبت شده است")

    btn_list = []
    if keyword.buttons:
        for b in keyword.buttons[:3]:
            t = b.title.strip()
            u = (b.url or "").strip()
            b_type = getattr(b, "type", "url") or "url"
            if t and (u or b_type == "postback"):
                btn_list.append({"title": t, "url": u, "type": b_type})
    elif keyword.button_title and keyword.button_url:
        btn_list.append({"title": keyword.button_title.strip(), "url": keyword.button_url.strip(), "type": "url"})

    new_keyword = Keyword(
        product_id=keyword.product_id,
        keyword=keyword.keyword.strip(),
        response=keyword.response.strip(),
        comment_reply=(keyword.comment_reply or "").strip() or None,
        buttons=btn_list if btn_list else None,
        button_title=btn_list[0]["title"] if btn_list else None,
        button_url=btn_list[0]["url"] if btn_list else None
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


@router.post("/preview", summary="پیش‌نمایش محلی تطابق کامنت بدون ارسال پیام")
def preview_keyword(data: KeywordPreviewRequest, db: Session = Depends(get_db)):
    product = db.get(Product, data.product_id) if data.product_id is not None else None
    if data.product_id is not None and product is None:
        raise HTTPException(404, "محصول پیدا نشد")
    return preview_comment(db, data.text, data.keyword, render_product_response(data.response, product),
                           data.comment_reply, data.editing_id, data.draft_active)


@router.get("/diagnostics", summary="وضعیت واقعی دایرکت و ریپلای کامنت در زرنیو")
def get_keyword_diagnostics(db: Session = Depends(get_db)):
    try:
        return keyword_delivery_statuses(db)
    except (requests.RequestException, ValueError, TypeError):
        raise HTTPException(status_code=502, detail="استعلام وضعیت اتوماسیون‌ها از زرنیو ناموفق بود")


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

    if "product_id" in keyword_data.model_fields_set:
        if keyword_data.product_id is not None and not db.get(Product, keyword_data.product_id):
            raise HTTPException(404, "محصول پیدا نشد")
        keyword.product_id = keyword_data.product_id

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

    if keyword_data.comment_reply is not None:
        keyword.comment_reply = keyword_data.comment_reply.strip() or None

    if keyword_data.buttons is not None:
        btn_list = []
        for b in keyword_data.buttons[:3]:
            t = b.title.strip()
            u = (b.url or "").strip()
            b_type = getattr(b, "type", "url") or "url"
            if t and (u or b_type == "postback"):
                btn_list.append({"title": t, "url": u, "type": b_type})
        keyword.buttons = btn_list if btn_list else None
        keyword.button_title = btn_list[0]["title"] if btn_list else None
        keyword.button_url = btn_list[0]["url"] if btn_list else None
    else:
        if keyword_data.button_title is not None:
            keyword.button_title = keyword_data.button_title.strip() if keyword_data.button_title.strip() else None
        if keyword_data.button_url is not None:
            keyword.button_url = keyword_data.button_url.strip() if keyword_data.button_url.strip() else None
        if keyword.button_title and keyword.button_url:
            keyword.buttons = [{"title": keyword.button_title, "url": keyword.button_url}]
        elif keyword_data.button_title == "" or keyword_data.button_url == "":
            keyword.buttons = None

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
