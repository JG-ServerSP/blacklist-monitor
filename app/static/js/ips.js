let clientsCache = [];
let groupsCache = [];
let blocksCache = {}; // block_id -> IPBlockOut

let currentPage = 1;
let pageSize = 20;
let totalCount = 0;
let currentPageIds = [];
const selectedIds = new Set();

let lastRows = []; // last page of MonitoredIPOut fetched, before grouping
const expandedBlocks = new Set();
const blockChildrenCache = {}; // block_id -> full array of MonitoredIPOut in that block
const blockPageState = {}; // block_id -> { page, pageSize } for the expanded-block view

async function loadFilters() {
  const [clients, groups, blocks] = await Promise.all([api("/api/clients"), api("/api/groups"), api("/api/ips/blocks")]);
  clientsCache = clients;
  groupsCache = groups;
  blocksCache = {};
  blocks.forEach(b => { blocksCache[b.id] = b; });
  const clientSel = document.getElementById("import-client");
  const groupSel = document.getElementById("import-group");
  clientSel.innerHTML = '<option value="">—</option>' + clientsCache.map(c => `<option value="${c.id}">${c.name}</option>`).join("");
  groupSel.innerHTML = '<option value="">—</option>' + groupsCache.map(g => `<option value="${g.id}">${g.name}</option>`).join("");

  const editClientSel = document.getElementById("edit-ip-client");
  const editGroupSel = document.getElementById("edit-ip-group");
  const clientOptions = `<option value="">${t("ips.noChangeOption")}</option><option value="none">${t("ips.noneOption")}</option>` +
    clientsCache.map(c => `<option value="${c.id}">${c.name}</option>`).join("");
  const groupOptions = `<option value="">${t("ips.noChangeOption")}</option><option value="none">${t("ips.noneOption")}</option>` +
    groupsCache.map(g => `<option value="${g.id}">${g.name}</option>`).join("");
  editClientSel.innerHTML = clientOptions;
  editGroupSel.innerHTML = groupOptions;
}

function clientName(id) { const c = clientsCache.find(c => c.id === id); return c ? c.name : "—"; }
function groupName(id) { const g = groupsCache.find(g => g.id === id); return g ? g.name : "—"; }

function intervalDisplay(r) {
  if (r.check_interval_minutes) return t("ips.intervalMin", { min: r.check_interval_minutes });
  const g = groupsCache.find(g => g.id === r.group_id);
  if (g && g.check_interval_minutes) return t("ips.intervalMinGroup", { min: g.check_interval_minutes });
  return t("ips.globalDefault");
}

function currentFilterParams() {
  const q = document.getElementById("filter-q").value;
  const status = document.getElementById("filter-status").value;
  const params = new URLSearchParams();
  if (q) params.set("q", q);
  if (status) params.set("status_filter", status);
  return params;
}

function applyFilters() {
  currentPage = 1;
  loadIPs();
}

function changePageSize() {
  pageSize = parseInt(document.getElementById("filter-page-size").value, 10) || 20;
  currentPage = 1;
  loadIPs();
}

function prevPage() {
  if (currentPage > 1) { currentPage--; loadIPs(); }
}

function nextPage() {
  const maxPage = Math.max(1, Math.ceil(totalCount / pageSize));
  if (currentPage < maxPage) { currentPage++; loadIPs(); }
}

async function loadIPs() {
  const params = currentFilterParams();
  params.set("limit", pageSize);
  params.set("offset", (currentPage - 1) * pageSize);

  const token = Auth.getToken();
  const resp = await fetch("/api/ips?" + params.toString(), {
    headers: token ? { Authorization: "Bearer " + token } : {},
  });
  if (!resp.ok) { toast(t("ips.loadError"), "error"); return; }
  const rows = await resp.json();
  totalCount = parseInt(resp.headers.get("X-Total-Count") || rows.length, 10);

  selectedIds.clear();
  currentPageIds = rows.map(r => r.id);
  lastRows = rows;

  // Any mutation (edit/delete/import/check) reloads via loadIPs(), so the
  // cache must be invalidated or expanded blocks would keep showing stale
  // children. Eagerly refetch open blocks; a collapsed one just falls back
  // to whatever subset of it appears in `rows` until it's expanded again.
  Object.keys(blockChildrenCache).forEach(id => delete blockChildrenCache[id]);
  await Promise.all([...expandedBlocks].map(async (blockId) => {
    try { blockChildrenCache[blockId] = await api(`/api/ips?block_id=${blockId}&limit=2000`); }
    catch (e) { /* leave uncached; renderTable falls back to the page subset */ }
  }));

  document.getElementById("ips-empty").style.display = rows.length ? "none" : "block";
  renderTable();

  document.getElementById("select-all").checked = false;
  document.getElementById("select-all").indeterminate = false;
  updateBulkButtons();
  updatePaginationControls();
}

