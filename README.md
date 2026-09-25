# ⚡ GramCRM — Instagram Smart Sales Automation & CRM Platform

<div align="center">

![FastAPI](https://img.shields.io/badge/FastAPI-005571?style=for-the-badge&logo=fastapi)
![Python](https://img.shields.io/badge/Python_3.10+-3776AB?style=for-the-badge&logo=python&logoColor=white)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-316192?style=for-the-badge&logo=postgresql&logoColor=white)
![Zernio API](https://img.shields.io/badge/Zernio_API-Official_Meta-blueviolet?style=for-the-badge)
![Status](https://img.shields.io/badge/Status-Production_Ready-22c08c?style=for-the-badge)

**پلتفرم جامع مدیریت ارتباط با مشتری (CRM)، اتوماسیون هوشمند دایرکت و فروش اینستاگرام برای تمامی فروشگاه‌ها و کسب‌وکارهای آنلاین**

[ویژگی‌ها](#-ویژگی‌های-کلیدی) • [معماری](#-معماری-سیستم) • [نصب سریع روی سرور](#-راه‌اندازی-سریع-روی-سرور-vps) • [اجرای لوکال](#-راه‌اندازی-لوکال) • [مستندات API](#-مستندات-api)

</div>

---

## 📖 معرفی GramCRM

**GramCRM** یک پلتفرم نسل جدید برای اتوماسیون فروش و تعامل با مشتریان در اینستاگرام است. این سیستم طوری طراحی شده که برای هر نوع کسب‌وکار و فروشگاهی (لوازم آرایشی، پوشاک، عطر و ادکلن، اکسسوری، دوره‌های آموزشی و بیزینس‌های خدماتی) قابل استفاده و توسعه باشد.

برخلاف ربات‌های سنتی و پرریسک، GramCRM از **API رسمی و وب‌هوک‌های زنده (Event-Driven Webhooks)** استفاده می‌کند که **ریسک بن شدن یا محدودیت پیج را به صفر می‌رساند**.

علاوه بر این، دارای یک **پنل مدیریت تحت وب الترا-مدرن (Ultra-Modern Dark UI)** با پشتیبانی کامل از زبان فارسی و فونت وزیرمتن است که نیاز به هیچ ابزار بیلد یا فریم‌ورک سنگین فرانت‌اندی ندارد.

---

## ✨ ویژگی‌های کلیدی

### 🤖 ۱. اتوماسیون هوشمند دایرکت و کامنت
- **پاسخ‌دهی آنی به دایرکت‌ها (DMs):** پاسخ خودکار بر اساس کلیدواژه‌ها با پشتیبانی از نرمال‌سازی کلمات فارسی (اصلاح ی/ک، فاصله‌ها و املا).
- **اتوماسیون کامنت به دایرکت (Comment-to-DM):** ارسال خودکار دایرکت به محض کامنت شدن کلیدواژه‌ها زیر پست‌های اینستاگرام.
- **همگام‌سازی خودکار (Auto-Sync):** با ایجاد، ویرایش یا حذف هر کلیدواژه در پنل ادمین، اطلاعات به‌صورت خودکار در پس‌زمینه با سرورهای اینستاگرام/Zernio سینک می‌شود.
- **پشتیبانی از وب‌هوک و پولینگ (Hybrid):** پشتیبانی از دریافت رویداد زنده `message.received` و `comment.received` بدون تأخیر، همراه با ورکر پشتیبان.
- **رعایت پنجره مجاز ۲۴ ساعته متا:** مدیریت هوشمند محدودیت‌های پلتفرم اینستاگرام جهت جلوگیری از خطای ارسال پیام.
- **دروازه فالو (Follow Gate):** امکان الزام کاربران به فالو کردن پیج پیش از دریافت پاسخ.

### 💼 ۲. مدیریت یکپارچه CRM و فروش
- **صندوق پیام‌ها (Inbox):** مشاهده فهرست گفتگوها، سوابق چت و تبادل پیام‌ها به‌صورت زنده شبیه به اپلیکیشن‌های دسکتاپ مدرن.
- **ارسال پیام دستی (Manual Send):** امکان پاسخ مستقیم و آنی از داخل پنل مدیریت به دایرکت مشتری.
- **مدیریت محصولات:** کاتالوگ محصولات و مواد اولیه عطر، قیمت‌گذاری و وضعیت موجودی.
- **تنظیمات داینامیک:** فعال/غیرفعال کردن ربات با یک کلیک و تغییر متن پیام پیش‌فرض (Fallback) بدون نیاز به ریستارت سرور.

### 🎨 ۳. پنل مدیریت لوکس و نسل جدید (Next-Gen UI)
- طراحی شده به سبک استانداردهای مینیمال جهانی (الهام‌گرفته از Linear.app و Stripe).
- پالت رنگی Deep Slate با لهجه‌های بنفش لوکس و طلایی.
- پشتیبانی کامل از RTL و تایپوگرافی زیبای وزیرمتن (Vazirmatn).
- احراز هویت امن با کوکی‌های رمزنگاری‌شده (Session Middleware).

---

## 🏗 معماری سیستم

```text
[ کاربر در اینستاگرام ]
       │ (دایرکت یا کامنت)
       ▼
[ پلتفرم ابری Zernio (Official Meta API) ]
       │
       ├─── رویداد زنده ──► [ FastAPI Webhook (/webhook/zernio) ]
       └─── استعلام دوره‌ای ◄── [ Background Worker (Poll Cycle) ]
                                      │
                                      ▼
                        [ Chat Service & Reply Engine ]
                                      │
                 ┌────────────────────┴────────────────────┐
                 ▼                                         ▼
        [ پایگاه داده PostgreSQL ]                 [ ارسال پاسخ به کاربر ]
    (مشتریان، پیام‌ها، کلیدواژه‌ها)            (از طریق Zernio Inbox API)
```

### 📂 ساختار پوشه‌بندی:
```text
perfume-bot/
├── app/
│   ├── models/            # مدل‌های دیتابیس SQLAlchemy (مشتری، پیام، محصول، تنظیمات، کلیدواژه)
│   ├── schemas/           # اسکیماهای اعتبارسنجی Pydantic
│   ├── routers/           # اندپوینت‌های API (customer, message, product, keyword, settings, webhook)
│   │   ├── zernio_webhook.py  # روتر دریافت وب‌هوک‌های زنده دایرکت و کامنت
│   │   └── webhook.py         # روتر وب‌هوک متا
│   ├── service/           # لایه منطق بیزینس
│   │   ├── instagram_service.py # کلاینت رسمی Zernio برای ارسال و دریافت دایرکت
│   │   ├── zernio_service.py    # مدیریت اتوماسیون‌های کامنت و همگام‌سازی کلیدواژه‌ها
│   │   ├── chat_service.py      # پایپ‌لاین کامل پردازش پیام‌ها و دروازه فالو
│   │   ├── reply_engine.py      # موتور استخراج پاسخ و نرمال‌سازی فارسی
│   │   └── bot_settings.py      # مدیریت تنظیمات ربات
│   ├── static/panel/      # فرانت‌اند پنل مدیریت (HTML5, Modern CSS, JS)
│   ├── auth.py            # سیستم ورود و سشن ادمین
│   ├── worker.py          # ورکر پس‌زمینه پولینگ
│   ├── database.py        # اتصال و Session دیتابیس PostgreSQL
│   ├── config.py          # بارگذاری تنظیمات از محیط
│   └── main.py            # نقطه ورود اپلیکیشن و مایگریشن‌های خودکار
├── deploy.sh              # اسکریپت استقرار خودکار تک‌دستوری روی سرور لینوکس
├── requirements.txt       # نیازمندی‌های پایتون
└── README.md
```

---

## 🚀 راه‌اندازی سریع روی سرور (VPS)

پروژه دارای اسکریپت استقرار کاملاً خودکار است. روی یک سرور خام **Ubuntu 22.04 یا 24.04** تنها با یک دستور کل پروژه به همراه دیتابیس PostgreSQL، وب‌سرور Nginx و سرویس ۲۴ ساعته Systemd نصب و اجرا می‌شود:

```bash
curl -sSL https://raw.githubusercontent.com/MHTAHERII/Instagram-Perfume-Assistant/main/deploy.sh | bash
```

پس از اتمام:
- **پنل مدیریت:** `http://YOUR_SERVER_IP/panel`
- **آدرس وب‌هوک:** `http://YOUR_SERVER_IP/webhook/zernio`

### اتصال دامنه و SSL رایگان (HTTPS):
پس از ست کردن رکورد A دامنه به سمت آی‌پی سرور:
```bash
apt install -y certbot python3-certbot-nginx
certbot --nginx -d bot.yourdomain.com
```

---

## 💻 راه‌اندازی لوکال (Development)

### ۱. پیش‌نیازها
- پایتون 3.10 یا بالاتر
- سرور دیتابیس PostgreSQL

### ۲. کلون و نصب کتابخانه‌ها
```bash
git clone https://github.com/MHTAHERII/Instagram-Perfume-Assistant.git
cd Instagram-Perfume-Assistant

python -m venv venv
# در ویندوز:
venv\Scripts\activate
# در لینوکس/مک:
source venv/bin/activate

pip install -r requirements.txt
```

### ۳. تنظیم فایل `.env`
یک فایل `.env` در ریشه پروژه بسازید:
```env
DATABASE_URL=postgresql://postgres:password@localhost:5432/perfume_bot
ADMIN_PASSWORD=admin123
ADMIN_SESSION_SECRET=your-random-secret-key-change-me

# تنظیمات Zernio API
ENABLE_IG_WORKER=true
IG_POLL_INTERVAL=5
ZERNIO_API_KEY=your_zernio_api_key
ZERNIO_PROFILE_ID=your_profile_id
ZERNIO_ACCOUNT_ID=your_account_id
```

### ۴. اجرای سرور
```bash
uvicorn app.main:app --reload
```

- پنل مدیریت: `http://127.0.0.1:8000/panel` (رمز عبور: `admin123`)
- مستندات سواگر: `http://127.0.0.1:8000/docs`

---

## 📑 مستندات API

FastAPI به‌صورت پیش‌فرض مستندات کامل اینتراکتیو Swagger و ReDoc را تولید می‌کند:
- **Swagger UI:** `/docs`
- **ReDoc:** `/redoc`

### مهم‌ترین مسیرها:
| متد | مسیر | توضیحات |
| :--- | :--- | :--- |
| `POST` | `/auth/login` | ورود به پنل مدیریت |
| `GET` | `/conversations/` | دریافت فهرست کامل گفتگوها و آخرین پیام‌ها |
| `POST` | `/customers/{id}/send` | ارسال دایرکت دستی به مشتری از پنل |
| `GET/POST` | `/keywords/` | مدیریت و افزودن کلیدواژه‌های ربات |
| `POST` | `/keywords/sync-zernio` | همگام‌سازی دستی کلیدواژه‌ها با اتوماسیون اینستاگرام |
| `GET/PUT` | `/settings/` | دریافت و ویرایش تنظیمات ربات و پیام پیش‌فرض |
| `POST` | `/webhook/zernio` | اندپوینت دریافت رویدادهای زنده Zernio |

---

## 🛡 امنیت و پایداری
- رمز عبور ادمین با متد زمان-ثابت (`secrets.compare_digest`) در برابر حملات Timing مقایسه می‌شود.
- نشست‌ها (Sessions) با کوکی‌های امضاشده امن مدیریت می‌شوند.
- ارتباط با API رسمی متمرکز بر توکن اختصاصی است و هیچ نیازی به ذخیره نام کاربری و پسورد اصلی پیج اینستاگرام وجود ندارد.

---

## 👨‍💻 سازنده

**محمدحسین طاهری (MH TAHERI)**
- گیت‌هاب: [@MHTAHERII](https://github.com/MHTAHERII)
