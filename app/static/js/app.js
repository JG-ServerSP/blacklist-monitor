// Shared helpers: auth-aware fetch, toasts, formatting.

const Auth = {
  getToken() { return localStorage.getItem("bm_token"); },
  setToken(t) { localStorage.setItem("bm_token", t); },
  clear() { localStorage.removeItem("bm_token"); localStorage.removeItem("bm_user"); },
  getUser() {
    const raw = localStorage.getItem("bm_user");
    return raw ? JSON.parse(raw) : null;
  },
  setUser(u) { localStorage.setItem("bm_user", JSON.stringify(u)); },
};

async function api(path, options = {}) {
  const headers = Object.assign({ "Content-Type": "application/json" }, options.headers || {});
  const token = Auth.getToken();
  if (token) headers["Authorization"] = "Bearer " + token;
  const resp = await fetch(path, Object.assign({}, options, { headers }));
  if (resp.status === 401 && path !== "/api/auth/login") {
    // Every API route (besides login itself) requires a valid session — any
    // 401 means the token is missing/expired, so bounce to the login page.
    Auth.clear();
    if (!window.location.pathname.startsWith("/login")) {
      window.location.href = "/login";
    }
  }
  if (!resp.ok) {
    let detail = resp.statusText;
    try { const j = await resp.json(); detail = j.detail || JSON.stringify(j); } catch (e) {}
    throw new Error(detail);
  }
  const ct = resp.headers.get("content-type") || "";
  if (ct.includes("application/json")) return resp.json();
  return resp.text();
}

// Call at the top of every protected page. Redirects to /login immediately
// if there's no token, and again if the token turns out to be invalid/expired.
async function requireAuth() {
  if (!Auth.getToken()) {
    window.location.href = "/login";
    return Promise.reject(new Error("not authenticated"));
  }
  try {
    const user = await api("/api/auth/me");
    Auth.setUser(user);
    // Personal language overrides the server-rendered system default (set via
    // data-lang on <html>). Re-applies translations if it actually changed.
    if (user.language && I18N_SUPPORTED.includes(user.language) && document.documentElement.getAttribute("data-lang") !== user.language) {
      document.documentElement.setAttribute("data-lang", user.language);
      applyI18n();
    }
    return user;
  } catch (e) {
    throw e;
  }
}

function toast(message, type = "success") {
  let container = document.querySelector(".toast-container");
  if (!container) {
    container = document.createElement("div");
    container.className = "toast-container";
    document.body.appendChild(container);
  }
  const el = document.createElement("div");
  el.className = `toast ${type}`;
  el.textContent = message;
  container.appendChild(el);
  setTimeout(() => el.remove(), 4500);
}

function severityLabel(sev) { return t(`severity.${sev}`); }
const SEVERITY_ORDER = ["critical", "high", "medium", "low"];
function statusLabel(status) { return t(`status.${status}`); }
const STATUS_CLASS = { clean: "low", listed: "critical", unchecked: "medium", error: "high" };
function pingLabel(status) { return t(`ping.${status}`); }

function severityBadge(sev) {
  return `<span class="badge-sev badge-${sev}"><span class="dot-sev dot-${sev}"></span>${severityLabel(sev)}</span>`;
}

function fmtDate(iso) {
  if (!iso) return "—";
  const d = new Date(iso);
  const locale = i18nLocale();
  return d.toLocaleDateString(locale) + " " + d.toLocaleTimeString(locale, { hour: "2-digit", minute: "2-digit" });
}

function fmtDateOnly(iso) {
  if (!iso) return "—";
  return new Date(iso).toLocaleDateString(i18nLocale());
}

async function loadTopbarCounts() {
  try {
    const listings = await api("/api/listings?active_only=true&limit=500");
    const bellCount = document.getElementById("bell-count");
    if (bellCount) {
      if (listings.length > 0) { bellCount.textContent = listings.length; bellCount.style.display = ""; }
      else { bellCount.style.display = "none"; }
    }
  } catch (e) { /* dashboard should still render without this */ }
}

