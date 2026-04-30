const state = {
  overview: null,
  decision: null,
  demand: null,
  inventory: null,
  procurement: null,
  substitutions: null,
  quality: null
};

const number = new Intl.NumberFormat("en-IN", { maximumFractionDigits: 0 });
const compact = new Intl.NumberFormat("en-IN", { notation: "compact", maximumFractionDigits: 1 });

function inr(value) {
  const n = Number(value || 0);
  if (Math.abs(n) >= 10000000) return `INR ${(n / 10000000).toFixed(2)} Cr`;
  if (Math.abs(n) >= 100000) return `INR ${(n / 100000).toFixed(2)} L`;
  return `INR ${number.format(n)}`;
}

function qty(value, unit = "") {
  const n = Number(value || 0);
  return `${compact.format(n)}${unit ? ` ${unit}` : ""}`;
}

function pct(value) {
  return `${Number(value || 0).toFixed(1)}%`;
}

async function api(path, options = {}) {
  const response = await fetch(path, options);
  if (!response.ok) throw new Error(`${path} failed with ${response.status}`);
  return response.json();
}

async function loadAll() {
  setRefreshState("Loading");
  const [overview, decision, demand, inventory, procurement, substitutions, quality] = await Promise.all([
    api("/api/overview"),
    api("/api/decision-dashboard"),
    api("/api/demand-planning"),
    api("/api/inventory-management"),
    api("/api/smart-procurement"),
    api("/api/substitutions"),
    api("/api/data-quality")
  ]);
  Object.assign(state, { overview, decision, demand, inventory, procurement, substitutions, quality });
  renderAll();
  setRefreshState("Ready");
}

function renderAll() {
  renderOverview();
  renderDemand();
  renderInventory();
  renderProcurement();
  renderSubstitutions();
  renderQuality();
}

function renderOverview() {
  const overview = state.overview;
  document.getElementById("analysisDate").textContent = `Analysis ${overview.analysisDate || "-"}`;
  document.getElementById("kpiGrid").innerHTML = [
    kpi("Remaining credit", inr(overview.kpis.remainingCreditInr), `${pct(overview.kpis.creditUtilizationPct)} utilized`),
    kpi("Approved PO value", inr(overview.kpis.approvedPoValueInr), `${overview.kpis.approvedPoValueInr > 0 ? "Credit-safe" : "No approvals"}`),
    kpi("Blocked need", inr(overview.kpis.blockedPoValueInr), `${overview.kpis.stockoutAlertCount} stockout alerts`),
    kpi("Data checks", String(overview.kpis.dataQualityIssueCount), "Warnings and notes")
  ].join("");

  const fill = document.getElementById("creditFill");
  fill.style.width = `${Math.min(100, overview.kpis.creditUtilizationPct)}%`;
  document.getElementById("creditBadge").textContent = overview.kpis.remainingCreditInr > 0 ? "Within cap" : "At cap";
  document.getElementById("creditUtilized").textContent = inr(overview.kpis.projectedCreditUtilizedInr);
  document.getElementById("creditAvailable").textContent = inr(overview.kpis.remainingCreditInr);

  document.getElementById("moduleList").innerHTML = overview.modules.map(module => `
    <div class="module-item">
      <strong>${escapeHtml(module.name)}</strong>
      <span>${escapeHtml(module.status)}</span>
      <span>${escapeHtml(module.metric)}</span>
    </div>
  `).join("");

  const actions = state.decision.immediateActions.slice(0, 8);
  document.getElementById("immediateActions").innerHTML = actions.map(row => `
    <tr>
      <td>${escapeHtml(row.material_name || row.material_id)}</td>
      <td>${escapeHtml(row.supplier_name || "-")}</td>
      <td>${qty(row.recommended_qty, row.unit)}</td>
      <td>${statusPill(row.credit_status)}</td>
    </tr>
  `).join("");

  document.getElementById("riskList").innerHTML = overview.topRisks.map(row => `
    <div class="risk-item">
      <strong>${escapeHtml(row.material_id)} · ${escapeHtml(row.material_name)}</strong>
      <span>${escapeHtml(row.first_stockout_date || "No date")} · ${row.days_to_stockout || "-"} day cover · shortage ${qty(row.projected_shortage_qty, row.unit)}</span>
    </div>
  `).join("");
}

