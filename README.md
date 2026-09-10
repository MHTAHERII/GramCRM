# 🚀 Perfume CRM API

> ⚠️ **Status:** In Progress / Learning Project

A backend REST API built with **FastAPI** and **PostgreSQL**, designed with a clean layered architecture (**Models**, **Schemas**, **Routers**) for managing a perfume store CRM and bot interactions.

---

## 📚 Overview

This project is developed to practice modern backend engineering concepts, including:
- Modular application architecture
- Database modeling and relational ORM
- Request/Response validation and serialization
- Dependency injection

---

## 🛠 Tech Stack

- **Framework:** FastAPI (Python 3)
- **Database:** PostgreSQL
- **ORM:** SQLAlchemy
- **Data Validation:** Pydantic
- **Server:** Uvicorn (ASGI)
- **Docs:** Swagger UI & ReDoc

---

## 🏗 Project Architecture

The codebase follows a modular layered structure:

```text
app/
├── models/         # SQLAlchemy database models
│   ├── customer.py
│   ├── message.py
│   └── product.py
├── schemas/        # Pydantic validation schemas
│   ├── customer.py
│   ├── message.py
│   └── product.py
├── routers/        # API route handlers & endpoints
│   ├── customer.py
│   ├── message.py
│   └── product.py
├── database.py     # Database connection & session setup
└── main.py         # Application entry point
```

### Flow
```text
Client ──► FastAPI Router ──► Pydantic Schema (Validation) ──► SQLAlchemy (ORM) ──► PostgreSQL
```

---

## 💡 Key Features & Concepts

- **Layered Architecture:** Clear separation between data models, validation schemas, and route controllers.
- **CRUD Operations:** Complete endpoints for managing products, customer profiles, and chat messages.
- **Relational Data:** Foreign key relationships between customers and their conversation history.
- **Dependency Injection:** Database sessions managed safely per request via `get_db`.
- **Interactive Documentation:** Automatic OpenAPI documentation generated out of the box.

---

## ▶️ Getting Started

### 1. Install Dependencies
```bash
pip install -r requirements.txt
```

### 2. Configure Database
Set your PostgreSQL credentials in `app/database.py`:
```python
DATABASE_URL = "postgresql://<user>:<password>@localhost:5432/perfume_bot"
```

### 3. Run the Server
```bash
uvicorn app.main:app --reload
```

### 4. API Docs
Open your browser at:
- **Swagger UI:** `http://127.0.0.1:8000/docs`
- **ReDoc:** `http://127.0.0.1:8000/redoc`

---

## 👨‍💻 Author

**MH TAHERI**
