async function loadSettings() {
  try {
    const s = await api("/api/settings");
    document.getElementById("s-smtp-host").value = s.smtp_host || "";
    document.getElementById("s-smtp-port").value = s.smtp_port || "";
    document.getElementById("s-smtp-user").value = s.smtp_user || "";
    document.getElementById("s-smtp-from").value = s.smtp_from || "";
    document.getElementById("s-resolvers").value = s.dns_resolvers || "";
    document.getElementById("s-interval").value = s.default_check_interval_minutes || "";
    document.getElementById("s-recheck").value = s.listed_ip_recheck_minutes || "";
    document.getElementById("s-log-level").value = s.log_level || "info";
    document.getElementById("s-timezone").value = s.timezone || "UTC";
    document.getElementById("s-language").value = s.language || "pt-BR";
  } catch (e) {
    toast(t("settings.loginRequired"), "error");
  }
}

async function loadMyNotifications() {
  const me = await api("/api/auth/me");
  document.getElementById("my-notify-email").value = me.notify_email || "";
  document.getElementById("my-pushover-key").value = me.pushover_user_key || "";
  document.getElementById("my-language").value = me.language || "";
}

async function saveMyLanguage() {
  const language = document.getElementById("my-language").value;
  try {
    const updated = await api("/api/auth/me/language", { method: "PUT", body: JSON.stringify({ language }) });
    Auth.setUser(updated);
    window.location.reload();
  } catch (e) { toast(e.message, "error"); }
}

async function saveMyNotifications() {
  const body = {
    notify_email: document.getElementById("my-notify-email").value.trim() || null,
    pushover_user_key: document.getElementById("my-pushover-key").value.trim() || null,
  };
  try {
    await api("/api/auth/me/notifications", { method: "PUT", body: JSON.stringify(body) });
    toast(t("settings.notificationsSaved"), "success");
  } catch (e) { toast(e.message, "error"); }
}

async function saveSettings() {
  const newLanguage = document.getElementById("s-language").value;
  const languageChanged = newLanguage !== i18nLang();
  const body = {
    smtp_host: document.getElementById("s-smtp-host").value || null,
    smtp_port: parseInt(document.getElementById("s-smtp-port").value) || null,
    smtp_use_tls: document.getElementById("s-smtp-tls").value === "true",
    smtp_user: document.getElementById("s-smtp-user").value || null,
    smtp_from: document.getElementById("s-smtp-from").value || null,
    dns_resolvers: document.getElementById("s-resolvers").value || null,
    default_check_interval_minutes: parseInt(document.getElementById("s-interval").value) || null,
    listed_ip_recheck_minutes: parseInt(document.getElementById("s-recheck").value) || null,
    log_level: document.getElementById("s-log-level").value,
    timezone: document.getElementById("s-timezone").value,
    language: newLanguage,
  };
  const smtpPassword = document.getElementById("s-smtp-password").value;
  const pushover = document.getElementById("s-pushover").value;
  const dqs = document.getElementById("s-dqs").value;
  if (smtpPassword) body.smtp_password = smtpPassword;
  if (pushover) body.pushover_app_token = pushover;
  if (dqs) body.spamhaus_dqs_key = dqs;
  try {
    await api("/api/settings", { method: "PUT", body: JSON.stringify(body) });
    if (languageChanged) {
      window.location.reload();
      return;
    }
    toast(t("settings.saved"), "success");
  } catch (e) { toast(e.message, "error"); }
}

let dbCheckIssues = [];

function renderDbCheckResult() {
  const box = document.getElementById("db-check-result");
  const cleanBtn = document.getElementById("db-clean-btn");
  if (!dbCheckIssues.length) {
    box.innerHTML = `<p style="color:var(--low);font-size:13px;">${t("settings.dbCheckClean")}</p>`;
    cleanBtn.style.display = "none";
    return;
  }
  const items = dbCheckIssues.map((i) => `<li style="margin-bottom:4px;">${i.detail}</li>`).join("");
  box.innerHTML = `
    <p style="color:var(--medium);font-size:13px;margin-bottom:6px;">${t("settings.dbIssuesFound", { count: dbCheckIssues.length })}</p>
    <ul style="font-size:12px;color:var(--text-muted);padding-left:18px;margin:0;">${items}</ul>`;
  cleanBtn.style.display = "inline-block";
}

async function checkDatabase() {
  try {
    const result = await api("/api/maintenance/db-check");
    dbCheckIssues = result.issues;
    renderDbCheckResult();
  } catch (e) { toast(e.message, "error"); }
}

async function cleanDatabase() {
  if (!confirm(t("settings.dbCleanConfirm", { count: dbCheckIssues.length }))) return;
  try {
    const result = await api("/api/maintenance/db-clean", { method: "POST" });
    toast(t("settings.dbCleanDone", { blocks: result.removed_blocks, ips: result.fixed_ips }), "success");
    await checkDatabase();
  } catch (e) { toast(e.message, "error"); }
}

async function changePassword() {
  const current_password = document.getElementById("pw-current").value;
  const new_password = document.getElementById("pw-new").value;
  if (!current_password || !new_password) { toast(t("settings.fillPasswords"), "error"); return; }
  try {
    await api("/api/auth/change-password", { method: "POST", body: JSON.stringify({ current_password, new_password }) });
    toast(t("settings.passwordChanged"), "success");
    document.getElementById("pw-current").value = "";
    document.getElementById("pw-new").value = "";
  } catch (e) { toast(e.message, "error"); }
}

requireAuth().then(() => { loadSettings(); loadMyNotifications(); });
