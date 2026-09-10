from fastapi import FastAPI, Depends
from app.database import engine, Base
from app.routers.product import router as product_router
from app.routers.customer import router as customer_router
from app.routers.message import router as message_router
app = FastAPI()
Base.metadata.create_all(bind=engine)
app.include_router(product_router)
app.include_router(customer_router)
app.include_router(message_router)

@app.get("/")
def root():
    return {"message": "Perfume bot API is running"}