function renderDemand() {
  drawBars("weekDemandChart", state.demand.weekTotals, "forecast_week", "seasonal_required_qty", row => `Week ${row.forecast_week}`);
  drawBars("materialDemandChart", state.demand.materialTotals.slice(0, 10), "material_id", "seasonal_required_qty", row => `${row.material_id} ${row.canonical_unit}`);
  renderBomRows();
}

function renderBomRows() {
  const needle = document.getElementById("bomSearch").value.trim().toLowerCase();
  const rows = state.demand.bomTraceSample.filter(row => {
    if (!needle) return true;
    return `${row.order_id} ${row.material_id} ${row.material_name}`.toLowerCase().includes(needle);
  });
  document.getElementById("bomTraceRows").innerHTML = rows.map(row => `
    <tr>
      <td>${escapeHtml(row.order_id)}</td>
      <td>${escapeHtml(row.material_id)} · ${escapeHtml(row.material_name)}</td>
      <td>${escapeHtml(row.box_size)}</td>
      <td>${Number(row.bom_qty_per_box || 0).toFixed(4)}</td>
      <td>${number.format(Number(row.order_quantity || 0))}</td>
      <td>${qty(row.seasonal_required_qty, row.canonical_unit)}</td>
    </tr>
  `).join("");
}

function renderInventory() {
  renderInventoryCards();
  document.getElementById("slowMovingRows").innerHTML = state.inventory.slowMoving.map(row => `
    <tr>
      <td>${escapeHtml(row.material_id)} · ${escapeHtml(row.name)}</td>
      <td>${qty(row.current_stock, row.unit)}</td>
      <td>${qty(row.forecast_demand_4w, row.unit)}</td>
      <td>${escapeHtml(row.watchlist_reason)}</td>
    </tr>
  `).join("");
}

function renderInventoryCards() {
  const needle = document.getElementById("inventorySearch").value.trim().toLowerCase();
  const rows = state.inventory.coverage.filter(row => {
    if (!needle) return true;
    return `${row.material_id} ${row.material_name}`.toLowerCase().includes(needle);
  });
  document.getElementById("inventoryCards").innerHTML = rows.map(row => {
    const critical = row.under_3_days_stock === true || row.under_3_days_stock === "True";
    return `
      <div class="inventory-card ${critical ? "critical" : "watch"}">
        <strong>${escapeHtml(row.material_id)} · ${escapeHtml(row.material_name)}</strong>
        <span>${escapeHtml(row.first_stockout_date || "No 42-day stockout")} · ${row.days_to_stockout || "-"} days</span>
        <span>Stock ${qty(row.current_stock, row.unit)} · 21D demand ${qty(row.total_demand_21d, row.unit)}</span>
        <span>${statusPill(critical ? "critical" : "watch")}</span>
      </div>
    `;
  }).join("");
}

function renderProcurement() {
  document.getElementById("approvedRows").innerHTML = state.procurement.approved.map(row => `
    <tr>
      <td>${escapeHtml(row.supplier_name)}</td>
      <td>${escapeHtml(row.material_id)} · ${escapeHtml(row.material_name)}</td>
      <td>${qty(row.recommended_qty, row.unit)}</td>
      <td>${inr(row.recommended_value_inr)}</td>
      <td>${inr(row.projected_credit_utilized_after_line_inr)}</td>
    </tr>
  `).join("");
  document.getElementById("blockedRows").innerHTML = state.procurement.blocked.map(row => `
    <tr>
      <td>${escapeHtml(row.material_id)} · ${escapeHtml(row.material_name)}</td>
      <td>${escapeHtml(row.supplier_name || "-")}</td>
      <td>${qty(row.recommended_qty, row.unit)}</td>
      <td>${inr(row.recommended_value_inr)}</td>
    </tr>
  `).join("");
}

