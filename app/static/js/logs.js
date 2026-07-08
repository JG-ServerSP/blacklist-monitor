const LOG_LEVEL_CLASS = { DEBUG: "low", INFO: "low", WARNING: "medium", ERROR: "high", CRITICAL: "critical" };

function escapeHtml(s) {
  const div = document.createElement("div");
  div.textContent = s == null ? "" : s;
  return div.innerHTML;
}

function levelBadge(level) {
  if (!level) return "—";
  const cls = LOG_LEVEL_CLASS[level] || "medium";
  return `<span class="badge-sev badge-${cls}">${level}</span>`;
}

async function loadLogs() {
  const level = document.getElementById("log-filter-level").value;
  const q = document.getElementById("log-filter-q").value;
  const params = new URLSearchParams();
  if (level) params.set("level", level);
  if (q) params.set("q", q);
  params.set("limit", 300);
  let rows;
  try {
    rows = await api("/api/logs?" + params.toString());
  } catch (e) { toast(e.message, "error"); return; }
  const tbody = document.getElementById("logs-tbody");
  document.getElementById("logs-empty").style.display = rows.length ? "none" : "block";
  tbody.innerHTML = rows.map(r => `
    <tr>
      <td style="white-space:nowrap;color:var(--text-muted);font-size:12px;">${escapeHtml(r.timestamp) || "—"}</td>
      <td>${levelBadge(r.level)}</td>
      <td style="font-family:monospace;font-size:12px;">${escapeHtml(r.logger) || "—"}</td>
      <td style="font-family:monospace;font-size:12px;white-space:pre-wrap;word-break:break-word;">${escapeHtml(r.message)}</td>
    </tr>`).join("");
}

requireAuth().then(loadLogs);
