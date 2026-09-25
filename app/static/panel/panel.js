/* ------------------------------------------------------------------
 * پنل مدیریت ربات دایرکت — اسکریپت اصلی
 * تمام درخواست‌ها از اینجا به API همین سرور زده می‌شود.
 * ----------------------------------------------------------------- */

/* ---------------- ابزارهای عمومی ---------------- */

function esc(value) {
  // جلوگیری از تزریق HTML در محتوای کاربر
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

// تاریخ‌های سرور UTC بدون پسوند Z هستند؛ برای نمایش درست به وقت محلی Z اضافه می‌شود
function parseDate(iso) {
  if (!iso) return null;
  return new Date(iso.endsWith("Z") ? iso : iso + "Z");
}

function fmtTime(iso) {
  const d = parseDate(iso);
  if (!d || isNaN(d)) return "";
  const now = new Date();
  const isToday = d.toDateString() === now.toDateString();

  if (isToday) {
    return new Intl.DateTimeFormat("fa-IR", {
      hour: "2-digit",
      minute: "2-digit",
    }).format(d);
  }

  return new Intl.DateTimeFormat("fa-IR", {
    month: "numeric",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(d);
}

function fmtConvTime(iso) {
  const d = parseDate(iso);
  if (!d || isNaN(d)) return "";
  const now = new Date();
  if (d.toDateString() === now.toDateString()) {
    return new Intl.DateTimeFormat("fa-IR", { hour: "2-digit", minute: "2-digit" }).format(d);
  }
  return new Intl.DateTimeFormat("fa-IR", { month: "numeric", day: "numeric" }).format(d);
}

function fmtNumber(n) {
  return new Intl.NumberFormat("fa-IR").format(n);
}

function showToast(message, type = "") {
  const toast = document.getElementById("toast");
  if (!toast) return;

  let icon = "";
  if (type === "success") {
    icon = `<span style="font-size: 1.15rem; line-height: 1;">✓</span>`;
  } else if (type === "error") {
    icon = `<span style="font-size: 1.15rem; line-height: 1;">✕</span>`;
  }

  toast.innerHTML = `${icon}<span>${message}</span>`;
  toast.className = "toast " + type;
  toast.classList.remove("hidden");

  clearTimeout(showToast._timer);
  showToast._timer = setTimeout(() => {
    toast.classList.add("hidden");
  }, 3200);
}

function flashButtonSuccess(btn, originalText = null, successText = "✓ ذخیره شد") {
  if (!btn) return;
  const oldText = originalText || btn.textContent;
  btn.textContent = successText;
  btn.style.transition = "all 0.2s ease";
  const oldBg = btn.style.background;
  btn.style.background = "#10b981";
  btn.style.borderColor = "#10b981";
  setTimeout(() => {
    btn.textContent = oldText;
    btn.style.background = oldBg;
    btn.style.borderColor = "";
  }, 1800);
}

/* ---------------- لایه ارتباط با API ---------------- */

async function api(path, options = {}) {
  const res = await fetch(path, {
    credentials: "same-origin",
    headers: { "Content-Type": "application/json" },
    ...options,
  });

  if (res.status === 401 && !path.startsWith("/auth/")) {
    showLogin();
    throw new Error("unauthorized");
  }
  if (!res.ok) {
    let detail = "خطای " + res.status;
    try {
      const data = await res.json();
      if (typeof data.detail === "string") detail = data.detail;
      else if (Array.isArray(data.detail)) detail = data.detail[0]?.msg || detail;
    } catch (_) { /* بدنه بدون JSON */ }
    throw new Error(detail);
  }
  return res.json();
}

/* ---------------- ورود و خروج ---------------- */

const loginOverlay = document.getElementById("login-overlay");
const loginError = document.getElementById("login-error");

function showLogin() {
  loginOverlay.classList.remove("hidden");
}

function hideLogin() {
  loginOverlay.classList.add("hidden");
  loginError.classList.add("hidden");
}

document.getElementById("login-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const username = document.getElementById("login-username")?.value.trim() || "";
  const password = document.getElementById("login-password").value;
  try {
    await api("/auth/login", {
      method: "POST",
      body: JSON.stringify({ username, password }),
    });
    document.getElementById("login-password").value = "";
    hideLogin();
    await init();
  } catch (err) {
    loginError.textContent = err.message || "ورود ناموفق بود";
    loginError.classList.remove("hidden");
  }
});

document.getElementById("logout-btn").addEventListener("click", async () => {
  try { await api("/auth/logout", { method: "POST" }); } catch (_) {}
  showLogin();
});

/* ---------------- داشبورد و وضعیت زنده سرور (3X-UI Style) ---------------- */

async function loadDashboardStatus() {
  try {
    const data = await api("/system/status");
    const sys = data.system;
    const crm = data.crm;
    const bot = data.bot;

    // CPU
    const cpuVal = document.getElementById("stat-cpu-val");
    const cpuBar = document.getElementById("stat-cpu-bar");
    const cpuSub = document.getElementById("stat-cpu-sub");
    if (cpuVal && cpuBar && cpuSub) {
      cpuVal.textContent = `${sys.cpu_percent}%`;
      cpuBar.style.width = `${Math.min(100, Math.max(0, sys.cpu_percent))}%`;
      cpuSub.textContent = `تعداد هسته: ${sys.cpu_cores}`;
    }

    // RAM
    const ramVal = document.getElementById("stat-ram-val");
    const ramBar = document.getElementById("stat-ram-bar");
    const ramSub = document.getElementById("stat-ram-sub");
    if (ramVal && ramBar && ramSub) {
      ramVal.textContent = `${sys.memory.percent}%`;
      ramBar.style.width = `${Math.min(100, Math.max(0, sys.memory.percent))}%`;
      ramSub.textContent = `${fmtNumber(sys.memory.used_mb)} MB / ${fmtNumber(sys.memory.total_mb)} MB`;
    }

    // Disk
    const diskVal = document.getElementById("stat-disk-val");
    const diskBar = document.getElementById("stat-disk-bar");
    const diskSub = document.getElementById("stat-disk-sub");
    if (diskVal && diskBar && diskSub) {
      diskVal.textContent = `${sys.disk.percent}%`;
      diskBar.style.width = `${Math.min(100, Math.max(0, sys.disk.percent))}%`;
      diskSub.textContent = `${fmtNumber(sys.disk.used_gb)} GB / ${fmtNumber(sys.disk.total_gb)} GB`;
    }

    // Uptime
    const uptimeVal = document.getElementById("stat-uptime-val");
    if (uptimeVal) uptimeVal.textContent = sys.uptime;

    // CRM
    const msgEl = document.getElementById("stat-total-messages");
    const custEl = document.getElementById("stat-total-customers");
    const kwEl = document.getElementById("stat-active-keywords");
    const prodEl = document.getElementById("stat-total-products");
    if (msgEl) msgEl.textContent = fmtNumber(crm.total_messages);
    if (custEl) custEl.textContent = fmtNumber(crm.total_customers);
    if (kwEl) kwEl.textContent = fmtNumber(crm.active_keywords);
    if (prodEl) prodEl.textContent = fmtNumber(crm.total_products);

    // Instagram Connection
    const desc = document.getElementById("dashboard-conn-desc");
    const badge = document.getElementById("dashboard-conn-badge");
    if (desc && badge) {
      if (bot.instagram_connected) {
        const userText = bot.instagram_username ? ` به پیج @${bot.instagram_username}` : "";
        desc.textContent = `ارتباط با سرورهای ابری Zernio و اینستاگرام${userText} پایدار است. وب‌هوک‌ها فعال هستند.`;
        badge.textContent = bot.instagram_username ? `@${bot.instagram_username} 🟢` : "متصل 🟢";
        badge.style.background = "rgba(16, 185, 129, 0.15)";
        badge.style.color = "#10b981";
        badge.style.border = "1px solid rgba(16, 185, 129, 0.3)";
      } else {
        desc.textContent = "توکن API اینستاگرام در تب تنظیمات وارد نشده است.";
        badge.textContent = "عدم اتصال 🔴";
        badge.style.background = "rgba(239, 68, 68, 0.15)";
        badge.style.color = "#ef4444";
        badge.style.border = "1px solid rgba(239, 68, 68, 0.3)";
      }
    }
  } catch (err) {
    console.error("Error loading dashboard status:", err);
  }
}

document.getElementById("btn-refresh-status")?.addEventListener("click", () => {
  loadDashboardStatus();
  showToast("وضعیت سیستم به‌روزرسانی شد", "success");
});

/* ---------------- تب‌ها ---------------- */

const loaders = {
  dashboard: loadDashboardStatus,
  keywords: loadKeywords,
  conversations: loadConversations,
  products: loadProducts,
  settings: loadSettings,
};
let activeTab = "dashboard";

document.querySelectorAll(".tab").forEach((tab) => {
  tab.addEventListener("click", () => {
    document.querySelectorAll(".tab").forEach((t) => t.classList.remove("active"));
    document.querySelectorAll(".tab-panel").forEach((p) => p.classList.remove("active"));
    tab.classList.add("active");
    document.getElementById("tab-" + tab.dataset.tab).classList.add("active");
    activeTab = tab.dataset.tab;
    loaders[activeTab]();
  });
});

/* ---------------- کلمات کلیدی ---------------- */

let editingKeywordId = null;
let keywordsCache = [];

function createButtonRow(title = "", url = "") {
  const row = document.createElement("div");
  row.className = "grid-2 keyword-btn-row";
  row.style.cssText = "margin-bottom: 8px; align-items: flex-end;";
  row.innerHTML = `
    <div class="field" style="margin-bottom: 0;">
      <label style="font-size: 0.78rem;">متن دکمه (مثلاً: پرداخت آنلاین 💳)</label>
      <input type="text" class="btn-title-input" placeholder="عنوان دکمه" value="${esc(title)}">
    </div>
    <div class="field" style="margin-bottom: 0; display: flex; gap: 8px; align-items: flex-end;">
      <div style="flex: 1;">
        <label style="font-size: 0.78rem;">لینک اینترنتی (URL)</label>
        <input type="url" class="btn-url-input" placeholder="https://..." value="${esc(url)}">
      </div>
      <button type="button" class="btn small ghost btn-remove-row" style="color: #ef4444; border-color: rgba(239, 68, 68, 0.3); height: 38px; padding: 0 10px;" title="حذف این دکمه">✕</button>
    </div>
  `;
  row.querySelector(".btn-remove-row").addEventListener("click", () => {
    row.remove();
    checkButtonCount();
  });
  return row;
}

function checkButtonCount() {
  const container = document.getElementById("keyword-buttons-container");
  const addBtn = document.getElementById("btn-add-keyword-button");
  if (!container || !addBtn) return;
  const count = container.querySelectorAll(".keyword-btn-row").length;
  addBtn.style.display = count >= 3 ? "none" : "inline-flex";
}

function addKeywordButtonRow(title = "", url = "") {
  const container = document.getElementById("keyword-buttons-container");
  if (!container) return;
  if (container.querySelectorAll(".keyword-btn-row").length >= 3) {
    showToast("حداکثر ۳ دکمه می‌توانید اضافه کنید", "error");
    return;
  }
  container.appendChild(createButtonRow(title, url));
  checkButtonCount();
}

document.getElementById("btn-add-keyword-button")?.addEventListener("click", () => {
  addKeywordButtonRow();
});

async function loadKeywords() {
  keywordsCache = await api("/keywords/");
  const tbody = document.getElementById("keywords-body");
  document.getElementById("keywords-empty").classList.toggle("hidden", keywordsCache.length > 0);

  tbody.innerHTML = keywordsCache.map((k) => {
    const btns = (k.buttons && k.buttons.length)
      ? k.buttons
      : (k.button_title && k.button_url ? [{ title: k.button_title, url: k.button_url }] : []);
    return `
      <tr>
        <td class="kw-text">${esc(k.keyword)}</td>
        <td class="kw-response">
          <div>${esc(k.response)}</div>
          ${btns.length ? `
            <div style="margin-top:6px; display:flex; flex-wrap:wrap; gap:4px;">
              ${btns.map(b => `
                <a href="${esc(b.url)}" target="_blank" rel="noopener noreferrer" style="display:inline-flex;align-items:center;gap:4px;padding:3px 8px;font-size:0.75rem;background:rgba(99,102,241,0.15);color:#818cf8;border:1px solid rgba(99,102,241,0.3);border-radius:6px;text-decoration:none;">
                  🔘 ${esc(b.title)}
                </a>
              `).join("")}
            </div>
          ` : ""}
        </td>
        <td>
          <label class="switch" title="روشن/خاموش">
            <input type="checkbox" ${k.active ? "checked" : ""} onchange="toggleKeyword(${k.id})">
            <span class="slider"></span>
          </label>
        </td>
        <td class="actions">
          <button class="btn small ghost" onclick="startEditKeyword(${k.id})">ویرایش</button>
          <button class="btn small ghost" onclick="deleteKeyword(${k.id})">حذف</button>
        </td>
      </tr>
    `;
  }).join("");
}

async function toggleKeyword(id) {
  try {
    await api(`/keywords/${id}/toggle`, { method: "PATCH" });
    showToast("وضعیت کلمه کلیدی با موفقیت تغییر کرد", "success");
  } catch (err) {
    showToast(err.message, "error");
    loadKeywords();
  }
}

async function deleteKeyword(id) {
  if (!confirm("این کلمه کلیدی حذف شود؟")) return;
  try {
    await api(`/keywords/${id}`, { method: "DELETE" });
    showToast("کلمه کلیدی با موفقیت حذف شد", "success");
    loadKeywords();
  } catch (err) {
    showToast(err.message, "error");
  }
}

function startEditKeyword(id) {
  const k = keywordsCache.find((item) => item.id === id);
  if (!k) return;
  editingKeywordId = id;
  document.getElementById("keyword-form-title").textContent = "ویرایش کلمه کلیدی";
  document.getElementById("keyword-input").value = k.keyword;
  document.getElementById("keyword-response-input").value = k.response;

  // بازسازی ردیف‌های دکمه‌ها
  const container = document.getElementById("keyword-buttons-container");
  if (container) {
    container.innerHTML = "";
    const btns = (k.buttons && k.buttons.length)
      ? k.buttons
      : (k.button_title && k.button_url ? [{ title: k.button_title, url: k.button_url }] : []);
    btns.forEach(b => addKeywordButtonRow(b.title, b.url));
  }

  document.getElementById("keyword-submit").textContent = "ذخیره تغییرات";
  document.getElementById("keyword-cancel").classList.remove("hidden");
  document.getElementById("keyword-input").focus();
}

function resetKeywordForm() {
  editingKeywordId = null;
  document.getElementById("keyword-form").reset();
  const container = document.getElementById("keyword-buttons-container");
  if (container) container.innerHTML = "";
  checkButtonCount();
  document.getElementById("keyword-form-title").textContent = "افزودن کلمه کلیدی";
  document.getElementById("keyword-submit").textContent = "افزودن";
  document.getElementById("keyword-cancel").classList.add("hidden");
}

document.getElementById("keyword-cancel").addEventListener("click", resetKeywordForm);

document.getElementById("keyword-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const container = document.getElementById("keyword-buttons-container");
  const rows = container ? container.querySelectorAll(".keyword-btn-row") : [];
  const buttons = [];
  rows.forEach(r => {
    const t = r.querySelector(".btn-title-input")?.value.trim();
    const u = r.querySelector(".btn-url-input")?.value.trim();
    if (t && u) {
      buttons.push({ title: t, url: u });
    }
  });

  const body = JSON.stringify({
    keyword: document.getElementById("keyword-input").value.trim(),
    response: document.getElementById("keyword-response-input").value.trim(),
    buttons: buttons,
    button_title: buttons.length ? buttons[0].title : null,
    button_url: buttons.length ? buttons[0].url : null,
  });

  try {
    if (editingKeywordId) {
      await api(`/keywords/${editingKeywordId}`, { method: "PUT", body });
      showToast("کلمه کلیدی با موفقیت ویرایش و ذخیره شد", "success");
    } else {
      await api("/keywords/", { method: "POST", body });
      showToast("کلمه کلیدی جدید با موفقیت ذخیره شد", "success");
    }
    resetKeywordForm();
    loadKeywords();
  } catch (err) {
    showToast(err.message, "error");
  }
});

/* ---------------- گفتگوها (Optimized Real-Time Chat & Inbox) ---------------- */

let selectedCustomerId = null;
let conversationsCache = [];
let messagesCache = {}; // Cache: customerId -> messages[]

const SENDER_LABEL = {
  customer: "مشتری",
  bot: "ربات",
  admin: "شما",
};

function renderConversationsList(conversations) {
  const list = document.getElementById("conversation-list");
  if (!list) return;

  if (!conversations || !conversations.length) {
    list.innerHTML = `<div class="empty">هنوز گفتگویی وجود ندارد</div>`;
    list.dataset.fingerprint = "";
    return;
  }

  // بررسی عدم تغییر دیتا برای جلوگیری از رفرش و پرش تصویری (Silent Background Poll)
  const convFingerprint = JSON.stringify(conversations.map(c => [
    c.customer?.id,
    c.customer?.username,
    c.last_message?.id,
    c.last_message?.text,
    c.last_message?.created_at,
    c.customer?.id === selectedCustomerId
  ]));

  if (list.dataset.fingerprint === convFingerprint) {
    return; // دیتا تغییر نکرده؛ DOM دست نخورده باقی می‌ماند
  }
  list.dataset.fingerprint = convFingerprint;

  list.innerHTML = conversations.map((c) => {
    const customer = c.customer;
    const last = c.last_message;
    const name = customer.name || customer.username || "کاربر " + customer.instagram_id;
    const preview = last ? last.text : "بدون پیام";
    const time = last ? fmtConvTime(last.created_at) : "";
    const isActive = customer.id === selectedCustomerId;
    return `
      <div class="conversation-item ${isActive ? "active" : ""}"
           data-customer-id="${customer.id}"
           onclick="selectConversation(${customer.id})">
        <div class="c-name">${esc(name)}</div>
        ${customer.username ? `<div class="c-username">@${esc(customer.username)}</div>` : ""}
        <div class="c-preview" id="conv-prev-${customer.id}">${esc(preview)}</div>
        <div class="c-time" id="conv-time-${customer.id}">${time}</div>
      </div>
    `;
  }).join("");
}

async function loadConversations(isBackground = false) {
  const list = document.getElementById("conversation-list");
  let conversations;
  try {
    conversations = await api("/conversations/");
    conversationsCache = conversations || [];
    renderConversationsList(conversationsCache);
  } catch (err) {
    if (err.message === "unauthorized") return;
    if (!isBackground && list) {
      list.innerHTML = `<div class="empty">خطا در دریافت گفتگوها</div>`;
    }
    return;
  }
}

function renderChatHeader(customer) {
  const header = document.getElementById("chat-header");
  if (!header || !customer) return;
  const name = customer.name || customer.username || "کاربر " + customer.instagram_id;
  header.innerHTML = "";
  const title = document.createElement("div");
  title.textContent = name;
  const sub = document.createElement("div");
  sub.className = "hint";
  sub.style.direction = "ltr";
  sub.textContent = customer.username ? "@" + customer.username : "ID: " + customer.instagram_id;
  header.appendChild(title);
  header.appendChild(sub);
}

function renderMessageList(messages) {
  const messagesBox = document.getElementById("chat-messages");
  if (!messagesBox) return;

  if (!messages || !messages.length) {
    messagesBox.innerHTML = `<div class="empty">پیامی رد و بدل نشده است</div>`;
    messagesBox.dataset.fingerprint = "";
    return;
  }

  // بررسی تفاوت پیام‌ها؛ اگر هیچ پیام جدیدی اضافه نشده باشد، DOM اصلاً بازنویسی نمی‌شود
  const msgFingerprint = JSON.stringify(messages.map(m => [m.id, m._pending, m.text]));
  if (messagesBox.dataset.fingerprint === msgFingerprint) {
    return; // هیچ پیامی تغییر نکرده؛ مانع از پرش اسکرول و چشمک صفحه شو
  }
  messagesBox.dataset.fingerprint = msgFingerprint;

  // اگر کاربر نزدیک پایین چت باشد، بعد از رندر اسکرول شود؛ اگر بالاتر را می‌خواند اسکرولش نپرد
  const isNearBottom = messagesBox.scrollHeight - messagesBox.scrollTop - messagesBox.clientHeight < 150;

  messagesBox.innerHTML = messages.map((m) => {
    const isPending = m._pending;
    return `
      <div class="msg ${esc(m.sender)}" ${m.id ? `id="msg-${m.id}"` : ""}>
        <div class="bubble">
          ${m.sender !== "customer" ? `<span class="sender">${SENDER_LABEL[m.sender] || m.sender}</span>` : ""}
          <div class="bubble-content">
            <span class="bubble-text">${esc(m.text)}</span>
            <span class="time" id="status-${m.id}">
              ${isPending ? "در حال ارسال… ⏳" : fmtTime(m.created_at)}
            </span>
          </div>
        </div>
      </div>
    `;
  }).join("");

  if (isNearBottom) {
    messagesBox.scrollTop = messagesBox.scrollHeight;
  }
}

async function selectConversation(customerId) {
  selectedCustomerId = customerId;
  const messagesBox = document.getElementById("chat-messages");
  if (messagesBox) messagesBox.dataset.fingerprint = ""; // ریست برای بارگذاری تمیز پیام‌های کاربر جدید

  // ۱. آپدیت فوری استایل active روی آیتم‌ها بدون رفرش کل لیست (۰ میلی‌ثانیه!)
  document.querySelectorAll(".conversation-item").forEach((el) => {
    el.classList.toggle("active", el.dataset.customerId == customerId);
  });

  // ۲. نمایش فوری هدر از روی اطلاعات کش شده (۰ میلی‌ثانیه!)
  const conv = conversationsCache.find((c) => c.customer && c.customer.id === customerId);
  if (conv && conv.customer) {
    renderChatHeader(conv.customer);
  }

  // ۳. نمایش فوری پیام‌ها از کش حافظه اگر قبلاً لود شده باشد (Instant 0ms UI)
  if (messagesCache[customerId]) {
    renderMessageList(messagesCache[customerId]);
  } else {
    const messagesBox = document.getElementById("chat-messages");
    if (messagesBox) {
      messagesBox.innerHTML = `<div class="empty" style="color: #818cf8;">در حال دریافت پیام‌ها…</div>`;
    }
  }

  // ۴. دریافت آخرین پیام‌ها در پس‌زمینه بدون مسدود کردن UI
  await loadChatMessages();
}

async function loadChatMessages() {
  if (!selectedCustomerId) return;
  const currentId = selectedCustomerId;

  try {
    const messages = await api(`/customers/${currentId}/messages`);
    // جلوگیری از تداخل اگر کاربر حین فچ روی گفتگوی دیگری کلیک کرده باشد
    if (selectedCustomerId !== currentId) return;

    messagesCache[currentId] = messages;
    renderMessageList(messages);

    // تکمیل مشخصات هدر در صورتی که موجود باشد
    const conv = conversationsCache.find((c) => c.customer && c.customer.id === currentId);
    if (conv && conv.customer) {
      renderChatHeader(conv.customer);
    }
  } catch (err) {
    if (err.message === "unauthorized") return;
    showToast(err.message, "error");
  }
}

// ارسال فوق‌سریع پیام با آپدیت خوش‌بینانه (Optimistic UI - Instant 0ms)
document.getElementById("chat-send-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  if (!selectedCustomerId) {
    showToast("اول یک گفتگو انتخاب کنید", "error");
    return;
  }
  const input = document.getElementById("chat-input");
  const text = input.value.trim();
  if (!text) return;

  const currentCustomerId = selectedCustomerId;
  const tempId = "temp-" + Date.now();
  const optimisticMsg = {
    id: tempId,
    customer_id: currentCustomerId,
    sender: "admin",
    text: text,
    created_at: new Date().toISOString(),
    _pending: true
  };

  // ۱. پاکسازی فوری ورودی جهت تایپ پیام بعدی بدون توقف (۰ میلی‌ثانیه!)
  input.value = "";
  input.focus();

  // ۲. نمایش فوری پیام در پنجره چت (۰ میلی‌ثانیه!)
  if (!messagesCache[currentCustomerId]) {
    messagesCache[currentCustomerId] = [];
  }
  messagesCache[currentCustomerId].push(optimisticMsg);
  renderMessageList(messagesCache[currentCustomerId]);

  // ۳. آپدیت فوری پیش‌نمایش در لیست سمت راست
  const prevEl = document.getElementById(`conv-prev-${currentCustomerId}`);
  const timeEl = document.getElementById(`conv-time-${currentCustomerId}`);
  if (prevEl) prevEl.textContent = text;
  if (timeEl) timeEl.textContent = "همین الان";

  // ۴. ارسال درخواست به سرور در پس‌زمینه بدون بلاک کردن کاربر
  try {
    const result = await api(`/customers/${currentCustomerId}/send`, {
      method: "POST",
      body: JSON.stringify({ text }),
    });

    const statusEl = document.getElementById(`status-${tempId}`);
    if (result.sent) {
      if (statusEl) {
        statusEl.textContent = fmtTime(new Date()) + " ✓";
        statusEl.style.color = "#34d399";
      }
      optimisticMsg._pending = false;
      if (result.message && result.message.id) {
        optimisticMsg.id = result.message.id;
      }
    } else {
      if (statusEl) {
        statusEl.innerHTML = `<span style="color:#f87171;" title="${esc(result.detail || 'خطا در ارسال')}">ارسال نشد ⚠️</span>`;
      }
      showToast(result.detail || "ارسال به اینستاگرام ناموفق بود ولی در سوابق ثبت شد", "warning");
    }
  } catch (err) {
    const statusEl = document.getElementById(`status-${tempId}`);
    if (statusEl) {
      statusEl.innerHTML = `<span style="color:#ef4444;" title="${esc(err.message)}">خطا ❌</span>`;
    }
    if (err.message !== "unauthorized") showToast(err.message, "error");
  }
});