async function toggleNotifPopup() {
  const popup = document.getElementById("notif-popup");
  if (!popup) return;
  const opening = popup.style.display === "none";
  popup.style.display = opening ? "block" : "none";
  if (opening) {
    const list = document.getElementById("notif-popup-list");
    list.innerHTML = `<div class="empty-state" style="padding:16px;">${t("topbar.loading")}</div>`;
    try {
      const items = await api("/api/activity?limit=6");
      list.innerHTML = items.map(a => {
        const meta = ACTIVITY_ICON[a.action] || { icon: "ℹ️", bg: "rgba(148,163,184,.15)" };
        const label = activityLabel(a);
        return `
          <div class="activity-item">
            <span class="activity-icon" style="background:${meta.bg};">${meta.icon}</span>
            <div style="flex:1;">
              <div>${label}</div>
              <div style="color:var(--text-muted);font-size:12px;">${fmtDate(a.created_at)}</div>
            </div>
          </div>`;
      }).join("") || `<div class="empty-state" style="padding:16px;">${t("topbar.noNotifications")}</div>`;
    } catch (e) {
      list.innerHTML = `<div class="empty-state" style="padding:16px;">${t("topbar.notificationsError")}</div>`;
    }
    // Marca como vistas: zera o contador do sino até a próxima novidade.
    const bellCount = document.getElementById("bell-count");
    if (bellCount) bellCount.style.display = "none";
  }
}

document.addEventListener("click", (e) => {
  const wrap = document.querySelector(".notif-wrap");
  const popup = document.getElementById("notif-popup");
  if (!wrap || !popup || popup.style.display === "none") return;
  if (!wrap.contains(e.target)) popup.style.display = "none";
});

function initTopbarUser() {
  const user = Auth.getUser();
  const nameEl = document.getElementById("topbar-username");
  const emailEl = document.getElementById("topbar-useremail");
  if (user) {
    if (nameEl) nameEl.textContent = user.name || user.email;
    if (emailEl) emailEl.textContent = user.email;
  }
  const logoutBtn = document.getElementById("logout-btn");
  if (logoutBtn) {
    logoutBtn.addEventListener("click", () => { Auth.clear(); window.location.href = "/login"; });
  }
}

document.addEventListener("DOMContentLoaded", () => {
  loadTopbarCounts();
  initTopbarUser();
});

const ACTIVITY_ICON = {
  listing_detected: { icon: "⚠️", bg: "rgba(239,68,68,.15)" },
  listing_removed: { icon: "✅", bg: "rgba(34,197,94,.15)" },
  delist_requested: { icon: "📤", bg: "rgba(234,179,8,.15)" },
  login: { icon: "🔑", bg: "rgba(139,92,246,.15)" },
  ip_import: { icon: "➕", bg: "rgba(59,130,246,.15)" },
  system_seed: { icon: "🌱", bg: "rgba(34,197,94,.15)" },
  password_changed: { icon: "🔒", bg: "rgba(139,92,246,.15)" },
  user_created: { icon: "👤", bg: "rgba(59,130,246,.15)" },
  user_updated: { icon: "✏️", bg: "rgba(234,179,8,.15)" },
  user_2fa_disabled: { icon: "🔓", bg: "rgba(239,68,68,.15)" },
};

function activityLabel(a) {
  const p = a.payload || {};
  if (!I18N["pt-BR"][`activity.${a.action}`]) return a.action;
  return t(`activity.${a.action}`, p);
}

async function exportReport() {
  const token = Auth.getToken();
  if (!token) { window.location.href = "/login"; return; }
  try {
    const resp = await fetch("/api/reports/export.csv", { headers: { Authorization: "Bearer " + token } });
    if (resp.status === 401) { Auth.clear(); window.location.href = "/login"; return; }
    if (!resp.ok) throw new Error(t("reports.exportError"));
    const blob = await resp.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "relatorio_blacklist.csv";
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  } catch (e) { toast(e.message, "error"); }
}

async function renderActivityFeed(containerId, limit = 12) {
  const items = await api(`/api/activity?limit=${limit}`);
  const feed = document.getElementById(containerId);
  feed.innerHTML = items.map(a => {
    const meta = ACTIVITY_ICON[a.action] || { icon: "ℹ️", bg: "rgba(148,163,184,.15)" };
    const label = activityLabel(a);
    return `
      <div class="activity-item">
        <span class="activity-icon" style="background:${meta.bg};">${meta.icon}</span>
        <div style="flex:1;">
          <div>${label}</div>
          <div style="color:var(--text-muted);font-size:12px;">${a.entity || ""}</div>
        </div>
        <div style="color:var(--text-muted);font-size:12px;white-space:nowrap;">${fmtDate(a.created_at)}</div>
      </div>`;
  }).join("") || `<div class="empty-state">${t("common.noActivity")}</div>`;
}
