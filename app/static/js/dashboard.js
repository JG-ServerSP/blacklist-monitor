const KPI_ICONS = {
  monitored: { icon: "🖥️", bg: "rgba(59,130,246,.15)", color: "#3b82f6" },
  clean: { icon: "🛡️", bg: "rgba(34,197,94,.15)", color: "#22c55e" },
  listed: { icon: "⚠️", bg: "rgba(234,179,8,.15)", color: "#eab308" },
  critical: { icon: "⛔", bg: "rgba(239,68,68,.15)", color: "#ef4444" },
  domains: { icon: "🌐", bg: "rgba(139,92,246,.15)", color: "#8b5cf6" },
};

let currentSeverityFilter = "all";
let allListings = [];
let donutChart, timelineChart;

function renderKPIs(k) {
  const grid = document.getElementById("kpi-grid");
  const cards = [
    { key: "monitored", label: t("dashboard.kpiMonitoredIps"), value: k.monitored_ips, delta: null },
    { key: "clean", label: t("dashboard.kpiCleanIps"), value: `${k.clean_ips} (${k.clean_pct}%)`, delta: null },
    { key: "listed", label: t("dashboard.kpiListedIps"), value: `${k.listed_ips} (${k.listed_pct}%)`, delta: null },
    { key: "critical", label: t("dashboard.kpiCriticalListings"), value: `${k.critical_listings} (${k.critical_pct}%)`, delta: null },
    { key: "domains", label: t("dashboard.kpiMonitoredDomains"), value: k.monitored_domains, delta: null },
  ];
  grid.innerHTML = cards.map(c => {
    const ic = KPI_ICONS[c.key];
    return `
      <div class="card kpi-card">
        <div class="label">${c.label}
          <span class="kpi-icon" style="background:${ic.bg};color:${ic.color};">${ic.icon}</span>
        </div>
        <div class="value">${c.value}</div>
      </div>`;
  }).join("");
}

function renderTabs(severityBreakdown) {
  const total = ["critical", "high", "medium", "low"].reduce((a, k) => a + (severityBreakdown[k] || 0), 0);
  document.getElementById("count-all").textContent = total;
  document.getElementById("count-critical").textContent = severityBreakdown.critical || 0;
  document.getElementById("count-high").textContent = severityBreakdown.high || 0;
  document.getElementById("count-medium").textContent = severityBreakdown.medium || 0;
  document.getElementById("count-low").textContent = severityBreakdown.low || 0;
}

function renderListingsTable() {
  const tbody = document.getElementById("listings-tbody");
  const filtered = currentSeverityFilter === "all" ? allListings : allListings.filter(l => l.severity === currentSeverityFilter);
  document.getElementById("listings-empty").style.display = filtered.length ? "none" : "block";
  tbody.innerHTML = filtered.map(l => {
    const blBadges = l.blacklists.slice(0, 2).map(b => `<span class="pill">${b.name}</span>`).join("");
    const extra = l.blacklists.length > 2 ? `<span class="pill">+${l.blacklists.length - 2}</span>` : "";
    return `
      <tr class="clickable" data-ip-id="${l.ip_id}">
        <td><span class="dot-sev dot-${l.severity}"></span>${l.ip}</td>
        <td>${l.client || "—"}<br><span style="color:var(--text-muted);font-size:12px;">${l.service || ""}</span></td>
        <td>${blBadges}${extra}</td>
        <td>${severityBadge(l.severity)}</td>
        <td>${fmtDate(l.last_detection)}</td>
        <td><button class="btn btn-outline" style="padding:4px 10px;font-size:12px;">${t("dashboard.viewButton")}</button></td>
      </tr>`;
  }).join("");

  tbody.querySelectorAll("tr[data-ip-id]").forEach(tr => {
    tr.addEventListener("click", () => loadIPDetail(tr.dataset.ipId));
  });
}

async function loadListings() {
  allListings = await api("/api/dashboard/recent-listings");
  renderListingsTable();
}