/* ---------------- محصولات ---------------- */

let editingProductId = null;
let productsCache = [];

async function loadProducts() {
  productsCache = await api("/products/");
  const grid = document.getElementById("products-list");
  document.getElementById("products-empty").classList.toggle("hidden", productsCache.length > 0);

  grid.innerHTML = productsCache.map((p) => `
    <div class="card product-card">
      <div class="p-name">${esc(p.name)}</div>
      <div class="p-price">${fmtNumber(p.price)} تومان</div>
      <div class="p-desc">${esc(p.description)}</div>
      <div class="p-footer">
        <span class="p-stock">موجودی: ${fmtNumber(p.stock)}</span>
        <span class="actions">
          <button class="btn small ghost" onclick="startEditProduct(${p.id})">ویرایش</button>
          <button class="btn small ghost" onclick="deleteProduct(${p.id})">حذف</button>
        </span>
      </div>
    </div>
  `).join("");
}

function startEditProduct(id) {
  const p = productsCache.find((item) => item.id === id);
  if (!p) return;
  editingProductId = id;
  document.getElementById("product-form-title").textContent = "ویرایش محصول";
  document.getElementById("product-name").value = p.name;
  document.getElementById("product-price").value = p.price;
  document.getElementById("product-stock").value = p.stock;
  document.getElementById("product-description").value = p.description;
  document.getElementById("product-submit").textContent = "ذخیره تغییرات";
  document.getElementById("product-cancel").classList.remove("hidden");
  window.scrollTo({ top: 0, behavior: "smooth" });
}

