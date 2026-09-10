from pydantic import BaseModel
from datetime import datetime

class CustomerCreate(BaseModel):#اطلاعاتی ک از کاربر میاد
    instagram_id:str
    username:str | None=None
    name:str | None=None

class CustomerResponse(CustomerCreate):# اطلاعاتی ک api برمیگردونه
    id: int
    created_at : datetime

    class Confid:
        from_attributes = True

class CustomerUpdate(BaseModel):
    username: str | None = None
    name: str | None = None