function renderDonut(breakdown) {
  const ctx = document.getElementById("ips-overview-chart");
  const labels = [
    t("dashboard.kpiCleanIps"),
    t("dashboard.sevLow"), t("dashboard.sevMedium"), t("dashboard.sevHigh"), t("dashboard.sevCritical"),
  ];
  const values = [
    breakdown.clean_ips || 0,
    breakdown.low || 0, breakdown.medium || 0, breakdown.high || 0, breakdown.critical || 0,
  ];
  const colors = ["#22c55e", "#3b82f6", "#eab308", "#f97316", "#ef4444"];
  const totalIps = breakdown.total_ips || 0;

  if (donutChart) donutChart.destroy();
  donutChart = new Chart(ctx, {
    type: "doughnut",
    data: { labels, datasets: [{ data: values, backgroundColor: colors, borderWidth: 0 }] },
    options: {
      cutout: "70%",
      plugins: { legend: { display: false } },
    },
    plugins: [{
      id: "centerText",
      afterDraw(chart) {
        const { ctx, chartArea: { width, height, left, top } } = chart;
        ctx.save();
        ctx.textAlign = "center";
        ctx.fillStyle = "#e5e7eb";
        ctx.font = "700 22px Inter, sans-serif";
        ctx.fillText(totalIps, left + width / 2, top + height / 2 - 2);
        ctx.font = "12px Inter, sans-serif";
        ctx.fillStyle = "#9ca3af";
        ctx.fillText(t("dashboard.total"), left + width / 2, top + height / 2 + 16);
        ctx.restore();
      },
    }],
  });

  const legend = document.getElementById("ips-overview-legend");
  legend.innerHTML = labels.map((label, i) => {
    const pct = totalIps ? Math.round((values[i] / totalIps) * 1000) / 10 : 0;
    return `<div style="display:flex;align-items:center;justify-content:space-between;padding:4px 0;">
      <span><span class="dot-sev" style="background:${colors[i]}"></span>${label}</span>
      <span style="color:var(--text-muted);">${values[i]} (${pct}%)</span>
    </div>`;
  }).join("");
}

function renderTimeline(byDay) {
  const days = Object.keys(byDay).sort();
  const ctx = document.getElementById("timeline-chart");
  const series = [
    { key: "critical", label: t("dashboard.sevCritical"), color: "#ef4444" },
    { key: "high", label: t("dashboard.sevHigh"), color: "#f97316" },
    { key: "medium", label: t("dashboard.sevMedium"), color: "#eab308" },
    { key: "low", label: t("dashboard.sevLow"), color: "#22c55e" },
  ];
  if (timelineChart) timelineChart.destroy();
  timelineChart = new Chart(ctx, {
    type: "line",
    data: {
      labels: days.map(d => fmtDateOnly(d)),
      datasets: series.map(s => ({
        label: s.label,
        data: days.map(d => (byDay[d] && byDay[d][s.key]) || 0),
        borderColor: s.color,
        backgroundColor: s.color,
        tension: 0.35,
      })),
    },
    options: {
      scales: {
        x: { grid: { color: "#232b3d" }, ticks: { color: "#9ca3af" } },
        y: { grid: { color: "#232b3d" }, ticks: { color: "#9ca3af" }, beginAtZero: true },
      },
      plugins: { legend: { labels: { color: "#e5e7eb" } } },
    },
  });
}