function resetProductForm() {
  editingProductId = null;
  document.getElementById("product-form").reset();
  document.getElementById("product-form-title").textContent = "افزودن محصول";
  document.getElementById("product-submit").textContent = "افزودن";
  document.getElementById("product-cancel").classList.add("hidden");
}

document.getElementById("product-cancel").addEventListener("click", resetProductForm);

document.getElementById("product-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const body = JSON.stringify({
    name: document.getElementById("product-name").value,
    price: Number(document.getElementById("product-price").value),
    stock: Number(document.getElementById("product-stock").value),
    description: document.getElementById("product-description").value,
  });
  try {
    if (editingProductId) {
      await api(`/products/${editingProductId}`, { method: "PUT", body });
      showToast("محصول با موفقیت ویرایش و ذخیره شد", "success");
    } else {
      await api("/products/", { method: "POST", body });
      showToast("محصول جدید با موفقیت ذخیره شد", "success");
    }
    resetProductForm();
    loadProducts();
  } catch (err) {
    showToast(err.message, "error");
  }
});

async function deleteProduct(id) {
  if (!confirm("این محصول حذف شود؟")) return;
  try {
    await api(`/products/${id}`, { method: "DELETE" });
    showToast("محصول با موفقیت حذف شد", "success");
    loadProducts();
  } catch (err) {
    showToast(err.message, "error");
  }
}

