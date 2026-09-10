from typing import List

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.product import Product
from app.schemas.product import (ProductCreate, ProductUpdate, ProductResponce)

router = APIRouter(prefix="/product", tags=["product"])


@router.post("/products")
def create_product(product: ProductCreate, db: Session = Depends(get_db)):
    new_product = Product(name=product.name,
                          description=product.description,
                          price=product.price,
                          stock=product.stock
                          )
    db.add(new_product)
    db.commit()
    db.refresh(new_product)
    return new_product


@router.get("/products", response_model=List[ProductResponce])
def get_products(db: Session = Depends(get_db)):
    return db.query(Product).all()


@router.get("/products/{id}", response_model=ProductResponce)
def get_product(id: int, db: Session = Depends(get_db)):
    product = db.query(Product).filter(Product.id == id).first()
    if not product:
        return {"message": "product not found"}
    return product


@router.put("/products/{id}")
def update_product(product_id: int, product_data: ProductUpdate, db: Session = Depends(get_db)):
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        return {"message": "product not found"}
    product.name = product_data.name
    product.description = product_data.description
    product.price = product_data.price
    product.stock = product_data.stock
    db.commit()
    db.refresh(product)
    return product


@router.delete("/products/{id}")
def delete_product(id: int, db: Session = Depends(get_db)):
    product = db.query(Product).filter(Product.id == id).first()
    if not product:
        return {"message": "product not found"}
    db.delete(product)
    db.commit()
    return {"message": "product deleted"}