async function loadIPDetail(ipId) {
  const detail = await api(`/api/dashboard/ip-detail/${ipId}`);
  const body = document.getElementById("ip-detail-body");
  if (!detail || !detail.ip) {
    body.innerHTML = `<div class="empty-state">${t("dashboard.ipNotFound")}</div>`;
    return;
  }
  const activeListings = detail.listings.filter(l => !l.removed_at);
  const worst = activeListings.length ? activeListings.reduce((a, b) =>
    SEVERITY_ORDER.indexOf(a.severity) < SEVERITY_ORDER.indexOf(b.severity) ? a : b) : null;

  body.innerHTML = `
    <div style="display:flex;align-items:center;gap:10px;margin-bottom:14px;">
      <span class="dot-sev dot-${worst ? worst.severity : 'low'}" style="width:10px;height:10px;"></span>
      <span style="font-size:16px;font-weight:700;">${detail.ip}</span>
      ${worst ? severityBadge(worst.severity) : `<span class="badge-sev badge-low">${t("dashboard.clean")}</span>`}
    </div>
    <div style="font-size:13px;line-height:1.9;color:var(--text-muted);">
      <div><b style="color:var(--text);">${t("dashboard.client")}</b> ${detail.client || "—"}</div>
      <div><b style="color:var(--text);">${t("dashboard.service")}</b> ${detail.service || "—"}</div>
      <div><b style="color:var(--text);">${t("dashboard.group")}</b> ${detail.group || "—"}</div>
      <div><b style="color:var(--text);">${t("dashboard.asn")}</b> <span id="asn-live">${t("dashboard.runningDiagnostics")}</span></div>
      <div><b style="color:var(--text);">${t("dashboard.datacenter")}</b> ${detail.datacenter || "—"}</div>
      <div><b style="color:var(--text);">${t("dashboard.addedOn")}</b> ${fmtDate(detail.created_at)}</div>
    </div>
    <p class="section-title" style="margin-top:16px;">${t("dashboard.listingsSummary")}</p>
    <div style="font-size:13px;">
      ${activeListings.length ? activeListings.map(l => `
        <div style="display:flex;justify-content:space-between;padding:5px 0;">
          <span>${l.blacklist} ${severityBadge(l.severity)}</span>
          <span style="color:var(--text-muted);">${t("dashboard.since", { date: fmtDateOnly(l.detected_at) })}</span>
        </div>`).join("") : `<div style="color:var(--text-muted);">${t("dashboard.noActiveListingsSimple")}</div>`}
    </div>
    <div style="display:flex;gap:8px;margin-top:16px;flex-wrap:wrap;">
      <button class="btn btn-primary" onclick="loadDiagnostics('${ipId}')">${t("dashboard.viewDiagnostics")}</button>
      <button class="btn btn-secondary" onclick="requestDelistFor(${activeListings[0] ? activeListings[0].id : 0})">${t("dashboard.requestDelist")}</button>
    </div>
  `;
  loadDiagnostics(ipId, ipId);
  fetchAndRenderASNInline(detail.ip);
}

async function fetchAndRenderASNInline(ip) {
  const span = document.getElementById("asn-live");
  if (!span) return;
  try {
    const r = await api(`/api/diagnostics/asn-lookup?ip=${encodeURIComponent(ip)}`);
    span.textContent = r.asn
      ? `AS${r.asn} — ${r.holder || "?"}${r.country ? " (" + r.country + ")" : ""}`
      : t("dashboard.asnNotFound");
  } catch (e) {
    span.textContent = t("dashboard.asnNotFound");
  }
}

function renderManualIPDetail(ip, data) {
  const asn = data.asn || {};
  const listed = (data.checks || []).filter(c => c.listed);
  const worst = listed.length
    ? listed.reduce((a, b) => SEVERITY_ORDER.indexOf(a.severity) < SEVERITY_ORDER.indexOf(b.severity) ? a : b)
    : null;
  return `
    <div style="display:flex;align-items:center;gap:10px;margin-bottom:14px;">
      <span class="dot-sev dot-${worst ? worst.severity : 'low'}" style="width:10px;height:10px;"></span>
      <span style="font-size:16px;font-weight:700;">${ip}</span>
      ${worst ? severityBadge(worst.severity) : `<span class="badge-sev badge-low">${t("dashboard.clean")}</span>`}
    </div>
    <div style="font-size:13px;line-height:1.9;color:var(--text-muted);">
      <div><b style="color:var(--text);">${t("dashboard.asn")}</b> ${asn.asn ? `AS${asn.asn} — ${asn.holder || "?"}` : t("dashboard.asnNotFound")}</div>
      <div><b style="color:var(--text);">${t("dashboard.asnPrefix")}</b> ${asn.prefix || "—"}</div>
      <div><b style="color:var(--text);">${t("dashboard.asnCountry")}</b> ${asn.country || "—"}</div>
      <div><b style="color:var(--text);">${t("dashboard.asnRegistry")}</b> ${asn.registry || "—"}</div>
    </div>
    <p class="section-title" style="margin-top:16px;">${t("dashboard.listingsSummary")}</p>
    <div style="font-size:13px;">
      ${listed.length ? listed.map(c => `
        <div style="display:flex;justify-content:space-between;padding:5px 0;">
          <span>${c.blacklist} ${severityBadge(c.severity)}</span>
          <span style="color:var(--text-muted);">${c.sublist || ""}</span>
        </div>`).join("") : `<div style="color:var(--text-muted);">${t("dashboard.noActiveListingsSimple")}</div>`}
    </div>
  `;
}

