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
  const password = document.getElementById("login-password").value;
  try {
    await api("/auth/login", {
      method: "POST",
      body: JSON.stringify({ password }),
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

/* ---------------- تب‌ها ---------------- */

const loaders = {
  keywords: loadKeywords,
  conversations: loadConversations,
  products: loadProducts,
  settings: loadSettings,
};
let activeTab = "keywords";

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

async function loadKeywords() {
  keywordsCache = await api("/keywords/");
  const tbody = document.getElementById("keywords-body");
  document.getElementById("keywords-empty").classList.toggle("hidden", keywordsCache.length > 0);

  tbody.innerHTML = keywordsCache.map((k) => `
    <tr>
      <td class="kw-text">${esc(k.keyword)}</td>
      <td class="kw-response">${esc(k.response)}</td>
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
  `).join("");
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
  document.getElementById("keyword-submit").textContent = "ذخیره تغییرات";
  document.getElementById("keyword-cancel").classList.remove("hidden");
  document.getElementById("keyword-input").focus();
}

function resetKeywordForm() {
  editingKeywordId = null;
  document.getElementById("keyword-form").reset();
  document.getElementById("keyword-form-title").textContent = "افزودن کلمه کلیدی";
  document.getElementById("keyword-submit").textContent = "افزودن";
  document.getElementById("keyword-cancel").classList.add("hidden");
}

document.getElementById("keyword-cancel").addEventListener("click", resetKeywordForm);

document.getElementById("keyword-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const body = JSON.stringify({
    keyword: document.getElementById("keyword-input").value,
    response: document.getElementById("keyword-response-input").value,
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
  document.getElementById("fallback-message").value = settings.fallback_message;
  document.getElementById("follow-gate-enabled").checked = settings.follow_gate_enabled;
  document.getElementById("follow-gate-message").value = settings.follow_gate_message;
  updateBotStatusText(settings.bot_enabled);
  updateBotBadge(settings.bot_enabled);
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

/* ---------------- رفرش خودکار گفتگوها ---------------- */

setInterval(async () => {
  // فقط وقتی تب گفتگوها باز و کاربر وارد شده است رفرش کن
  if (activeTab !== "conversations" || !loginOverlay.classList.contains("hidden")) return;
  await loadConversations();
  if (selectedCustomerId) await loadChatMessages();
}, 10_000);

/* ---------------- راه‌اندازی ---------------- */

async function init() {
  try {
    const settings = await api("/settings/");
    updateBotBadge(settings.bot_enabled);
    await loadKeywords();
  } catch (err) {
    if (err.message !== "unauthorized") showToast(err.message, "error");
  }
}

init();