/* ---------------- تنظیمات ---------------- */

async function loadSettings() {
  const settings = await api("/settings/");
  document.getElementById("bot-enabled").checked = settings.bot_enabled;
  document.getElementById("fallback-message").value = settings.fallback_message || "";
  document.getElementById("follow-gate-enabled").checked = settings.follow_gate_enabled;
  document.getElementById("follow-gate-message").value = settings.follow_gate_message || "";

  // فیلدهای توکن و اکانت Zernio
  document.getElementById("setting-zernio-api-key").value = settings.zernio_api_key || "";
  document.getElementById("setting-zernio-profile-id").value = settings.zernio_profile_id || "";
  document.getElementById("setting-zernio-account-id").value = settings.zernio_account_id || "";

  // نمایش وضعیت و نام پیج متصل
  const zBadge = document.getElementById("zernio-account-badge");
  const zInfo = document.getElementById("zernio-connected-info");
  const zUserEl = document.getElementById("zernio-connected-username");
  if (settings.instagram_username) {
    if (zBadge) {
      zBadge.textContent = `🟢 @${settings.instagram_username}`;
      zBadge.style.display = "inline-block";
    }
    if (zInfo && zUserEl) {
      zUserEl.textContent = `@${settings.instagram_username}`;
      zInfo.style.display = "block";
    }
  } else if (settings.zernio_account_id) {
    if (zBadge) {
      zBadge.textContent = "🟢 متصل";
      zBadge.style.display = "inline-block";
    }
  } else {
    if (zBadge) zBadge.style.display = "none";
    if (zInfo) zInfo.style.display = "none";
  }

  // فیلد نام کاربری
  document.getElementById("setting-admin-username").value = settings.admin_username || "admin";
  document.getElementById("setting-admin-password").value = "";

  updateBotStatusText(settings.bot_enabled);
  updateBotBadge(settings.bot_enabled);
  await fetchSystemLogs();
  await fetchVersionInfo();
}

