const ROLE_LABEL_KEY = { admin: "users.roleAdmin", operator: "users.roleOperator", readonly: "users.roleReadonly" };

let usersCache = [];
let editingUserId = null;

async function loadUsers() {
  usersCache = await api("/api/users");
  const me = Auth.getUser();
  const tbody = document.getElementById("users-tbody");
  document.getElementById("users-empty").style.display = usersCache.length ? "none" : "block";
  tbody.innerHTML = usersCache.map(r => {
    const isSelf = me && me.id === r.id;
    return `
    <tr>
      <td>${r.name || "—"}</td>
      <td>${r.email}</td>
      <td>${ROLE_LABEL_KEY[r.role] ? t(ROLE_LABEL_KEY[r.role]) : r.role}</td>
      <td>${r.totp_enabled ? "✅ " + t("users.active") : "—"}</td>
      <td>${r.is_active ? "✅ " + t("users.active") : "⏸️ " + t("users.inactive")}</td>
      <td>${fmtDateOnly(r.created_at)}</td>
      <td style="white-space:nowrap;"><button class="btn btn-outline" style="padding:4px 10px;font-size:12px;" onclick="editUser(${r.id})">${t("users.edit")}</button></td>
      <td style="white-space:nowrap;">${r.totp_enabled ? `<button class="btn btn-outline" style="padding:4px 10px;font-size:12px;" onclick="disable2FA(${r.id})">${t("users.disable2fa")}</button>` : ""}</td>
      <td>${isSelf ? "" : `<button class="btn btn-danger" style="padding:4px 10px;font-size:12px;" onclick="deleteUser(${r.id})">${t("users.remove")}</button>`}</td>
    </tr>`;
  }).join("");
}

function openUserModal() {
  editingUserId = null;
  document.getElementById("user-modal-title").textContent = t("users.modalTitleNew");
  document.getElementById("user-name").value = "";
  document.getElementById("user-email").value = "";
  document.getElementById("user-email").disabled = false;
  document.getElementById("user-role").value = "operator";
  document.getElementById("user-status-field").style.display = "none";
  document.getElementById("user-active").value = "true";
  document.getElementById("user-password-label").textContent = t("users.labelPassword");
  document.getElementById("user-password").placeholder = t("users.passwordPlaceholderNew");
  document.getElementById("user-password").value = "";
  document.getElementById("user-modal").style.display = "flex";
}

function editUser(id) {
  const r = usersCache.find(u => u.id === id);
  if (!r) return;
  editingUserId = id;
  document.getElementById("user-modal-title").textContent = t("users.modalTitleEdit", { email: r.email });
  document.getElementById("user-name").value = r.name || "";
  document.getElementById("user-email").value = r.email;
  document.getElementById("user-email").disabled = true;
  document.getElementById("user-role").value = r.role;
  document.getElementById("user-status-field").style.display = "";
  document.getElementById("user-active").value = r.is_active ? "true" : "false";
  document.getElementById("user-password-label").textContent = t("users.labelNewPassword");
  document.getElementById("user-password").placeholder = t("users.passwordPlaceholderEdit");
  document.getElementById("user-password").value = "";
  document.getElementById("user-modal").style.display = "flex";
}

function closeUserModal() { document.getElementById("user-modal").style.display = "none"; }

async function submitUser() {
  const name = document.getElementById("user-name").value.trim();
  const email = document.getElementById("user-email").value.trim();
  const password = document.getElementById("user-password").value;
  const role = document.getElementById("user-role").value;

  if (!editingUserId) {
    if (!email) { toast(t("users.enterEmail"), "error"); return; }
    if (!password || password.length < 8) { toast(t("users.passwordTooShortNew"), "error"); return; }
    try {
      await api("/api/users", { method: "POST", body: JSON.stringify({ email, name, password, role }) });
      toast(t("users.created"), "success");
      closeUserModal();
      loadUsers();
    } catch (e) { toast(e.message, "error"); }
    return;
  }

  if (password && password.length < 8) { toast(t("users.passwordTooShortEdit"), "error"); return; }
  const body = { name, role, is_active: document.getElementById("user-active").value === "true" };
  if (password) body.password = password;
  try {
    await api(`/api/users/${editingUserId}`, { method: "PUT", body: JSON.stringify(body) });
    toast(t("users.updated"), "success");
    closeUserModal();
    loadUsers();
  } catch (e) { toast(e.message, "error"); }
}

async function disable2FA(id) {
  if (!confirm(t("users.confirmDisable2fa"))) return;
  try {
    await api(`/api/users/${id}/disable-2fa`, { method: "POST" });
    toast(t("users.disabled2fa"), "success");
    loadUsers();
  } catch (e) { toast(e.message, "error"); }
}

async function deleteUser(id) {
  if (!confirm(t("users.confirmDelete"))) return;
  try {
    await api(`/api/users/${id}`, { method: "DELETE" });
    toast(t("users.deleted"), "success");
    loadUsers();
  } catch (e) { toast(e.message, "error"); }
}

requireAuth().then(loadUsers);
