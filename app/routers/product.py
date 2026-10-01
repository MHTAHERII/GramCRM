from typing import List

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.orm import Session

from app.auth import require_auth
from app.database import get_db
from app.models.product import Product
from app.models.keyword import Keyword
from app.models.order import Order
from app.routers.keyword import _sync_zernio_bg
from app.schemas.product import ProductCreate, ProductUpdate, ProductResponse

router = APIRouter(prefix="/products", tags=["Products"], dependencies=[Depends(require_auth)])


@router.post("/", response_model=ProductResponse)
def create_product(product: ProductCreate, db: Session = Depends(get_db)):
    new_product = Product(
        name=product.name,
        description=product.description,
        price=product.price,
        stock=product.stock
        , unit=product.unit
    )
    db.add(new_product)
    db.commit()
    db.refresh(new_product)
    return new_product


@router.get("/", response_model=List[ProductResponse])
def get_products(db: Session = Depends(get_db)):
    return db.query(Product).all()


@router.get("/{product_id}", response_model=ProductResponse)
def get_product(product_id: int, db: Session = Depends(get_db)):
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    return product


@router.put("/{product_id}", response_model=ProductResponse)
def update_product(product_id: int, product_data: ProductUpdate, background_tasks: BackgroundTasks,
                   db: Session = Depends(get_db)):
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    # فقط فیلدهایی که در درخواست ارسال شده‌اند به‌روزرسانی می‌شوند
    if product_data.name is not None:
        product.name = product_data.name
    if product_data.description is not None:
        product.description = product_data.description
    if product_data.price is not None:
        product.price = product_data.price
    if product_data.stock is not None:
        product.stock = product_data.stock
    if product_data.unit is not None:
        if not product_data.unit.strip():
            raise HTTPException(422, "واحد نمی‌تواند خالی باشد")
        product.unit = product_data.unit.strip()

    db.commit()
    db.refresh(product)
    background_tasks.add_task(_sync_zernio_bg)
    return product


@router.delete("/{product_id}")
def delete_product(product_id: int, db: Session = Depends(get_db)):
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    if db.query(Keyword).filter(Keyword.product_id == product_id).first() or db.query(Order).filter(Order.product_id == product_id).first():
        raise HTTPException(409, "محصول به کلیدواژه یا سفارش متصل است و قابل حذف نیست")
    db.delete(product)
    db.commit()
    return {"message": "product deleted"}
