let domainClients = [];

async function loadDomainClients() {
  domainClients = await api("/api/clients");
  document.getElementById("domain-client").innerHTML = `<option value="">${t("domains.none")}</option>` +
    domainClients.map(c => `<option value="${c.id}">${c.name}</option>`).join("");
}
function domainClientName(id) { const c = domainClients.find(c => c.id === id); return c ? c.name : t("domains.none"); }

async function loadDomains() {
  const rows = await api("/api/domains");
  const tbody = document.getElementById("domains-tbody");
  document.getElementById("domains-empty").style.display = rows.length ? "none" : "block";
  tbody.innerHTML = rows.map(r => `
    <tr>
      <td>${r.domain}</td>
      <td>${domainClientName(r.client_id)}</td>
      <td><span class="badge-sev badge-${STATUS_CLASS[r.current_status]}">${statusLabel(r.current_status)}</span></td>
      <td>${fmtDate(r.last_checked_at)}</td>
      <td style="white-space:nowrap;">
        <button class="btn btn-outline" style="padding:4px 10px;font-size:12px;" onclick="checkDomain(${r.id})">${t("domains.checkNow")}</button>
        <button class="btn btn-danger" style="padding:4px 10px;font-size:12px;" onclick="deleteDomain(${r.id})">${t("domains.remove")}</button>
      </td>
    </tr>`).join("");
}

async function checkDomain(id) {
  try { await api(`/api/domains/${id}/check`, { method: "POST" }); toast(t("domains.checkDone"), "success"); loadDomains(); }
  catch (e) { toast(e.message, "error"); }
}
async function deleteDomain(id) {
  if (!confirm(t("domains.confirmDelete"))) return;
  try { await api(`/api/domains/${id}`, { method: "DELETE" }); loadDomains(); }
  catch (e) { toast(e.message, "error"); }
}
function openDomainModal() { document.getElementById("domain-modal").style.display = "flex"; }
function closeDomainModal() { document.getElementById("domain-modal").style.display = "none"; }
async function submitDomain() {
  const domain = document.getElementById("domain-input").value.trim();
  if (!domain) { toast(t("domains.enterDomain"), "error"); return; }
  try {
    await api("/api/domains", { method: "POST", body: JSON.stringify({
      domain, client_id: document.getElementById("domain-client").value || null,
    })});
    toast(t("domains.added"), "success");
    closeDomainModal();
    loadDomains();
  } catch (e) { toast(e.message, "error"); }
}

requireAuth().then(() => loadDomainClients().then(loadDomains));