async function lookupArbitraryIP() {
  const input = document.getElementById("ip-lookup-input");
  const ip = input.value.trim();
  const body = document.getElementById("ip-detail-body");
  if (!ip) return;
  body.innerHTML = `<div class="empty-state">${t("dashboard.runningDiagnostics")}</div>`;
  try {
    const data = await api(`/api/diagnostics/ip-lookup?ip=${encodeURIComponent(ip)}`);
    body.innerHTML = renderManualIPDetail(ip, data);
  } catch (e) {
    body.innerHTML = `<div class="empty-state">${t("dashboard.diagnosticError", { message: e.message })}</div>`;
  }
  loadDiagnosticsForIP(ip);
}

function diagStatusWord(key, res) {
  if (key === "port25") return res.ok ? t("dashboard.diagClosed") : t("dashboard.diagOpen");
  if (res.ok === true) return t("dashboard.diagOk");
  if (res.ok === false) return t("dashboard.diagMissing");
  return t("dashboard.diagNotApplicable");
}

async function runDiagnostics(url) {
  const body = document.getElementById("diagnostics-body");
  body.innerHTML = `<div class="empty-state">${t("dashboard.runningDiagnostics")}</div>`;
  try {
    const d = await api(url);
    const rows = [
      { key: "ptr", label: t("dashboard.diagPtr"), res: d.ptr },
      { key: "fcrdns", label: t("dashboard.diagFcrdns"), res: d.fcrdns },
      { key: "spf", label: t("dashboard.diagSpf"), res: d.spf },
      { key: "dkim", label: t("dashboard.diagDkim"), res: d.dkim },
      { key: "dmarc", label: t("dashboard.diagDmarc"), res: d.dmarc },
      { key: "port25", label: t("dashboard.diagPort25"), res: d.port25 },
    ];
    body.innerHTML = rows.map(r => {
      const cls = r.res.ok === true ? "diag-status-ok" : r.res.ok === false ? "diag-status-err" : "diag-status-warn";
      const icon = r.res.ok === true ? "✅" : r.res.ok === false ? "❌" : "⚠️";
      const word = diagStatusWord(r.key, r.res);
      return `
        <div class="diag-row" style="flex-direction:column;align-items:stretch;gap:3px;">
          <div style="display:flex;justify-content:space-between;align-items:center;">
            <span>${r.label}</span>
            <span class="${cls}">${icon} ${word}</span>
          </div>
          <div style="color:var(--text-muted);font-size:12px;word-break:break-all;">${r.res.detail || "—"}</div>
        </div>`;
    }).join("");
  } catch (e) {
    body.innerHTML = `<div class="empty-state">${t("dashboard.diagnosticError", { message: e.message })}</div>`;
  }
}

async function loadDiagnostics(ipId) {
  await runDiagnostics(`/api/diagnostics/${ipId}`);
}

async function loadDiagnosticsForIP(ip) {
  await runDiagnostics(`/api/diagnostics/by-ip?ip=${encodeURIComponent(ip)}`);
}

async function requestDelistFor(listingId) {
  if (!listingId) { toast(t("dashboard.noActiveListingForDelist"), "error"); return; }
  const user = Auth.getUser();
  try {
    await api(`/api/listings/${listingId}/delist-request`, {
      method: "POST",
      body: JSON.stringify({ requested_by: user ? user.email : "admin@seudominio.com" }),
    });
    toast(t("dashboard.delistRequested"), "success");
    loadActivity();
  } catch (e) { toast(e.message, "error"); }
}

async function loadActivity() {
  await renderActivityFeed("activity-feed", 12);
}

document.querySelectorAll("#severity-tabs .tab").forEach(tab => {
  tab.addEventListener("click", () => {
    document.querySelectorAll("#severity-tabs .tab").forEach(t => t.classList.remove("active"));
    tab.classList.add("active");
    currentSeverityFilter = tab.dataset.sev;
    renderListingsTable();
  });
});

async function initDashboard() {
  await requireAuth();
  const [kpis, breakdown, timeline] = await Promise.all([
    api("/api/dashboard/kpis"),
    api("/api/dashboard/severity-breakdown"),
    api("/api/dashboard/timeline?days=14"),
  ]);
  renderKPIs(kpis);
  renderTabs(breakdown);
  renderDonut(breakdown);
  renderTimeline(timeline);
  await loadListings();
  await loadActivity();
  if (allListings.length) loadIPDetail(allListings[0].ip_id);
}

initDashboard().catch(e => toast(t("dashboard.loadError", { message: e.message }), "error"));