function updateBotStatusText(enabled) {
  document.getElementById("bot-status-text").textContent = enabled
    ? "🟢 ربات روشن است و به دایرکت‌ها پاسخ خودکار می‌دهد."
    : "🔴 ربات خاموش است؛ پیام‌ها ذخیره می‌شوند ولی پاسخی ارسال نمی‌شود.";
}

function updateBotBadge(enabled) {
  const badge = document.getElementById("bot-status");
  badge.textContent = enabled ? "ربات فعال" : "ربات خاموش";
  badge.classList.toggle("off", !enabled);
}

// دکمه نمایش/مخفی کردن توکن API
document.getElementById("btn-toggle-token-vis")?.addEventListener("click", () => {
  const input = document.getElementById("setting-zernio-api-key");
  if (!input) return;
  input.type = input.type === "password" ? "text" : "password";
});

document.getElementById("save-settings").addEventListener("click", async () => {
  const btn = document.getElementById("save-settings");
  const body = JSON.stringify({
    bot_enabled: document.getElementById("bot-enabled").checked,
    fallback_message: document.getElementById("fallback-message").value,
  });
  try {
    const updated = await api("/settings/", { method: "PUT", body });
    updateBotStatusText(updated.bot_enabled);
    updateBotBadge(updated.bot_enabled);
    flashButtonSuccess(btn, "ذخیره تنظیمات", "✓ ذخیره شد");
    showToast("تنظیمات عمومی با موفقیت ذخیره شد", "success");
  } catch (err) {
    showToast(err.message, "error");
  }
});

document.getElementById("save-follow-gate").addEventListener("click", async () => {
  const btn = document.getElementById("save-follow-gate");
  const body = JSON.stringify({
    follow_gate_enabled: document.getElementById("follow-gate-enabled").checked,
    follow_gate_message: document.getElementById("follow-gate-message").value,
  });
  try {
    await api("/settings/", { method: "PUT", body });
    flashButtonSuccess(btn, "ذخیره دروازه فالو", "✓ ذخیره شد");
    showToast("تنظیمات دروازه فالو با موفقیت ذخیره شد", "success");
  } catch (err) {
    showToast(err.message, "error");
  }
});

// ذخیره کلید و شناسه‌های API اینستاگرام (Zernio) با اتصال و استعلام خودکار
document.getElementById("save-api-settings")?.addEventListener("click", async () => {
  const saveBtn = document.getElementById("save-api-settings");
  const apiKey = document.getElementById("setting-zernio-api-key").value.trim();
  const profileId = document.getElementById("setting-zernio-profile-id").value.trim();
  const accountId = document.getElementById("setting-zernio-account-id").value.trim();
  const alertEl = document.getElementById("connection-status-alert");

  if (!apiKey) {
    showToast("لطفاً کلید API توکن را وارد کنید", "error");
    return;
  }

  saveBtn.disabled = true;
  if (alertEl) {
    alertEl.textContent = "در حال ذخیره و شناسایی خودکار اکانت اینستاگرام...";
    alertEl.style.color = "#818cf8";
  }

  const body = JSON.stringify({
    zernio_api_key: apiKey || null,
    zernio_profile_id: profileId || null,
    zernio_account_id: accountId || null,
  });
  try {
    const updated = await api("/settings/", { method: "PUT", body });
    
    // پر کردن خودکار شناسه‌ها در فیلدهای پیشرفته
    if (updated.zernio_profile_id) {
      document.getElementById("setting-zernio-profile-id").value = updated.zernio_profile_id;
    }
    if (updated.zernio_account_id) {
      document.getElementById("setting-zernio-account-id").value = updated.zernio_account_id;
    }
    if (updated.instagram_username) {
      const badge = document.getElementById("zernio-account-badge");
      const info = document.getElementById("zernio-connected-info");
      const usernameEl = document.getElementById("zernio-connected-username");
      if (badge) {
        badge.textContent = `🟢 @${updated.instagram_username}`;
        badge.style.display = "inline-block";
      }
      if (info && usernameEl) {
        usernameEl.textContent = `@${updated.instagram_username}`;
        info.style.display = "block";
      }
    }

    flashButtonSuccess(saveBtn, "ذخیره و اتصال خودکار ⚡", "✓ ذخیره شد");
    showToast(`تنظیمات اتصال با موفقیت ذخیره شد${updated.instagram_username ? ' (@' + updated.instagram_username + ')' : ''}`, "success");
    if (alertEl) {
      alertEl.textContent = `✅ تنظیمات ذخیره و متصل شد.${updated.instagram_username ? ' پیج فعال: @' + updated.instagram_username : ''}`;
      alertEl.style.color = "#10b981";
    }
  } catch (err) {
    showToast(err.message, "error");
    if (alertEl) {
      alertEl.textContent = `❌ خطا در ذخیره تنظیمات: ${err.message}`;
      alertEl.style.color = "#ef4444";
    }
  } finally {
    saveBtn.disabled = false;
  }
});