// Groups the current page's rows: IPs sharing a block_id (CIDR/range import)
// collapse under one row, in the order their block first appears.
function groupForRender(rows) {
  const groups = [];
  const byBlock = new Map();
  for (const r of rows) {
    if (r.block_id && blocksCache[r.block_id]) {
      let g = byBlock.get(r.block_id);
      if (!g) {
        g = { type: "block", block: blocksCache[r.block_id], children: [] };
        byBlock.set(r.block_id, g);
        groups.push(g);
      }
      g.children.push(r);
    } else {
      groups.push({ type: "ip", row: r });
    }
  }
  return groups;
}

function ipRowHtml(r, indented) {
  return `
    <tr>
      <td><input type="checkbox" class="row-check" ${selectedIds.has(r.id) ? "checked" : ""} onchange="toggleRowSelect(${r.id}, this.checked)"></td>
      <td${indented ? ' style="padding-left:28px;"' : ""}>${r.ip}</td>
      <td>${clientName(r.client_id)}</td>
      <td>${groupName(r.group_id)}</td>
      <td><span class="badge-sev badge-${STATUS_CLASS[r.current_status]}">${statusLabel(r.current_status)}</span></td>
      <td>${r.ping_status ? pingLabel(r.ping_status) : t("ping.unknown")}</td>
      <td style="white-space:nowrap;font-size:12px;color:${r.check_interval_minutes ? "var(--text)" : "var(--text-muted)"};">${intervalDisplay(r)}</td>
      <td>${fmtDate(r.last_checked_at)}</td>
      <td style="white-space:nowrap;">
        <button class="btn btn-outline" style="padding:4px 10px;font-size:12px;" onclick="forceCheck(${r.id})">${t("ips.checkNow")}</button>
        <button class="btn btn-outline" style="padding:4px 10px;font-size:12px;" onclick="editIP(${r.id})">${t("common.edit")}</button>
        <button class="btn btn-danger" style="padding:4px 10px;font-size:12px;" onclick="deleteIP(${r.id})">${t("ips.remove")}</button>
      </td>
    </tr>`;
}

function blockRowHtml(g) {
  const block = g.block;
  const expanded = expandedBlocks.has(block.id);
  const known = blockChildrenCache[block.id];
  const displayCount = known ? known.length : (block.ip_count ?? g.children.length);
  const memberIds = (known || g.children).map(c => c.id);
  const allChecked = memberIds.length > 0 && memberIds.every(id => selectedIds.has(id));
  return `
    <tr class="block-row" style="background:var(--bg);">
      <td><input type="checkbox" id="block-check-${block.id}" ${allChecked ? "checked" : ""} onchange="toggleBlockSelect(${block.id}, this.checked)"></td>
      <td colspan="8">
        <button class="btn btn-outline" style="padding:2px 10px;font-size:12px;margin-right:8px;" onclick="toggleBlockExpand(${block.id})" title="${expanded ? t("ips.collapseBlock") : t("ips.expandBlock")}">${expanded ? "−" : "+"}</button>
        <strong>${block.cidr}</strong>
        <span style="color:var(--text-muted);font-size:12px;margin-left:8px;">${t("ips.cidrCount", { count: displayCount })}</span>
      </td>
    </tr>`;
}

