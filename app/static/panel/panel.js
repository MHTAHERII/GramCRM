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
  return new Intl.DateTimeFormat("fa-IR", {
    dateStyle: "short",
    timeStyle: "short",
  }).format(d);
}

function fmtNumber(n) {
  return new Intl.NumberFormat("fa-IR").format(n);
}

function showToast(message, type = "") {
  const toast = document.getElementById("toast");
  toast.textContent = message;
  toast.className = "toast " + type;
  clearTimeout(showToast._timer);
  showToast._timer = setTimeout(() => toast.classList.add("hidden"), 3200);
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
        desc.textContent = "ارتباط با سرورهای ابری Zernio و اینستاگرام پایدار است. وب‌هوک‌ها فعال هستند.";
        badge.textContent = "متصل 🟢";
        badge.style.background = "rgba(16, 185, 129, 0.15)";
        badge.style.color = "#10b981";
        badge.style.border = "1px solid rgba(16, 185, 129, 0.3)";
      } else {
        desc.textContent = "توکن API یا شناسه‌های اینستاگرام در تب تنظیمات وارد نشده است.";
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
    showToast("وضعیت کلمه کلیدی تغییر کرد", "success");
  } catch (err) {
    showToast(err.message, "error");
    loadKeywords();
  }
}

async function deleteKeyword(id) {
  if (!confirm("این کلمه کلیدی حذف شود؟")) return;
  try {
    await api(`/keywords/${id}`, { method: "DELETE" });
    showToast("کلمه کلیدی حذف شد", "success");
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
      showToast("کلمه کلیدی به‌روزرسانی شد", "success");
    } else {
      await api("/keywords/", { method: "POST", body });
      showToast("کلمه کلیدی اضافه شد", "success");
    }
    resetKeywordForm();
    loadKeywords();
  } catch (err) {
    showToast(err.message, "error");
  }
});

/* ---------------- گفتگوها ---------------- */

let selectedCustomerId = null;

const SENDER_LABEL = {
  customer: "مشتری",
  bot: "ربات",
  admin: "شما",
};

async function loadConversations() {
  const list = document.getElementById("conversation-list");
  let conversations;
  try {
    conversations = await api("/conversations/");
  } catch (err) {
    if (err.message === "unauthorized") return;
    list.innerHTML = `<div class="empty">خطا در دریافت گفتگوها</div>`;
    return;
  }

  if (!conversations.length) {
    list.innerHTML = `<div class="empty">هنوز گفتگویی وجود ندارد</div>`;
    return;
  }

  list.innerHTML = conversations.map((c) => {
    const customer = c.customer;
    const last = c.last_message;
    const name = customer.name || customer.username || "کاربر " + customer.instagram_id;
    const preview = last ? last.text : "بدون پیام";
    const time = last ? fmtTime(last.created_at) : "";
    return `
      <div class="conversation-item ${customer.id === selectedCustomerId ? "active" : ""}"
           onclick="selectConversation(${customer.id})">
        <div class="c-name">${esc(name)}</div>
        ${customer.username ? `<div class="c-username">@${esc(customer.username)}</div>` : ""}
        <div class="c-preview">${esc(preview)}</div>
        <div class="c-time">${time}</div>
      </div>
    `;
  }).join("");
}

async function selectConversation(customerId) {
  selectedCustomerId = customerId;
  loadConversations(); // برای به‌روزرسانی حالت active
  await loadChatMessages();
}

async function loadChatMessages() {
  if (!selectedCustomerId) return;
  const messagesBox = document.getElementById("chat-messages");
  const header = document.getElementById("chat-header");

  let customer, messages;
  try {
    customer = await api(`/customers/${selectedCustomerId}`);
    messages = await api(`/customers/${selectedCustomerId}/messages`);
  } catch (err) {
    if (err.message === "unauthorized") return;
    showToast(err.message, "error");
    return;
  }

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

  if (!messages.length) {
    messagesBox.innerHTML = `<div class="empty">پیامی رد و بدل نشده است</div>`;
    return;
  }

  messagesBox.innerHTML = messages.map((m) => `
    <div class="msg ${esc(m.sender)}">
      <div class="bubble">
        ${m.sender !== "customer" ? `<span class="sender">${SENDER_LABEL[m.sender] || m.sender}</span>` : ""}
        ${esc(m.text)}
        <span class="time">${fmtTime(m.created_at)}</span>
      </div>
    </div>
  `).join("");
  messagesBox.scrollTop = messagesBox.scrollHeight; // اسکرول به آخرین پیام
}