function renderSubstitutions() {
  document.getElementById("substitutionCards").innerHTML = state.substitutions.allSubstitutions.map(row => `
    <div class="sub-card">
      <strong>${escapeHtml(row.source_material_id)} → ${escapeHtml(row.substitute_material_id)}</strong>
      <span>${escapeHtml(row.source_material_name || "")}</span>
      <span>${escapeHtml(row.substitute_material_name || "")}</span>
      <span>${escapeHtml(row.supplier_name || "-")} · ${qty(row.recommended_purchase_qty, row.unit)}</span>
      <span>${statusPill(row.credit_status || "review")}</span>
    </div>
  `).join("");
}

function renderQuality() {
  document.getElementById("qualityRows").innerHTML = state.quality.issues.map(row => `
    <tr>
      <td>${statusPill(row.severity)}</td>
      <td>${escapeHtml(row.file)}</td>
      <td>${escapeHtml(row.issue_type)}<br><span class="muted">${escapeHtml(row.detail)}</span></td>
    </tr>
  `).join("");
  document.getElementById("unitRows").innerHTML = state.quality.unitConversions.slice(0, 120).map(row => `
    <tr>
      <td>${escapeHtml(row.material_id)}</td>
      <td>${escapeHtml(row.original_unit)}</td>
      <td>${escapeHtml(row.target_unit)}</td>
      <td>${statusPill(row.conversion_confidence)}</td>
    </tr>
  `).join("");
}

function drawBars(targetId, rows, labelKey, valueKey, labelFn) {
  const max = Math.max(...rows.map(row => Number(row[valueKey] || 0)), 1);
  document.getElementById(targetId).innerHTML = rows.map(row => {
    const value = Number(row[valueKey] || 0);
    return `
      <div class="bar-row">
        <div class="bar-label">${escapeHtml(labelFn ? labelFn(row) : row[labelKey])}</div>
        <div class="bar-track"><div class="bar-fill" style="width:${Math.max(2, value / max * 100)}%"></div></div>
        <div class="bar-value">${compact.format(value)}</div>
      </div>
    `;
  }).join("");
}

function kpi(label, value, note) {
  return `
    <div class="kpi">
      <span>${escapeHtml(label)}</span>
      <strong>${escapeHtml(value)}</strong>
      <small>${escapeHtml(note)}</small>
    </div>
  `;
}

function statusPill(value) {
  const text = String(value || "-").replaceAll("_", " ");
  const lowered = text.toLowerCase();
  let cls = "";
  if (lowered.includes("blocked") || lowered.includes("critical") || lowered.includes("exceed")) cls = "red";
  else if (lowered.includes("partial") || lowered.includes("warning") || lowered.includes("watch")) cls = "amber";
  else if (lowered.includes("fallback") || lowered.includes("low")) cls = "violet";
  return `<span class="pill ${cls}">${escapeHtml(text)}</span>`;
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function setRefreshState(text) {
  document.getElementById("refreshState").textContent = text;
}

document.querySelectorAll(".nav-item").forEach(button => {
  button.addEventListener("click", () => {
    document.querySelectorAll(".nav-item").forEach(item => item.classList.remove("active"));
    document.querySelectorAll(".tab-panel").forEach(panel => panel.classList.remove("active"));
    button.classList.add("active");
    document.getElementById(`tab-${button.dataset.tab}`).classList.add("active");
    document.querySelector(".topbar h1").textContent = button.textContent;
  });
});

document.getElementById("recomputeButton").addEventListener("click", async () => {
  const button = document.getElementById("recomputeButton");
  button.disabled = true;
  button.textContent = "Running";
  setRefreshState("Recomputing");
  try {
    await api("/api/recompute", { method: "POST" });
    await loadAll();
  } finally {
    button.disabled = false;
    button.textContent = "Recompute";
  }
});

document.getElementById("bomSearch").addEventListener("input", renderBomRows);
document.getElementById("inventorySearch").addEventListener("input", renderInventoryCards);

loadAll().catch(error => {
  setRefreshState("Error");
  document.querySelector(".workspace").insertAdjacentHTML(
    "afterbegin",
    `<div class="panel"><strong>Application error</strong><p>${escapeHtml(error.message)}</p></div>`
  );
});
