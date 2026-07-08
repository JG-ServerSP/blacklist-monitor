const PING_MODE_LABEL_KEY = {
  skip_unreachable: "groups.pingModeSkipDefault",
  check_all: "groups.pingModeCheckAll",
  tcp_fallback: "groups.pingModeTcpFallback",
};

let groupsCache = [];
let editingGroupId = null;

async function loadGroups() {
  groupsCache = await api("/api/groups");
  const tbody = document.getElementById("groups-tbody");
  document.getElementById("groups-empty").style.display = groupsCache.length ? "none" : "block";
  tbody.innerHTML = groupsCache.map(r => `
    <tr>
      <td>${r.name}</td>
      <td>${r.datacenter || "—"}</td>
      <td>${PING_MODE_LABEL_KEY[r.ping_mode] ? t(PING_MODE_LABEL_KEY[r.ping_mode]) : r.ping_mode}</td>
      <td>${r.check_interval_minutes || t("ips.globalDefault")}</td>
      <td style="white-space:nowrap;"><button class="btn btn-outline" style="padding:4px 10px;font-size:12px;" onclick="editGroup(${r.id})">${t("common.edit")}</button></td>
      <td><button class="btn btn-danger" style="padding:4px 10px;font-size:12px;" onclick="deleteGroup(${r.id})">${t("groups.remove")}</button></td>
    </tr>`).join("");
}

function openGroupModal() {
  editingGroupId = null;
  document.getElementById("group-modal-title").textContent = t("groups.modalTitleNew");
  document.getElementById("group-name").value = "";
  document.getElementById("group-dc").value = "";
  document.getElementById("group-ping-mode").value = "skip_unreachable";
  document.getElementById("group-interval").value = "";
  document.getElementById("group-modal").style.display = "flex";
}

function editGroup(id) {
  const r = groupsCache.find(g => g.id === id);
  if (!r) return;
  editingGroupId = id;
  document.getElementById("group-modal-title").textContent = t("groups.modalTitleEdit", { name: r.name });
  document.getElementById("group-name").value = r.name;
  document.getElementById("group-dc").value = r.datacenter || "";
  document.getElementById("group-ping-mode").value = r.ping_mode;
  document.getElementById("group-interval").value = r.check_interval_minutes || "";
  document.getElementById("group-modal").style.display = "flex";
}

function closeGroupModal() { document.getElementById("group-modal").style.display = "none"; }

async function submitGroup() {
  const name = document.getElementById("group-name").value.trim();
  if (!name) { toast(t("groups.enterName"), "error"); return; }
  const interval = document.getElementById("group-interval").value;
  const body = {
    name,
    datacenter: document.getElementById("group-dc").value || null,
    ping_mode: document.getElementById("group-ping-mode").value,
    check_interval_minutes: interval ? parseInt(interval) : null,
  };
  try {
    if (editingGroupId) {
      await api(`/api/groups/${editingGroupId}`, { method: "PUT", body: JSON.stringify(body) });
      toast(t("groups.updated"), "success");
    } else {
      await api("/api/groups", { method: "POST", body: JSON.stringify(body) });
      toast(t("groups.created"), "success");
    }
    closeGroupModal();
    loadGroups();
  } catch (e) { toast(e.message, "error"); }
}
async function deleteGroup(id) {
  if (!confirm(t("groups.confirmDelete"))) return;
  try { await api(`/api/groups/${id}`, { method: "DELETE" }); loadGroups(); }
  catch (e) { toast(e.message, "error"); }
}
requireAuth().then(loadGroups);