document.getElementById("chat-send-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  if (!selectedCustomerId) {
    showToast("اول یک گفتگو انتخاب کنید", "error");
    return;
  }
  const input = document.getElementById("chat-input");
  const text = input.value.trim();
  if (!text) return;

  try {
    const result = await api(`/customers/${selectedCustomerId}/send`, {
      method: "POST",
      body: JSON.stringify({ text }),
    });
    if (result.sent) showToast("پیام ارسال شد", "success");
    else showToast(result.detail || "ارسال به اینستاگرام ناموفق بود", "error");
    input.value = "";
    await loadChatMessages();
    await loadConversations();
  } catch (err) {
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
      showToast("محصول به‌روزرسانی شد", "success");
    } else {
      await api("/products/", { method: "POST", body });
      showToast("محصول اضافه شد", "success");
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
    showToast("محصول حذف شد", "success");
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

  // فیلد نام کاربری
  document.getElementById("setting-admin-username").value = settings.admin_username || "admin";
  document.getElementById("setting-admin-password").value = "";

  updateBotStatusText(settings.bot_enabled);
  updateBotBadge(settings.bot_enabled);
  await fetchSystemLogs();
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

document.getElementById("save-settings").addEventListener("click", async () => {
  const body = JSON.stringify({
    bot_enabled: document.getElementById("bot-enabled").checked,
    fallback_message: document.getElementById("fallback-message").value,
  });
  try {
    const updated = await api("/settings/", { method: "PUT", body });
    updateBotStatusText(updated.bot_enabled);
    updateBotBadge(updated.bot_enabled);
    showToast("تنظیمات ذخیره شد", "success");
  } catch (err) {
    showToast(err.message, "error");
  }
});

document.getElementById("save-follow-gate").addEventListener("click", async () => {
  const body = JSON.stringify({
    follow_gate_enabled: document.getElementById("follow-gate-enabled").checked,
    follow_gate_message: document.getElementById("follow-gate-message").value,
  });
  try {
    await api("/settings/", { method: "PUT", body });
    showToast("دروازه فالو ذخیره شد", "success");
  } catch (err) {
    showToast(err.message, "error");
  }
});

// ذخیره کلید و شناسه‌های API اینستاگرام (Zernio)
document.getElementById("save-api-settings")?.addEventListener("click", async () => {
  const apiKey = document.getElementById("setting-zernio-api-key").value.trim();
  const profileId = document.getElementById("setting-zernio-profile-id").value.trim();
  const accountId = document.getElementById("setting-zernio-account-id").value.trim();

  const body = JSON.stringify({
    zernio_api_key: apiKey || null,
    zernio_profile_id: profileId || null,
    zernio_account_id: accountId || null,
  });
  try {
    await api("/settings/", { method: "PUT", body });
    showToast("تنظیمات API با موفقیت ذخیره شد ✅", "success");
    const alertEl = document.getElementById("connection-status-alert");
    if (alertEl) {
      alertEl.textContent = "تنظیمات ذخیره شد. برای تست روی «بررسی وضعیت اتصال» کلیک کنید.";
      alertEl.style.color = "#818cf8";
    }
  } catch (err) {
    showToast(err.message, "error");
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
      alertEl.textContent = `${res.message} (تعداد اتوماسیون‌های فعال: ${res.automations_count ?? 0})`;
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
    showToast("اطلاعات ورود به پنل با موفقیت ذخیره شد 🔐", "success");
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

// بروزرسانی خودکار لاگ‌ها هر ۳ ثانیه اگر تیک زده شده باشد
setInterval(() => {
  const autoCheckbox = document.getElementById("log-auto-refresh");
  if (autoCheckbox && autoCheckbox.checked && activeTab === "settings") {
    fetchSystemLogs();
  }
}, 3000);

/* ---------------- رفرش خودکار گفتگوها و وضعیت سرور ---------------- */

setInterval(async () => {
  if (loginOverlay.classList.contains("hidden")) {
    if (activeTab === "conversations") {
      await loadConversations();
      if (selectedCustomerId) await loadChatMessages();
    } else if (activeTab === "dashboard") {
      await loadDashboardStatus();
    }
  }
}, 10_000);

/* ---------------- راه‌اندازی ---------------- */

async function init() {
  try {
    const settings = await api("/settings/");
    updateBotBadge(settings.bot_enabled);
    await loadDashboardStatus();
  } catch (err) {
    if (err.message !== "unauthorized") showToast(err.message, "error");
  }
}

init();