function blockPaginationRowHtml(blockId, total, state) {
  const maxPage = Math.max(1, Math.ceil(total / state.pageSize));
  const start = total === 0 ? 0 : (state.page - 1) * state.pageSize + 1;
  const end = Math.min(state.page * state.pageSize, total);
  return `
    <tr>
      <td></td>
      <td colspan="8">
        <div style="display:flex;align-items:center;justify-content:space-between;gap:8px;flex-wrap:wrap;padding:4px 0 4px 28px;">
          <span style="color:var(--text-muted);font-size:12px;">${t("ips.paginationSummary", { start, end, total, page: state.page, maxPage })}</span>
          <div style="display:flex;gap:8px;align-items:center;">
            <label style="color:var(--text-muted);font-size:12px;">${t("ips.perPage")}</label>
            <select onchange="changeBlockPageSize(${blockId}, this.value)" style="background:var(--bg);border:1px solid var(--card-border);border-radius:6px;padding:2px 6px;font-size:12px;color:var(--text);">
              ${[20, 50, 100, 200].map(n => `<option value="${n}" ${state.pageSize === n ? "selected" : ""}>${n}</option>`).join("")}
            </select>
            <button class="btn btn-outline" style="padding:2px 8px;font-size:12px;" onclick="blockPrevPage(${blockId})" ${state.page <= 1 ? "disabled" : ""}>‹</button>
            <button class="btn btn-outline" style="padding:2px 8px;font-size:12px;" onclick="blockNextPage(${blockId})" ${state.page >= maxPage ? "disabled" : ""}>›</button>
          </div>
        </div>
      </td>
    </tr>`;
}

function renderTable() {
  const groups = groupForRender(lastRows);
  const tbody = document.getElementById("ips-tbody");
  tbody.innerHTML = groups.map(g => {
    if (g.type === "ip") return ipRowHtml(g.row, false);
    const rows = [blockRowHtml(g)];
    if (expandedBlocks.has(g.block.id)) {
      const all = blockChildrenCache[g.block.id] || g.children;
      const state = blockPageState[g.block.id] || (blockPageState[g.block.id] = { page: 1, pageSize: 20 });
      const maxPage = Math.max(1, Math.ceil(all.length / state.pageSize));
      if (state.page > maxPage) state.page = maxPage;
      const start = (state.page - 1) * state.pageSize;
      const pageItems = all.slice(start, start + state.pageSize);
      rows.push(pageItems.map(c => ipRowHtml(c, true)).join(""));
      rows.push(blockPaginationRowHtml(g.block.id, all.length, state));
    }
    return rows.join("");
  }).join("");
  // checkbox.indeterminate can only be set as a DOM property, not via markup.
  groups.filter(g => g.type === "block").forEach(g => {
    const known = blockChildrenCache[g.block.id];
    const memberIds = (known || g.children).map(c => c.id);
    const anyChecked = memberIds.some(id => selectedIds.has(id));
    const allChecked = memberIds.length > 0 && memberIds.every(id => selectedIds.has(id));
    const el = document.getElementById(`block-check-${g.block.id}`);
    if (el) el.indeterminate = anyChecked && !allChecked;
  });
}

async function toggleBlockExpand(blockId) {
  if (expandedBlocks.has(blockId)) {
    expandedBlocks.delete(blockId);
    renderTable();
    return;
  }
  expandedBlocks.add(blockId);
  // Reset to page 1 on (re)open, but keep the page size sticky across
  // collapse/expand so the user's choice isn't lost.
  const prevSize = blockPageState[blockId] ? blockPageState[blockId].pageSize : 20;
  blockPageState[blockId] = { page: 1, pageSize: prevSize };
  if (!blockChildrenCache[blockId]) {
    try {
      blockChildrenCache[blockId] = await api(`/api/ips?block_id=${blockId}&limit=2000`);
    } catch (e) {
      toast(e.message, "error");
      blockChildrenCache[blockId] = [];
    }
  }
  renderTable();
}

function changeBlockPageSize(blockId, size) {
  const state = blockPageState[blockId] || (blockPageState[blockId] = { page: 1, pageSize: 20 });
  state.pageSize = parseInt(size, 10) || 20;
  state.page = 1;
  renderTable();
}

function blockPrevPage(blockId) {
  const state = blockPageState[blockId];
  if (!state || state.page <= 1) return;
  state.page--;
  renderTable();
}

