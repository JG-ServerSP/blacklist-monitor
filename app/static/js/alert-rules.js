let rulesCache = [];
let usersCache = [];
let editingRuleId = null;

async function loadUsersForNotify() {
  try {
    usersCache = await api("/api/users");
    const select = document.getElementById("rule-notify-user");
    select.innerHTML = `<option value="">${t("alertRules.noneOption")}</option>` +
      usersCache.map(u => `<option value="${u.id}">${u.name || u.email} (${u.email})</option>`).join("");
  } catch (e) { /* apenas admin lista usuários; segue sem essa opção se falhar */ }
}

function channelLabel(c) {
  if (c.type === "email") return `📧 ${c.to}`;
  if (c.type === "pushover") return `📱 ${c.user_key}`;
  if (c.type === "user") {
    const u = usersCache.find(x => x.id === c.user_id);
    return `👤 ${u ? (u.name || u.email) : "#" + c.user_id}`;
  }
  return c.type;
}

async function loadRules() {
  rulesCache = await api("/api/alert-rules");
  document.getElementById("rules-empty").style.display = rulesCache.length ? "none" : "block";
  document.getElementById("rules-tbody").innerHTML = rulesCache.map(r => {
    const cond = r.conditions || {};
    const condParts = [];
    if (cond.on_error) {
      condParts.push(t("alertRules.onErrorCond"));
    } else {
      if (cond.min_severity) condParts.push(t("alertRules.severityAtLeast", { sev: severityLabel(cond.min_severity) }));
      condParts.push(cond.on_resolution ? t("alertRules.onResolutionCond") : t("alertRules.onEnterCond"));
    }
    const channels = (r.channels || []).map(channelLabel).join(", ") || "—";
    return `
      <tr>
        <td>${r.name}</td>
        <td>${condParts.join(", ")}</td>
        <td>${channels}</td>
        <td>${r.enabled ? "✅ " + t("alertRules.active") : "⏸️ " + t("alertRules.inactive")}</td>
        <td style="white-space:nowrap;"><button class="btn btn-outline" style="padding:4px 10px;font-size:12px;" onclick="editRule(${r.id})">${t("common.edit")}</button></td>
        <td><button class="btn btn-danger" style="padding:4px 10px;font-size:12px;" onclick="deleteRule(${r.id})">${t("alertRules.remove")}</button></td>
      </tr>`;
  }).join("");
}

function openRuleModal() {
  editingRuleId = null;
  document.getElementById("rule-modal-title").textContent = t("alertRules.modalTitleNew");
  document.getElementById("rule-name").value = "";
  document.getElementById("rule-min-severity").value = "";
  document.getElementById("rule-on-resolution").value = "enter";
  document.getElementById("rule-email-to").value = "";
  document.getElementById("rule-pushover-key").value = "";
  document.getElementById("rule-notify-user").value = "";
  document.getElementById("rule-enabled").value = "true";
  document.getElementById("rule-modal").style.display = "flex";
}

function editRule(id) {
  const r = rulesCache.find(x => x.id === id);
  if (!r) return;
  editingRuleId = id;
  const cond = r.conditions || {};
  const emailChannel = (r.channels || []).find(c => c.type === "email");
  const pushoverChannel = (r.channels || []).find(c => c.type === "pushover");
  const userChannel = (r.channels || []).find(c => c.type === "user");
  document.getElementById("rule-modal-title").textContent = t("alertRules.modalTitleEdit", { name: r.name });
  document.getElementById("rule-name").value = r.name;
  document.getElementById("rule-min-severity").value = cond.min_severity || "";
  document.getElementById("rule-on-resolution").value = cond.on_error ? "error" : (cond.on_resolution ? "resolution" : "enter");
  document.getElementById("rule-email-to").value = emailChannel ? emailChannel.to : "";
  document.getElementById("rule-pushover-key").value = pushoverChannel ? pushoverChannel.user_key : "";
  document.getElementById("rule-notify-user").value = userChannel ? userChannel.user_id : "";
  document.getElementById("rule-enabled").value = r.enabled ? "true" : "false";
  document.getElementById("rule-modal").style.display = "flex";
}

function closeRuleModal() { document.getElementById("rule-modal").style.display = "none"; }

async function submitRule() {
  const name = document.getElementById("rule-name").value.trim();
  if (!name) { toast(t("alertRules.enterName"), "error"); return; }
  const channels = [];
  const emailTo = document.getElementById("rule-email-to").value.trim();
  const pushoverKey = document.getElementById("rule-pushover-key").value.trim();
  const notifyUserId = document.getElementById("rule-notify-user").value;
  if (emailTo) channels.push({ type: "email", to: emailTo });
  if (pushoverKey) channels.push({ type: "pushover", user_key: pushoverKey });
  if (notifyUserId) channels.push({ type: "user", user_id: parseInt(notifyUserId) });
  const minSeverity = document.getElementById("rule-min-severity").value;
  const trigger = document.getElementById("rule-on-resolution").value;
  const body = {
    name,
    conditions: {
      min_severity: minSeverity || null,
      on_resolution: trigger === "resolution",
      on_error: trigger === "error",
    },
    channels,
    escalation: {},
    enabled: document.getElementById("rule-enabled").value === "true",
  };
  try {
    if (editingRuleId) {
      await api(`/api/alert-rules/${editingRuleId}`, { method: "PUT", body: JSON.stringify(body) });
      toast(t("alertRules.updated"), "success");
    } else {
      await api("/api/alert-rules", { method: "POST", body: JSON.stringify(body) });
      toast(t("alertRules.created"), "success");
    }
    closeRuleModal();
    loadRules();
  } catch (e) { toast(e.message, "error"); }
}
async function deleteRule(id) {
  if (!confirm(t("alertRules.confirmDelete"))) return;
  try { await api(`/api/alert-rules/${id}`, { method: "DELETE" }); loadRules(); }
  catch (e) { toast(e.message, "error"); }
}
requireAuth().then(() => loadUsersForNotify().then(loadRules));
