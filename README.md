# 🚀 Perfume CRM API

> ⚠️ **Status:** In Progress / Learning Project

A backend REST API + admin panel built with **FastAPI** and **PostgreSQL** for managing Instagram DMs of a perfume (fragrance materials) shop: auto-replies by keywords, conversation inbox, products, and bot settings.

---

## 📚 Overview

- REST API with clean layered architecture (Models / Schemas / Routers / Services)
- Instagram DM worker (instagrapi) that polls unread messages and auto-replies
- **Admin panel** (Persian, RTL) served at `/panel` — no frontend build tools needed

---

## 🛠 Tech Stack

- **Framework:** FastAPI (Python 3)
- **Database:** PostgreSQL — **ORM:** SQLAlchemy — **Validation:** Pydantic
- **Instagram:** instagrapi
- **Panel:** plain HTML/CSS/JS (Vazirmatn font, RTL)

---

## 🏗 Project Architecture

```text
app/
├── models/         # SQLAlchemy models (customer, message, keyword, product, bot_setting)
├── schemas/        # Pydantic validation schemas
├── routers/        # API endpoints (customer, message, keyword, product, settings, auth)
├── service/        # Business logic
│   ├── instagram_service.py   # instagrapi client (login, fetch/send DMs)
│   ├── chat_service.py        # inbound message pipeline
│   ├── reply_engine.py        # keyword matching engine
│   └── bot_settings.py        # bot on/off + fallback message
├── static/panel/   # Admin panel (HTML/CSS/JS)
├── auth.py         # session login + require_auth dependency
├── worker.py       # DM polling worker (async background task)
├── database.py     # engine & session
├── config.py       # .env settings
└── main.py         # entry point
```

### Flow
```text
Instagram DM ──► worker (poll) ──► chat_service ──► reply_engine (keywords) ──► reply sent + saved
Admin panel ──► FastAPI (session auth) ──► same API ──► PostgreSQL
```

---

## 💡 Features

- **Keywords:** CRUD + enable/disable toggle; exact match first, then partial match (longer keywords win)
- **Conversations inbox:** customer list + chat history + manual reply (sent as admin)
- **Bot settings:** on/off switch (off = messages saved but no auto-reply), editable fallback message
- **Products:** full CRUD
- **Auth:** password login (session cookie); all API routers protected
- **Idempotent startup migration** for schema fixes

---

## ▶️ Getting Started

### 1. Install Dependencies
```bash
pip install -r requirements.txt
```

### 2. Configure Environment
Copy `.env.example` style settings into `.env`:
```env
DATABASE_URL=postgresql://<user>:<password>@localhost:5432/perfume_bot
IG_USERNAME=your_page_username
IG_PASSWORD=your_page_password
IG_SESSION_FILE=session.json
IG_POLL_INTERVAL=15
ENABLE_IG_WORKER=true
ADMIN_PASSWORD=your-panel-password
ADMIN_SESSION_SECRET=a-long-random-string
```
> To run the API without touching Instagram (e.g. only for the panel), set `ENABLE_IG_WORKER=false`.

### 3. Run the Server
```bash
uvicorn app.main:app --reload
```

### 4. Open the Panel & Docs
- **Admin Panel:** `http://127.0.0.1:8000/panel` (login with `ADMIN_PASSWORD`)
- **Swagger UI:** `http://127.0.0.1:8000/docs`

---

## 👨‍💻 Author

**MH TAHERI**