function blockNextPage(blockId) {
  const state = blockPageState[blockId];
  const all = blockChildrenCache[blockId];
  if (!state || !all) return;
  const maxPage = Math.max(1, Math.ceil(all.length / state.pageSize));
  if (state.page >= maxPage) return;
  state.page++;
  renderTable();
}

async function toggleBlockSelect(blockId, checked) {
  if (!blockChildrenCache[blockId]) {
    try {
      blockChildrenCache[blockId] = await api(`/api/ips?block_id=${blockId}&limit=2000`);
    } catch (e) { toast(e.message, "error"); return; }
  }
  blockChildrenCache[blockId].forEach(c => { if (checked) selectedIds.add(c.id); else selectedIds.delete(c.id); });
  renderTable();
  updateBulkButtons();
}

function updatePaginationControls() {
  const maxPage = Math.max(1, Math.ceil(totalCount / pageSize));
  const start = totalCount === 0 ? 0 : (currentPage - 1) * pageSize + 1;
  const end = Math.min(currentPage * pageSize, totalCount);
  document.getElementById("pagination-summary").textContent =
    totalCount === 0 ? "" : t("ips.paginationSummary", { start, end, total: totalCount, page: currentPage, maxPage });
  document.getElementById("btn-prev-page").disabled = currentPage <= 1;
  document.getElementById("btn-next-page").disabled = currentPage >= maxPage;
}

function toggleRowSelect(id, checked) {
  if (checked) selectedIds.add(id); else selectedIds.delete(id);
  renderTable();
  updateBulkButtons();
}

function toggleSelectAll(checked) {
  selectedIds.clear();
  if (checked) currentPageIds.forEach(id => selectedIds.add(id));
  renderTable();
  updateBulkButtons();
}

function updateBulkButtons() {
  const has = selectedIds.size > 0;
  document.getElementById("btn-check-selected").disabled = !has;
  document.getElementById("btn-edit-selected").disabled = !has;
  document.getElementById("btn-delete-selected").disabled = !has;
  const selectAll = document.getElementById("select-all");
  if (currentPageIds.length > 0 && selectedIds.size === currentPageIds.length) {
    selectAll.checked = true; selectAll.indeterminate = false;
  } else if (selectedIds.size > 0) {
    selectAll.checked = false; selectAll.indeterminate = true;
  } else {
    selectAll.checked = false; selectAll.indeterminate = false;
  }
}

async function checkSelected() {
  if (selectedIds.size === 0) return;
  toast(t("ips.checkingSelected", { count: selectedIds.size }));
  try {
    await api("/api/ips/bulk-check", { method: "POST", body: JSON.stringify({ ids: [...selectedIds] }) });
    toast(t("ips.checkComplete"), "success");
    loadIPs();
  } catch (e) { toast(e.message, "error"); }
}

async function checkAllFiltered() {
  if (!confirm(t("ips.confirmCheckAll", { count: totalCount }))) return;
  toast(t("ips.checkingAllFiltered"));
  try {
    const result = await api("/api/ips/check-all?" + currentFilterParams().toString(), { method: "POST" });
    toast(t("ips.checkedCount", { count: result.checked }), "success");
    loadIPs();
  } catch (e) { toast(e.message, "error"); }
}

async function deleteSelected() {
  if (selectedIds.size === 0) return;
  if (!confirm(t("ips.confirmDeleteSelected", { count: selectedIds.size }))) return;
  try {
    await api("/api/ips/bulk-delete", { method: "POST", body: JSON.stringify({ ids: [...selectedIds] }) });
    toast(t("ips.removedSelected"), "success");
    loadIPs();
  } catch (e) { toast(e.message, "error"); }
}

let editingIPIds = [];

function openEditIPModal(ids) {
  editingIPIds = ids;
  document.getElementById("edit-ip-title").textContent = ids.length === 1 ? t("ips.editTitleSingle") : t("ips.editTitleMultiple", { count: ids.length });
  document.getElementById("edit-ip-client").value = "";
  document.getElementById("edit-ip-group").value = "";
  document.getElementById("edit-ip-dc").value = "";
  document.getElementById("edit-ip-tags").value = "";
  document.getElementById("edit-ip-enabled").value = "";
  document.getElementById("edit-ip-interval").value = "";
  document.getElementById("edit-ip-interval").disabled = false;
  document.getElementById("edit-ip-interval-clear").checked = false;
  document.getElementById("edit-ip-modal").style.display = "flex";
}