// استعلام فوری شناسه‌ها از سرور Zernio بدون نیاز به ذخیره کامل
document.getElementById("btn-auto-discover")?.addEventListener("click", async () => {
  const btn = document.getElementById("btn-auto-discover");
  const apiKey = document.getElementById("setting-zernio-api-key").value.trim();
  const alertEl = document.getElementById("connection-status-alert");

  if (!apiKey) {
    showToast("لطفاً ابتدا کلید API توکن را وارد کنید", "error");
    return;
  }

  btn.disabled = true;
  if (alertEl) {
    alertEl.textContent = "در حال استعلام شناسه‌ها از سرورهای Zernio...";
    alertEl.style.color = "#818cf8";
  }

  try {
    const res = await api("/settings/auto-discover", {
      method: "POST",
      body: JSON.stringify({ api_key: apiKey })
    });
    if (res.success && res.data) {
      if (res.data.account_id) document.getElementById("setting-zernio-account-id").value = res.data.account_id;
      if (res.data.profile_id) document.getElementById("setting-zernio-profile-id").value = res.data.profile_id;
      if (res.data.username) {
        const badge = document.getElementById("zernio-account-badge");
        const info = document.getElementById("zernio-connected-info");
        const usernameEl = document.getElementById("zernio-connected-username");
        if (badge) {
          badge.textContent = `🟢 @${res.data.username}`;
          badge.style.display = "inline-block";
        }
        if (info && usernameEl) {
          usernameEl.textContent = `@${res.data.username}`;
          info.style.display = "block";
        }
      }
      showToast(res.message, "success");
      if (alertEl) {
        alertEl.textContent = `✅ اکانت @${res.data.username || ''} با موفقیت شناسایی و تنظیم شد.`;
        alertEl.style.color = "#10b981";
      }
    } else {
      showToast(res.message || "خطا در استعلام اکانت", "error");
      if (alertEl) {
        alertEl.textContent = `❌ ${res.message}`;
        alertEl.style.color = "#ef4444";
      }
    }
  } catch (err) {
    showToast(err.message, "error");
    if (alertEl) {
      alertEl.textContent = `❌ خطا: ${err.message}`;
      alertEl.style.color = "#ef4444";
    }
  } finally {
    btn.disabled = false;
  }
});

// تست زنده اتصال به اینستاگرام
document.getElementById("test-connection-btn")?.addEventListener("click", async () => {
  const btn = document.getElementById("test-connection-btn");
  const alertEl = document.getElementById("connection-status-alert");
  if (!alertEl) return;

  btn.disabled = true;
  alertEl.textContent = "در حال بررسی وضعیت اتصال به سرورهای اینستاگرام...";
  alertEl.style.color = "#94a3b8";

  try {
    const res = await api("/settings/test-connection", { method: "POST" });
    if (res.success) {
      if (res.account_id) document.getElementById("setting-zernio-account-id").value = res.account_id;
      if (res.profile_id) document.getElementById("setting-zernio-profile-id").value = res.profile_id;
      if (res.username) {
        const badge = document.getElementById("zernio-account-badge");
        const info = document.getElementById("zernio-connected-info");
        const usernameEl = document.getElementById("zernio-connected-username");
        if (badge) {
          badge.textContent = `🟢 @${res.username}`;
          badge.style.display = "inline-block";
        }
        if (info && usernameEl) {
          usernameEl.textContent = `@${res.username}`;
          info.style.display = "block";
        }
      }
      alertEl.textContent = `${res.message} ${res.username ? '(پیج: @' + res.username + ' | ' : '('}تعداد سناریوها: ${res.automations_count ?? 0})`;
      alertEl.style.color = "#10b981";
      showToast("اتصال با موفقیت تأیید شد ✅", "success");
    } else {
      alertEl.textContent = `❌ ${res.message}`;
      alertEl.style.color = "#ef4444";
      showToast("خطا در اتصال به اینستاگرام", "error");
    }
  } catch (err) {
    alertEl.textContent = `❌ ${err.message}`;
    alertEl.style.color = "#ef4444";
    showToast(err.message, "error");
  } finally {
    btn.disabled = false;
  }
});

// ذخیره اطلاعات ورود به پنل (یوزرنیم و پسورد)
document.getElementById("save-auth-settings")?.addEventListener("click", async () => {
  const username = document.getElementById("setting-admin-username").value.trim();
  const password = document.getElementById("setting-admin-password").value;

  if (!username) {
    showToast("نام کاربری نمی‌تواند خالی باشد", "error");
    return;
  }

  const payload = { admin_username: username };
  if (password.trim()) {
    payload.admin_password = password.trim();
  }

  try {
    await api("/settings/", { method: "PUT", body: JSON.stringify(payload) });
    document.getElementById("setting-admin-password").value = "";
    const authBtn = document.getElementById("save-auth-settings");
    flashButtonSuccess(authBtn, "ذخیره اطلاعات ورود", "✓ ذخیره شد");
    showToast("اطلاعات ورود به پنل با موفقیت ذخیره شد", "success");
  } catch (err) {
    showToast(err.message, "error");
  }
});

/* ---------------- پشتیبان‌گیری و بازیابی (Backup & Restore) ---------------- */

// دانلود فایل پشتیبان
document.getElementById("btn-download-backup")?.addEventListener("click", () => {
  window.location.href = "/system/backup";
  showToast("در حال آماده‌سازی و دانلود فایل پشتیبان...", "success");
});

// انتخاب فایل برای بازیابی
const restoreFileInput = document.getElementById("restore-file-input");
const restoreFileName = document.getElementById("restore-file-name");
const submitRestoreBtn = document.getElementById("btn-submit-restore");

document.getElementById("btn-choose-restore")?.addEventListener("click", () => {
  restoreFileInput?.click();
});

restoreFileInput?.addEventListener("change", () => {
  if (restoreFileInput.files.length > 0) {
    const file = restoreFileInput.files[0];
    if (restoreFileName) restoreFileName.textContent = `فایل انتخاب‌شده: ${file.name}`;
    submitRestoreBtn?.classList.remove("hidden");
  } else {
    if (restoreFileName) restoreFileName.textContent = "";
    submitRestoreBtn?.classList.add("hidden");
  }
});

