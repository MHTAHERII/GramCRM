from pydantic import BaseModel# برای اعتبار سنجی و مدیریت داده ها استفاده میشه

class ProductCreate(BaseModel):
    name : str
    price : int
    stock : int
    description : str

class ProductResponse(ProductCreate):
    id : int
    active : bool

    class Config:
        from_attributes = True #پیدنتیک میفهمه ک باید مقادیر رو از ویژگی های آبجکت بخونه

class ProductUpdate(BaseModel):
    name : str | None = None
    description : str | None = None
    price : int | None = None
    stock : int | None = None



