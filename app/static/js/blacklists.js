const TYPE_LABEL_KEY = { ipv4: "blacklists.typeIpv4", ipv6: "blacklists.typeIpv6", domain: "blacklists.typeDomain" };

let blCache = [];
let editingBLId = null;

async function loadBlacklists() {
  blCache = await api("/api/blacklists");
  document.getElementById("bl-tbody").innerHTML = blCache.map(r => `
    <tr>
      <td>${r.name}</td>
      <td style="font-family:monospace;font-size:12px;">${r.zone}</td>
      <td>${TYPE_LABEL_KEY[r.type] ? t(TYPE_LABEL_KEY[r.type]) : r.type}</td>
      <td>${severityBadge(r.default_severity)}</td>
      <td>${r.rate_limit_qps}</td>
      <td>${r.requires_key ? (r.has_key ? t("blacklists.keyConfigured") : t("blacklists.keyPending")) : "—"}</td>
      <td>
        <label style="display:flex;align-items:center;gap:6px;cursor:pointer;">
          <input type="checkbox" ${r.enabled ? "checked" : ""} onchange="toggleBL(${r.id})"> ${r.enabled ? t("blacklists.enabledActive") : t("blacklists.enabledInactive")}
        </label>
      </td>
      <td style="white-space:nowrap;"><button class="btn btn-outline" style="padding:4px 10px;font-size:12px;" onclick="editBL(${r.id})">${t("common.edit")}</button></td>
      <td><button class="btn btn-danger" style="padding:4px 10px;font-size:12px;" onclick="deleteBL(${r.id})">${t("blacklists.remove")}</button></td>
    </tr>`).join("");
}

async function toggleBL(id) {
  try { await api(`/api/blacklists/${id}/toggle`, { method: "POST" }); loadBlacklists(); }
  catch (e) { toast(e.message, "error"); }
}
async function deleteBL(id) {
  if (!confirm(t("blacklists.confirmRemove"))) return;
  try { await api(`/api/blacklists/${id}`, { method: "DELETE" }); loadBlacklists(); }
  catch (e) { toast(e.message, "error"); }
}

function openBLModal() {
  editingBLId = null;
  document.getElementById("bl-modal-title").textContent = t("blacklists.modalTitleNew");
  document.getElementById("bl-name").value = "";
  document.getElementById("bl-zone").value = "";
  document.getElementById("bl-type").value = "ipv4";
  document.getElementById("bl-severity").value = "medium";
  document.getElementById("bl-qps").value = "5";
  document.getElementById("bl-requires-key").value = "false";
  document.getElementById("bl-key").value = "";
  document.getElementById("bl-key").placeholder = t("blacklists.keyPlaceholderNew");
  document.getElementById("bl-delist-url").value = "";
  document.getElementById("bl-lookup-url").value = "";
  document.getElementById("bl-modal").style.display = "flex";
}

function editBL(id) {
  const r = blCache.find(b => b.id === id);
  if (!r) return;
  editingBLId = id;
  document.getElementById("bl-modal-title").textContent = t("blacklists.modalTitleEdit", { name: r.name });
  document.getElementById("bl-name").value = r.name;
  document.getElementById("bl-zone").value = r.zone;
  document.getElementById("bl-type").value = r.type;
  document.getElementById("bl-severity").value = r.default_severity;
  document.getElementById("bl-qps").value = r.rate_limit_qps;
  document.getElementById("bl-requires-key").value = r.requires_key ? "true" : "false";
  document.getElementById("bl-key").value = "";
  document.getElementById("bl-key").placeholder = t("blacklists.keyPlaceholderEdit");
  document.getElementById("bl-delist-url").value = r.delist_url || "";
  document.getElementById("bl-lookup-url").value = r.lookup_url || "";
  document.getElementById("bl-modal").style.display = "flex";
}

function closeBLModal() { document.getElementById("bl-modal").style.display = "none"; }

async function submitBL() {
  const name = document.getElementById("bl-name").value.trim();
  const zone = document.getElementById("bl-zone").value.trim();
  if (!name || !zone) { toast(t("blacklists.errNameZone"), "error"); return; }
  const keyInput = document.getElementById("bl-key").value;
  const body = {
    name, zone,
    type: document.getElementById("bl-type").value,
    default_severity: document.getElementById("bl-severity").value,
    rate_limit_qps: parseFloat(document.getElementById("bl-qps").value) || 5,
    requires_key: document.getElementById("bl-requires-key").value === "true",
    // Em edição, campo vazio significa "não alterar a chave atual"; em
    // criação, campo vazio significa "sem chave".
    api_key: keyInput || null,
    delist_url: document.getElementById("bl-delist-url").value || null,
    lookup_url: document.getElementById("bl-lookup-url").value || null,
  };
  try {
    if (editingBLId) {
      await api(`/api/blacklists/${editingBLId}`, { method: "PUT", body: JSON.stringify(body) });
      toast(t("blacklists.updated"), "success");
    } else {
      await api("/api/blacklists", { method: "POST", body: JSON.stringify(body) });
      toast(t("blacklists.created"), "success");
    }
    closeBLModal();
    loadBlacklists();
  } catch (e) { toast(e.message, "error"); }
}
requireAuth().then(loadBlacklists);
