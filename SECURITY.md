# 🔒 راهنمای امنیت GramCRM

این سند چک‌لیست کامل «فاز صفر» آماده‌سازی امنیت سرور قبل از اتصال کلیدهای واقعی و پذیرش مشتری است.

---

## ۰) اول از همه: اسکریپت ممیزی

وضعیت فعلی سرور را در چند ثانیه بسنجید (هیچ مقدار محرمانه‌ای چاپ نمی‌شود):

```bash
python scripts/security_audit.py
# یا با مسیر دلخواه:
python scripts/security_audit.py --env /path/to/.env
```

- خروجی `❌` یعنی **مشکل حیاتی** — همان را اول رفع کنید.
- کد خروج `1` یعنی حداقل یک مشکل حیاتی وجود دارد.

---

## ۱) متغیرهای امنیتی `.env` سرور

| متغیر | مقدار لازم | چطور بسازم / نکته |
| :--- | :--- | :--- |
| `ADMIN_PASSWORD` | رمز قوی، حداقل ۸ کاراکتر | **همون رمزی که در پنل گذاشته‌اید** را اینجا هم بگذارید تا اگر دیتابیس ریست شد، فالبک هم امن باشد. |
| `ADMIN_SESSION_SECRET` | رشته تصادفی ≥ ۳۲ کاراکتر | PowerShell: `[guid]::NewGuid().ToString('N') + [guid]::NewGuid().ToString('N')` |
| `SESSION_HTTPS_ONLY` | `true` | کوکی سشن فقط با HTTPS ارسال شود (جلوگیری از سرقت کوکی با HTTP). |
| `ZERNIO_WEBHOOK_SECRET` | توکن تصادفی | `python -c "import secrets;print(secrets.token_hex(32))"` |
| `META_APP_SECRET` | از Meta App Dashboard | فقط اگر از وب‌هوک متا استفاده می‌کنید. |
| `ENABLE_DOCS` | `false` (یا حذف) | مستندات OpenAPI نباید در سرور اصلی عمومی باشد. |

> [!IMPORTANT]
> **نکته `ZERNIO_WEBHOOK_SECRET`:** اگر این متغیر را بگذارید اما زرنیو توکن را نفرستد،
> **همه رویدادها ۴۰۳ می‌شوند و اتوماسیون از کار می‌افتد.**
> حتماً به این ترتیب عمل کنید:
> 1. توکن را بسازید و در `.env` بگذارید.
> 2. آدرس وب‌هوک در پنل زرنیو را به شکل زیر تغییر دهید:
>    ```text
>    https://crm.YOUR-DOMAIN.com/webhook/zernio?token=YOUR_TOKEN
>    ```
> 3. سرور را ری‌استارت کنید.
> 4. یک کامنت آزمایشی زیر پست بزنید و در «لاگ‌های زنده» پنل ببینید رویداد می‌آید.
> 5. اگر `403` دیدید، فوراً `ZERNIO_WEBHOOK_SECRET` را خالی کنید و مشکل را بررسی کنید.

---

## ۲) تغییر env و ری‌استارت

بعد از هر تغییر env در Runflare، سرویس را **ری‌استارت** کنید و لاگ استارت را ببینید:

- ✅ نباید هیچ خط زرد `⚠️ امنیت:` در لاگ استارت باشد.
- ⚠️ اگر خط `ADMIN_SESSION_SECRET پیش‌فرض فعال است` دیدید، یعنی هنوز مقدار پیش‌فرض دارید (خطر جعل کوکی).

---

## ۳) راستی‌آزمایی زنده (بعد از ری‌استارت)

| تست | انتظار |
| :--- | :--- |
| `POST /auth/login` با رمز قدیمی `admin123` | `401` |
| `GET /docs` و `GET /openapi.json` | `404` |
| `GET /settings/` بدون کوکی | `401` |
| `GET /system/backup` بدون کوکی | `401` |
| `POST /webhook/zernio?token=اشتباه` (بعد از فعال‌سازی توکن) | `403` |

---

## ۴) قواعد WAF کلودفلر (اختیاری ولی توصیه‌شده)

در Cloudflare → Security → WAF → Create rule:

**قاعده ۱ — محدودیت نرخ روی تلاش ورود** (جلوگیری از بروت‌فورس در لبه):

```txt
Expression:
  (http.request.uri.path eq "/auth/login" and http.request.method eq "POST")
Action: Block
Rate: 10 requests per 1 minute per IP — Block for 10 minutes
```

**قاعده ۲ — چالش برای بخش‌های حساس** (تنظیم IP ثابت خودتان به‌عنوان allow):

```txt
Expression:
  (http.request.uri.path starts_with "/system" or http.request.uri.path starts_with "/settings")
Action: Managed Challenge
```

---

## ۵) در صورت بروز حادثه (چک‌لیست فوری)

1. فوراً کلید API مربوطه (Zernio/PostZen/Meta) را در داشبورد سرویس‌دهنده **Revok** کنید.
2. `ADMIN_PASSWORD` و `ADMIN_SESSION_SECRET` را عوض و سرویس را ری‌استارت کنید.
3. لاگ‌های پنل و رویدادهای Cloudflare (Security → Events) را برای IP مشکوک بررسی کنید.
4. کلید جدید را **فقط بعد از اتمام این چک‌لیست** در پنل وارد کنید.

---

## ۶) چک‌لیست خلاصه

- [ ] `ADMIN_PASSWORD` قوی در env سرور (هم‌ارز رمز پنل)
- [ ] `ADMIN_SESSION_SECRET` سفارشی ≥ ۳۲ کاراکتر
- [ ] `SESSION_HTTPS_ONLY=true`
- [ ] `ZERNIO_WEBHOOK_SECRET` + آدرس `?token=` در زرنیو + تست کامنت
- [ ] `ENABLE_DOCS` غیرفعال
- [ ] ری‌استارت و بدون هشدار زرد در لاگ استارت
- [ ] راستی‌آزمایی ۴۰۱/۴۰۴ جدول بالا
- [ ] (اختیاری) قواعد WAF کلودفلر
- [ ] اتصال مجدد کلید جدید زرنیو
