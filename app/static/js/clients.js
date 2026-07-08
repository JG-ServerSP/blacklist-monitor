let clientsCache = [];
let editingClientId = null;

async function loadClients() {
  clientsCache = await api("/api/clients");
  const tbody = document.getElementById("clients-tbody");
  document.getElementById("clients-empty").style.display = clientsCache.length ? "none" : "block";
  tbody.innerHTML = clientsCache.map(r => `
    <tr>
      <td>${r.name}</td>
      <td>${r.contact_email || t("clients.none")}</td>
      <td>${fmtDateOnly(r.created_at)}</td>
      <td style="white-space:nowrap;"><button class="btn btn-outline" style="padding:4px 10px;font-size:12px;" onclick="editClient(${r.id})">${t("clients.edit")}</button></td>
      <td><button class="btn btn-danger" style="padding:4px 10px;font-size:12px;" onclick="deleteClient(${r.id})">${t("clients.remove")}</button></td>
    </tr>`).join("");
}

function openClientModal() {
  editingClientId = null;
  document.getElementById("client-modal-title").textContent = t("clients.modalNewTitle");
  document.getElementById("client-name").value = "";
  document.getElementById("client-email").value = "";
  document.getElementById("client-modal").style.display = "flex";
}

function editClient(id) {
  const r = clientsCache.find(c => c.id === id);
  if (!r) return;
  editingClientId = id;
  document.getElementById("client-modal-title").textContent = t("clients.modalEditTitle", { name: r.name });
  document.getElementById("client-name").value = r.name;
  document.getElementById("client-email").value = r.contact_email || "";
  document.getElementById("client-modal").style.display = "flex";
}

function closeClientModal() { document.getElementById("client-modal").style.display = "none"; }

async function submitClient() {
  const name = document.getElementById("client-name").value.trim();
  if (!name) { toast(t("clients.enterName"), "error"); return; }
  const body = { name, contact_email: document.getElementById("client-email").value || null };
  try {
    if (editingClientId) {
      await api(`/api/clients/${editingClientId}`, { method: "PUT", body: JSON.stringify(body) });
      toast(t("clients.updated"), "success");
    } else {
      await api("/api/clients", { method: "POST", body: JSON.stringify(body) });
      toast(t("clients.created"), "success");
    }
    closeClientModal();
    loadClients();
  } catch (e) { toast(e.message, "error"); }
}
async function deleteClient(id) {
  if (!confirm(t("clients.confirmDelete"))) return;
  try { await api(`/api/clients/${id}`, { method: "DELETE" }); loadClients(); }
  catch (e) { toast(e.message, "error"); }
}
requireAuth().then(loadClients);
