from pydantic import BaseModel, Field, field_validator

class ProductCreate(BaseModel):
    name : str = Field(min_length=1, max_length=150)
    price : int = Field(ge=0, le=2_000_000_000)
    stock : int = Field(ge=0, le=2_000_000_000)
    description : str
    unit: str = Field(default="عدد", min_length=1, max_length=30)

    @field_validator("name", "unit")
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError("این فیلد نمی‌تواند خالی باشد")
        return value.strip()

class ProductResponse(ProductCreate):
    id : int
    active : bool

    class Config:
        from_attributes = True #پیدنتیک میفهمه ک باید مقادیر رو از ویژگی های آبجکت بخونه

class ProductUpdate(BaseModel):
    name : str | None = None
    description : str | None = None
    price : int | None = Field(default=None, ge=0, le=2_000_000_000)
    stock : int | None = Field(default=None, ge=0, le=2_000_000_000)
    unit: str | None = Field(default=None, min_length=1, max_length=30)