// ارسال و اجرای بازیابی دیتابیس
submitRestoreBtn?.addEventListener("click", async () => {
  if (!restoreFileInput || !restoreFileInput.files.length) return;
  const file = restoreFileInput.files[0];

  if (!confirm(`آیا مطمئن هستید که می‌خواهید اطلاعات را از فایل «${file.name}» بازیابی کنید؟`)) {
    return;
  }

  submitRestoreBtn.disabled = true;
  submitRestoreBtn.textContent = "در حال بازیابی…";
  const alertEl = document.getElementById("backup-restore-alert");
  if (alertEl) {
    alertEl.textContent = "در حال ارسال فایل و بازیابی اطلاعات پایگاه داده...";
    alertEl.style.color = "#94a3b8";
  }

  const formData = new FormData();
  formData.append("file", file);

  try {
    const res = await fetch("/system/restore", {
      method: "POST",
      credentials: "same-origin",
      body: formData,
    });
    const result = await res.json();
    if (!res.ok) throw new Error(result.detail || "خطا در بازیابی");

    showToast("اطلاعات با موفقیت بازیابی شد! ✅", "success");
    if (alertEl) {
      alertEl.textContent = `✅ ${result.message} (کلمات کلیدی: ${result.restored.keywords}، محصولات: ${result.restored.products}، مشتریان: ${result.restored.customers})`;
      alertEl.style.color = "#10b981";
    }
    submitRestoreBtn.classList.add("hidden");
    if (restoreFileName) restoreFileName.textContent = "";
    restoreFileInput.value = "";
    await loadSettings();
  } catch (err) {
    showToast(err.message, "error");
    if (alertEl) {
      alertEl.textContent = `❌ ${err.message}`;
      alertEl.style.color = "#ef4444";
    }
  } finally {
    submitRestoreBtn.disabled = false;
    submitRestoreBtn.textContent = "تأیید و بازگردانی اطلاعات";
  }
});

/* ---------------- مشاهده لاگ‌های زنده سرور (Log Viewer) ---------------- */

async function fetchSystemLogs() {
  const consoleEl = document.getElementById("system-log-console");
  if (!consoleEl) return;

  try {
    const data = await api("/system/logs?limit=150");
    if (!data.logs || data.logs.length === 0) {
      consoleEl.innerHTML = `<span style="color:#64748b;">(هیچ لاگی در سیستم ثبت نشده است)</span>`;
      return;
    }
    consoleEl.innerHTML = data.logs.map(log => {
      const cls = log.level || "INFO";
      return `<div class="log-line ${cls}">[${esc(log.time)}] [${esc(log.level)}] [${esc(log.logger)}]: ${esc(log.message)}</div>`;
    }).join("");
    consoleEl.scrollTop = consoleEl.scrollHeight;
  } catch (err) {
    consoleEl.innerHTML = `<span style="color:#ef4444;">خطا در دریافت لاگ‌ها: ${esc(err.message)}</span>`;
  }
}

document.getElementById("btn-refresh-logs")?.addEventListener("click", () => {
  fetchSystemLogs();
  showToast("لاگ‌های سیستم بروزرسانی شدند", "success");
});

document.getElementById("btn-clear-logs")?.addEventListener("click", async () => {
  if (!confirm("آیا مایل به پاکسازی کنسول لاگ‌ها هستید؟")) return;
  try {
    await api("/system/logs", { method: "DELETE" });
    const consoleEl = document.getElementById("system-log-console");
    if (consoleEl) consoleEl.innerHTML = `<span style="color:#64748b;">(کنسول لاگ‌ها پاکسازی شد)</span>`;
    showToast("کنسول لاگ‌ها پاکسازی شد", "success");
  } catch (err) {
    showToast(err.message, "error");
  }
});

// دریافت دوره‌ای لاگ‌ها فقط در صورتی که وب‌سوکت قطع باشد (Fallback)
setInterval(() => {
  const autoCheckbox = document.getElementById("log-auto-refresh");
  if (autoCheckbox && autoCheckbox.checked && activeTab === "settings" && (!ws || ws.readyState !== WebSocket.OPEN)) {
    fetchSystemLogs();
  }
}, 10000);

/* ---------------- به‌روزرسانی پنل (1-Click Updater) ---------------- */

async function fetchVersionInfo() {
  const localBadge = document.getElementById("updater-local-badge");
  const localDate = document.getElementById("updater-local-date");
  const remoteBadge = document.getElementById("updater-remote-badge");
  const remoteDate = document.getElementById("updater-remote-date");
  const statusBadge = document.getElementById("updater-status-badge");
  const statusSub = document.getElementById("updater-status-sub");
  const commitBox = document.getElementById("updater-commit-box");
  const commitMsg = document.getElementById("updater-commit-msg");
  const runBtn = document.getElementById("btn-run-update");
  const alertEl = document.getElementById("updater-alert");

  if (!localBadge) return;

  statusBadge.textContent = "در حال بررسی…";
  statusBadge.style.background = "rgba(100, 116, 139, 0.15)";
  statusBadge.style.color = "#94a3b8";
  statusBadge.style.border = "1px solid rgba(100, 116, 139, 0.3)";

  try {
    const data = await api("/system/version");
    localBadge.textContent = data.local_commit || "-";
    if (localDate) localDate.textContent = data.local_date ? `تاریخ: ${data.local_date}` : "";
    remoteBadge.textContent = data.remote_commit || "-";
    if (remoteDate) remoteDate.textContent = data.remote_date ? `تاریخ: ${data.remote_date}` : "";

    if (data.remote_message && commitBox && commitMsg) {
      commitMsg.textContent = data.remote_message;
      commitBox.style.display = "block";
    }

    if (data.has_update) {
      statusBadge.textContent = "نسخه جدید موجود است 🚀";
      statusBadge.style.background = "rgba(245, 158, 11, 0.15)";
      statusBadge.style.color = "#fbbf24";
      statusBadge.style.border = "1px solid rgba(245, 158, 11, 0.3)";
      if (statusSub) statusSub.textContent = data.status;
      if (runBtn) {
        runBtn.disabled = false;
        runBtn.textContent = "🚀 به‌روزرسانی به آخرین نسخه";
        runBtn.style.opacity = "1";
      }
      if (alertEl) {
        alertEl.textContent = "یک نسخه جدیدتر در گیت‌هاب یافت شد. جهت اعمال، روی دکمه به‌روزرسانی کلیک کنید.";
        alertEl.style.color = "#fbbf24";
      }
    } else if (data.error) {
      statusBadge.textContent = "خطا در بررسی";
      statusBadge.style.background = "rgba(239, 68, 68, 0.15)";
      statusBadge.style.color = "#f87171";
      statusBadge.style.border = "1px solid rgba(239, 68, 68, 0.3)";
      if (statusSub) statusSub.textContent = data.error;
    } else {
      statusBadge.textContent = "سیستم به‌روز است ✓";
      statusBadge.style.background = "rgba(16, 185, 129, 0.15)";
      statusBadge.style.color = "#34d399";
      statusBadge.style.border = "1px solid rgba(16, 185, 129, 0.3)";
      if (statusSub) statusSub.textContent = data.status;
      if (alertEl) {
        alertEl.textContent = "سیستم شما با آخرین کامیت مخزن گیت‌هاب همگام است.";
        alertEl.style.color = "#10b981";
      }
    }
  } catch (err) {
    statusBadge.textContent = "خطا";
    statusBadge.style.background = "rgba(239, 68, 68, 0.15)";
    statusBadge.style.color = "#f87171";
    if (statusSub) statusSub.textContent = err.message;
  }
}