function editIP(id) { openEditIPModal([id]); }

function editSelected() {
  if (selectedIds.size === 0) return;
  openEditIPModal([...selectedIds]);
}

function closeEditIPModal() { document.getElementById("edit-ip-modal").style.display = "none"; }

async function submitEditIP() {
  const body = { ids: editingIPIds };
  const clientVal = document.getElementById("edit-ip-client").value;
  if (clientVal !== "") body.client_id = clientVal === "none" ? null : parseInt(clientVal, 10);
  const groupVal = document.getElementById("edit-ip-group").value;
  if (groupVal !== "") body.group_id = groupVal === "none" ? null : parseInt(groupVal, 10);
  const dc = document.getElementById("edit-ip-dc").value;
  if (dc !== "") body.datacenter = dc;
  const tags = document.getElementById("edit-ip-tags").value;
  if (tags !== "") body.tags = tags;
  const enabledVal = document.getElementById("edit-ip-enabled").value;
  if (enabledVal !== "") body.enabled = enabledVal === "true";
  const intervalClear = document.getElementById("edit-ip-interval-clear").checked;
  const intervalVal = document.getElementById("edit-ip-interval").value;
  if (intervalClear) {
    body.check_interval_minutes = null;
  } else if (intervalVal !== "") {
    body.check_interval_minutes = parseInt(intervalVal, 10);
  }

  if (Object.keys(body).length <= 1) { toast(t("ips.noChangesInformed"), "error"); return; }

  try {
    const result = await api("/api/ips/bulk-update", { method: "POST", body: JSON.stringify(body) });
    toast(t("ips.updatedCount", { count: result.updated }), "success");
    closeEditIPModal();
    loadIPs();
  } catch (e) { toast(e.message, "error"); }
}

async function forceCheck(id) {
  toast(t("ips.checkingIp"));
  try {
    await api(`/api/ips/${id}/check`, { method: "POST" });
    toast(t("ips.checkComplete"), "success");
    loadIPs();
  } catch (e) { toast(e.message, "error"); }
}

async function deleteIP(id) {
  if (!confirm(t("ips.confirmDeleteOne"))) return;
  try {
    await api(`/api/ips/${id}`, { method: "DELETE" });
    loadIPs();
  } catch (e) { toast(e.message, "error"); }
}

function openImportModal() { document.getElementById("import-modal").style.display = "flex"; }
function closeImportModal() { document.getElementById("import-modal").style.display = "none"; }

async function submitImport() {
  const entry = document.getElementById("import-entry").value.trim();
  if (!entry) { toast(t("ips.enterEntry"), "error"); return; }
  const body = {
    entry,
    client_id: document.getElementById("import-client").value || null,
    group_id: document.getElementById("import-group").value || null,
    datacenter: document.getElementById("import-dc").value || null,
    tags: document.getElementById("import-tags").value || null,
    check_interval_minutes: parseInt(document.getElementById("import-interval").value) || null,
  };
  try {
    const created = await api("/api/ips/import", { method: "POST", body: JSON.stringify(body) });
    toast(t("ips.importedCount", { count: created.length }), "success");
    closeImportModal();
    await loadFilters(); // entry may have created a new CIDR/range block
    loadIPs();
  } catch (e) { toast(e.message, "error"); }
}

async function uploadCSV(file) {
  if (!file) return;
  const formData = new FormData();
  formData.append("file", file);
  try {
    const token = Auth.getToken();
    const resp = await fetch("/api/ips/import-csv", {
      method: "POST",
      headers: token ? { Authorization: "Bearer " + token } : {},
      body: formData,
    });
    const result = await resp.json();
    if (!resp.ok) throw new Error(result.detail || t("ips.importFailed"));
    toast(t("ips.importedCsvCount", { count: result.created }), "success");
    if (result.errors && result.errors.length) toast(result.errors.join(" | "), "error");
    await loadFilters(); // rows may have created new CIDR/range blocks
    loadIPs();
  } catch (e) { toast(e.message, "error"); }
}

requireAuth().then(() => loadFilters().then(loadIPs));