document.getElementById("btn-check-update")?.addEventListener("click", async () => {
  const btn = document.getElementById("btn-check-update");
  btn.disabled = true;
  await fetchVersionInfo();
  btn.disabled = false;
  showToast("وضعیت نسخه بررسی شد", "success");
});

document.getElementById("btn-run-update")?.addEventListener("click", async () => {
  if (!confirm("آیا از به‌روزرسانی پنل به آخرین نسخه مخزن گیت‌هاب اطمینان دارید؟\nدر طول این فرآیند، کدهای جدید دریافت شده و سرویس پنل ریستارت خواهد شد.")) {
    return;
  }

  const runBtn = document.getElementById("btn-run-update");
  const checkBtn = document.getElementById("btn-check-update");
  const indicator = document.getElementById("updater-loading-indicator");
  const loadingText = document.getElementById("updater-loading-text");
  const alertEl = document.getElementById("updater-alert");

  runBtn.disabled = true;
  if (checkBtn) checkBtn.disabled = true;
  indicator?.classList.remove("hidden");
  if (alertEl) {
    alertEl.textContent = "در حال ارسال دستور به‌روزرسانی به سرور...";
    alertEl.style.color = "#38bdf8";
  }

  try {
    const res = await api("/system/update", { method: "POST" });
    if (!res.success) {
      throw new Error(res.message || "خطا در فرآیند به‌روزرسانی");
    }

    showToast("دستور به‌روزرسانی با موفقیت صادر شد 🚀", "success");
    if (alertEl) {
      alertEl.textContent = res.message;
      alertEl.style.color = "#10b981";
    }

    // شمارش معکوس جهت رفرش صفحه پس از ریستارت سرویس
    let countdown = 10;
    if (loadingText) loadingText.textContent = `در حال ریستارت سرویس... بارگذاری خودکار صفحه در ${countdown} ثانیه`;

    const timer = setInterval(() => {
      countdown -= 1;
      if (countdown > 0) {
        if (loadingText) loadingText.textContent = `در حال ریستارت سرویس... بارگذاری خودکار صفحه در ${countdown} ثانیه`;
      } else {
        clearInterval(timer);
        if (loadingText) loadingText.textContent = "در حال بارگذاری مجدد پنل...";
        window.location.reload();
      }
    }, 1000);

  } catch (err) {
    showToast(err.message, "error");
    if (alertEl) {
      alertEl.textContent = `❌ ${err.message}`;
      alertEl.style.color = "#ef4444";
    }
    runBtn.disabled = false;
    if (checkBtn) checkBtn.disabled = false;
    indicator?.classList.add("hidden");
  }
});

/* ---------------- اتصال زنده وب‌سوکت (Real-Time WebSocket) ---------------- */

let ws = null;
let wsReconnectTimer = null;
let wsPingInterval = null;

function initWebSocket() {
  if (ws && (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING)) {
    return;
  }

  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  const wsUrl = `${protocol}//${window.location.host}/ws`;

  try {
    ws = new WebSocket(wsUrl);

    ws.onopen = () => {
      console.log("WebSocket connected 🟢 (Real-Time Push فعال شد)");
      clearInterval(wsPingInterval);
      wsPingInterval = setInterval(() => {
        if (ws && ws.readyState === WebSocket.OPEN) {
          ws.send(JSON.stringify({ type: "ping" }));
        }
      }, 25000);
    };

    ws.onmessage = (event) => {
      try {
        const payload = JSON.parse(event.data);
        handleWsEvent(payload);
      } catch (err) {
        console.debug("WS parse error:", err);
      }
    };

    ws.onclose = () => {
      console.log("WebSocket disconnected 🔴 (تلاش مجدد پس از ۳ ثانیه...)");
      clearInterval(wsPingInterval);
      clearTimeout(wsReconnectTimer);
      wsReconnectTimer = setTimeout(initWebSocket, 3000);
    };

    ws.onerror = () => {
      try { ws.close(); } catch (_) {}
    };
  } catch (err) {
    console.debug("WS init error:", err);
    clearTimeout(wsReconnectTimer);
    wsReconnectTimer = setTimeout(initWebSocket, 4000);
  }
}

function handleWsEvent(payload) {
  if (!payload || !payload.type) return;

  if (payload.type === "new_message") {
    const { message, customer } = payload.data || {};
    if (!message) return;

    // ۱. به‌روزرسانی یا درج گفتگو در بالای لیست
    if (customer && customer.id) {
      const custId = customer.id;
      let convIndex = conversationsCache.findIndex(c => c.customer && c.customer.id === custId);
      if (convIndex !== -1) {
        const conv = conversationsCache[convIndex];
        conv.last_message = message;
        conversationsCache.splice(convIndex, 1);
        conversationsCache.unshift(conv);
      } else {
        conversationsCache.unshift({
          customer: customer,
          last_message: message
        });
      }
      renderConversationsList(conversationsCache);
    }

    // ۲. اگر چت این کاربر در صفحه باز است، پیام را آنی اضافه کن
    if (selectedCustomerId && customer && selectedCustomerId === customer.id) {
      if (!messagesCache[customer.id]) {
        messagesCache[customer.id] = [];
      }

      const existingIdx = messagesCache[customer.id].findIndex(m => 
        (m.id && m.id === message.id) || 
        (m._pending && m.text === message.text && m.sender === message.sender)
      );

      if (existingIdx !== -1) {
        messagesCache[customer.id][existingIdx] = message;
      } else {
        messagesCache[customer.id].push(message);
      }

      renderMessageList(messagesCache[customer.id]);
    }
  } else if (payload.type === "system_log") {
    // درج بلادرنگ لاگ زنده در کنسول بدون نیاز به پولینگ
    const log = payload.data;
    const consoleEl = document.getElementById("system-log-console");
    if (consoleEl && log && activeTab === "settings") {
      const cls = log.level || "INFO";
      const logLine = document.createElement("div");
      logLine.className = `log-line ${cls}`;
      logLine.textContent = `[${log.time}] [${log.level}] [${log.logger}]: ${log.message}`;
      consoleEl.appendChild(logLine);
      
      if (consoleEl.children.length > 500) {
        consoleEl.removeChild(consoleEl.firstChild);
      }
      consoleEl.scrollTop = consoleEl.scrollHeight;
    }
  }
}

/* ---------------- پشتیبان همگام‌سازی دوره‌ای (Fallback Sync) ---------------- */

setInterval(async () => {
  if (loginOverlay.classList.contains("hidden")) {
    // فقط در صورتی که وب‌سوکت قطع باشد، پولینگ آرام انجام بده
    if (!ws || ws.readyState !== WebSocket.OPEN) {
      if (activeTab === "conversations") {
        await loadConversations(true);
        if (selectedCustomerId) await loadChatMessages();
      } else if (activeTab === "dashboard") {
        await loadDashboardStatus();
      }
    }
  }
}, 30_000);

/* ---------------- راه‌اندازی ---------------- */

async function init() {
  try {
    const settings = await api("/settings/");
    updateBotBadge(settings.bot_enabled);
    await loadDashboardStatus();
    initWebSocket();
  } catch (err) {
    if (err.message !== "unauthorized") showToast(err.message, "error");
  }
}

init();
