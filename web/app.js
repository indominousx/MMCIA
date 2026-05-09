const state = {
  overview: null,
  decision: null,
  demand: null,
  inventory: null,
  procurement: null,
  substitutions: null,
  risk: null,
  forecast: null,
  recommendations: null,
  simulations: null,
  quality: null,
  alertConfig: null
};

const filters = {
  material: "",
  supplier: "",
  category: "",
  alertType: "",
  creditStatus: "",
  moqStatus: "",
  dateFrom: "",
  dateTo: ""
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

function sum(rows, key) {
  return (rows || []).reduce((total, row) => total + Number(row?.[key] || 0), 0);
}

async function api(path, options = {}) {
  const response = await fetch(path, options);
  if (!response.ok) throw new Error(`${path} failed with ${response.status}`);
  return response.json();
}

async function loadAll() {
  setRefreshState("Loading");
  const [
    overview,
    decision,
    demand,
    inventory,
    procurement,
    substitutions,
    risk,
    forecast,
    recommendations,
    simulations,
    quality,
    alertConfig
  ] = await Promise.all([
    api("/api/overview"),
    api("/api/decision-dashboard"),
    api("/api/demand-planning"),
    api("/api/inventory-management"),
    api("/api/smart-procurement"),
    api("/api/substitutions"),
    api("/api/risk-intelligence"),
    api("/api/advanced-forecast"),
    api("/api/ai-recommendations"),
    api("/api/simulation-lab"),
    api("/api/data-quality"),
    api("/api/alert-config")
  ]);
  Object.assign(state, {
    overview,
    decision,
    demand,
    inventory,
    procurement,
    substitutions,
    risk,
    forecast,
    recommendations,
    simulations,
    quality,
    alertConfig
  });
  setFilterOptions();
  renderAll();
  setRefreshState("Ready");
}

function renderAll() {
  renderOverview();
  renderDemand();
  renderInventory();
  renderRisk();
  renderForecast();
  renderProcurement();
  renderSubstitutions();
  renderRecommendations();
  renderSimulations();
  renderQuality();
  renderAlertCenter();
  renderEmailPanel();
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

  const riskSummary = state.risk?.summary || {};
  document.getElementById("riskSummaryCards").innerHTML = [
    alertCard("Critical materials", riskSummary.CRITICAL || 0, "Immediate escalation", "red"),
    alertCard("High risk", riskSummary.HIGH || 0, "Expedite supply", "amber"),
    alertCard("Avg risk score", Number(riskSummary.avgRiskScore || 0).toFixed(1), "Across portfolio", "violet")
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

  const actions = applyFilters(state.decision.immediateActions || [], { dateField: "order_by_date" }).slice(0, 8);
  document.getElementById("immediateActions").innerHTML = actions.map(row => `
    <tr>
      <td>${escapeHtml(row.material_name || row.material_id)}</td>
      <td>${escapeHtml(row.supplier_name || "-")}</td>
      <td>${qty(row.recommended_qty, row.unit)}</td>
      <td>${statusPill(row.credit_status)}</td>
    </tr>
  `).join("");

  const risks = applyFilters(overview.topRisks || [], { dateField: "first_stockout_date" });
  document.getElementById("riskList").innerHTML = risks.map(row => `
    <div class="risk-item">
      <strong>${escapeHtml(row.material_id)} · ${escapeHtml(row.material_name)}</strong>
      <span>${escapeHtml(row.first_stockout_date || "No date")} · ${row.days_to_stockout || "-"} day cover · shortage ${qty(row.projected_shortage_qty, row.unit)}</span>
    </div>
  `).join("");

  const recs = applyFilters(state.recommendations?.recommendations || [], {});
  document.getElementById("aiRecommendationsPreview").innerHTML = recs.slice(0, 6).map(row => `
    <div class="feed-item">
      <strong>${escapeHtml(row.material_name || row.material_id)} · ${escapeHtml(row.urgency || "-")}</strong>
      <span>${escapeHtml(row.recommended_action || "-")}</span>
      <span class="muted">${escapeHtml(row.reasoning || "")}</span>
    </div>
  `).join("");

  const scenarios = state.simulations?.scenarios || [];
  document.getElementById("scenarioHighlights").innerHTML = scenarios.slice(0, 4).map(row => `
    <div class="feed-item">
      <strong>${escapeHtml(row.scenario)}</strong>
      <span>Stockouts ${row.projected_stockouts} · Delays ${row.delayed_orders}</span>
      <span class="muted">${escapeHtml(row.scenario_summary || "")}</span>
    </div>
  `).join("");
}

function renderDemand() {
  const weekTotals = applyDateRange(state.demand.weekTotals || [], "week_start", "week_end");
  drawBars("weekDemandChart", weekTotals, "forecast_week", "seasonal_required_qty", row => `Week ${row.forecast_week}`);

  const materialTotals = applyFilters(state.demand.materialTotals || [], {});
  drawBars(
    "materialDemandChart",
    materialTotals.slice(0, 10),
    "material_id",
    "seasonal_required_qty",
    row => `${row.material_id} ${row.canonical_unit}`
  );
  renderBomRows();
}

function renderBomRows() {
  const needle = document.getElementById("bomSearch").value.trim().toLowerCase();
  const rows = applyFilters(state.demand.bomTraceSample || [], { dateField: "delivery_date" }).filter(row => {
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
  const slowMoving = applyFilters(state.inventory.slowMoving || [], {});
  document.getElementById("slowMovingRows").innerHTML = slowMoving.map(row => `
    <tr>
      <td>${escapeHtml(row.material_id)} · ${escapeHtml(row.name)}</td>
      <td>${qty(row.current_stock, row.unit)}</td>
      <td>${qty(row.forecast_demand_4w, row.unit)}</td>
      <td>${escapeHtml(row.watchlist_reason)}</td>
    </tr>
  `).join("");
}

function renderRisk() {
  const needle = document.getElementById("riskSearch")?.value.trim().toLowerCase() || "";
  const scores = applyFilters(state.risk?.scores || [], {});
  const filtered = scores.filter(row => {
    if (!needle) return true;
    return `${row.material_id || ""} ${row.material_name || ""}`.toLowerCase().includes(needle);
  });

  document.getElementById("riskHeatmap").innerHTML = filtered.slice(0, 60).map(row => `
    <div class="risk-tile ${severityClass(row.severity)}">
      <strong>${escapeHtml(row.material_id)} · ${escapeHtml(row.material_name)}</strong>
      <span>Risk score ${Number(row.risk_score || 0).toFixed(1)}</span>
      <span>${statusPill(row.severity)}</span>
    </div>
  `).join("");

  document.getElementById("riskRows").innerHTML = filtered.map(row => `
    <tr>
      <td>${escapeHtml(row.material_id)} · ${escapeHtml(row.material_name)}</td>
      <td>${Number(row.risk_score || 0).toFixed(1)}</td>
      <td>${statusPill(row.severity)}</td>
      <td>${escapeHtml(row.contributing_factors || "-")}</td>
      <td>${escapeHtml(row.mitigation_suggestions || "-")}</td>
    </tr>
  `).join("");

  const supplierRisks = applyFilters(state.risk?.supplierRisks || [], {});
  document.getElementById("supplierRiskRows").innerHTML = supplierRisks.map(row => `
    <tr>
      <td>${escapeHtml(row.supplier_name || "-")}</td>
      <td>${Number(row.avg_risk_score || 0).toFixed(1)}</td>
      <td>${row.material_count || 0}</td>
    </tr>
  `).join("");
}

function renderForecast() {
  const weekly = state.forecast?.weeklyTotals || [];
  drawBars(
    "forecastWeekChart",
    weekly,
    "forecast_week",
    "predicted_demand",
    row => formatWeekLabel(row.forecast_week)
  );

  const volatility = applyFilters(state.forecast?.topVolatility || [], {});
  document.getElementById("volatilityRows").innerHTML = volatility.map(row => `
    <tr>
      <td>${escapeHtml(row.material_id)} · ${escapeHtml(row.material_name || "")}</td>
      <td>${Number(row.volatility_score || 0).toFixed(1)}%</td>
    </tr>
  `).join("");
}

function renderInventoryCards() {
  const needle = document.getElementById("inventorySearch").value.trim().toLowerCase();
  const rows = applyFilters(state.inventory.coverage || [], { dateField: "first_stockout_date" }).filter(row => {
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
  const approved = applyFilters(state.procurement.approved || [], { dateField: "order_by_date" });
  document.getElementById("approvedRows").innerHTML = approved.map(row => `
    <tr>
      <td>${escapeHtml(row.supplier_name)}</td>
      <td>${escapeHtml(row.material_id)} · ${escapeHtml(row.material_name)}</td>
      <td>${qty(row.recommended_qty, row.unit)}</td>
      <td>${inr(row.recommended_value_inr)}</td>
      <td>${inr(row.projected_credit_utilized_after_line_inr)}</td>
    </tr>
  `).join("");
  const blocked = applyFilters(state.procurement.blocked || [], { dateField: "order_by_date" });
  document.getElementById("blockedRows").innerHTML = blocked.map(row => `
    <tr>
      <td>${escapeHtml(row.material_id)} · ${escapeHtml(row.material_name)}</td>
      <td>${escapeHtml(row.supplier_name || "-")}</td>
      <td>${qty(row.recommended_qty, row.unit)}</td>
      <td>${inr(row.recommended_value_inr)}</td>
    </tr>
  `).join("");
  renderSupplierExposure(approved, blocked);
}

function renderSubstitutions() {
  const substitutions = applyFilters(state.substitutions.allSubstitutions || [], { dateField: "first_stockout_date" });
  document.getElementById("substitutionCards").innerHTML = substitutions.map(row => `
    <div class="sub-card">
      <strong>${escapeHtml(row.source_material_id)} → ${escapeHtml(row.substitute_material_id)}</strong>
      <span>${escapeHtml(row.source_material_name || "")}</span>
      <span>${escapeHtml(row.substitute_material_name || "")}</span>
      <span>${escapeHtml(row.supplier_name || "-")} · ${qty(row.recommended_purchase_qty, row.unit)}</span>
      <span>${statusPill(row.credit_status || "review")}</span>
    </div>
  `).join("");
}

function renderRecommendations() {
  const needle = document.getElementById("recommendationSearch")?.value.trim().toLowerCase() || "";
  const recommendations = applyFilters(state.recommendations?.recommendations || [], {});
  const filtered = recommendations.filter(row => {
    if (!needle) return true;
    return `${row.material_id || ""} ${row.material_name || ""} ${row.recommended_action || ""}`
      .toLowerCase()
      .includes(needle);
  });

  document.getElementById("recommendationRows").innerHTML = filtered.map(row => `
    <tr>
      <td>${escapeHtml(row.material_id)} · ${escapeHtml(row.material_name)}</td>
      <td>${escapeHtml(row.issue_detected || "-")}</td>
      <td>${escapeHtml(row.recommended_action || "-")}</td>
      <td>${statusPill(row.urgency || "-")}</td>
      <td>${escapeHtml(row.business_impact || "-")}</td>
    </tr>
  `).join("");
}

function renderSimulations() {
  const scenarios = state.simulations?.scenarios || [];
  document.getElementById("simulationCards").innerHTML = scenarios.map(row => `
    <div class="scenario-card">
      <strong>${escapeHtml(row.scenario)}</strong>
      <span>Stockouts ${row.projected_stockouts || 0} · Delays ${row.delayed_orders || 0}</span>
      <span>Losses ${inr(row.simulated_losses_inr || 0)}</span>
      <span class="muted">${escapeHtml(row.scenario_summary || "")}</span>
    </div>
  `).join("");

  document.getElementById("simulationRows").innerHTML = scenarios.map(row => `
    <tr>
      <td>${escapeHtml(row.scenario)}</td>
      <td>${row.projected_stockouts || 0}</td>
      <td>${row.delayed_orders || 0}</td>
      <td>${inr(row.simulated_losses_inr || 0)}</td>
      <td>${Number(row.risk_change_pct || 0).toFixed(1)}%</td>
    </tr>
  `).join("");
}

function collectScenarioPayload() {
  return {
    label: document.getElementById('sim-name')?.value || undefined,
    demand_spike: parseFloat(document.getElementById('sim-demand-spike')?.value) || 0.0,
    supplier_delay_days: parseInt(document.getElementById('sim-supplier-delay')?.value) || 0,
    credit_reduction: parseFloat(document.getElementById('sim-credit-reduction')?.value) || 0.0,
    inventory_shrinkage: parseFloat(document.getElementById('sim-shrinkage')?.value) || 0.0,
    approval_delay_days: parseInt(document.getElementById('sim-approval-delay')?.value) || 0,
  };
}

async function runScenario() {
  const btn = document.getElementById('run-sim-btn');
  if (btn) btn.disabled = true;
  try {
    const payload = collectScenarioPayload();
    const response = await api('/api/run-scenario', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
    if (response && response.ok && Array.isArray(response.scenarios)) {
      state.simulations = { scenarios: response.scenarios };
      renderSimulations();
    } else if (response && response.ok) {
      state.simulations = { scenarios: response.scenarios || [] };
      renderSimulations();
      alert('Simulation returned no scenarios.');
    } else {
      alert('Simulation failed: ' + (response?.error || 'unknown'));
    }
  } catch (e) {
    alert('Simulation error: ' + (e.message || e));
  } finally {
    if (btn) btn.disabled = false;
  }
}

function resetScenarioForm() {
  const fields = ['sim-name','sim-demand-spike','sim-supplier-delay','sim-credit-reduction','sim-shrinkage','sim-approval-delay'];
  fields.forEach(id => { const el = document.getElementById(id); if (el) el.value = el.defaultValue ?? '' });
}

// wire buttons after DOM ready
document.addEventListener('DOMContentLoaded', () => {
  const runBtn = document.getElementById('run-sim-btn');
  if (runBtn) runBtn.addEventListener('click', runScenario);
  const resetBtn = document.getElementById('reset-sim-btn');
  if (resetBtn) resetBtn.addEventListener('click', resetScenarioForm);
});

function renderQuality() {
  const qualityRows = state.quality.issues || [];
  document.getElementById("qualityRows").innerHTML = qualityRows.map(row => `
    <tr>
      <td>${statusPill(row.severity)}</td>
      <td>${escapeHtml(row.file)}</td>
      <td>${escapeHtml(row.issue_type)}<br><span class="muted">${escapeHtml(row.detail)}</span></td>
    </tr>
  `).join("");
  const unitRows = state.quality.unitConversions || [];
  document.getElementById("unitRows").innerHTML = unitRows.slice(0, 120).map(row => `
    <tr>
      <td>${escapeHtml(row.material_id)}</td>
      <td>${escapeHtml(row.original_unit)}</td>
      <td>${escapeHtml(row.target_unit)}</td>
      <td>${statusPill(row.conversion_confidence)}</td>
    </tr>
  `).join("");
}

function renderAlertCenter() {
  const alerts = applyFilters(state.inventory.alerts || [], { dateField: "first_stockout_date" });
  const critical = alerts.filter(row => {
    const type = String(row.alert_type || "");
    return type.includes("less_than_3_days") || row.under_3_days_stock === true || row.under_3_days_stock === "True";
  });
  const watch = alerts.filter(row => !critical.includes(row));
  const blockedValue = sum(state.procurement.blocked, "recommended_value_inr");

  document.getElementById("alertSummary").innerHTML = [
    alertCard("Critical (<3 days)", critical.length, "Immediate escalation", "red"),
    alertCard("Stockout <=21 days", watch.length, "Expedite supplier plan", "amber"),
    alertCard("Credit blocked value", inr(blockedValue), `${state.procurement.blocked.length} blocked lines`, "violet")
  ].join("");

  const timeline = alerts.slice(0, 6);
  document.getElementById("alertTimeline").innerHTML = timeline.map(row => `
    <div class="alert-item">
      <strong>${escapeHtml(row.material_id)} · ${escapeHtml(row.material_name)}</strong>
      <span>${escapeHtml(row.first_stockout_date || "No date")} · ${row.days_to_stockout || "-"} days cover · shortage ${qty(row.projected_shortage_qty, row.unit)}</span>
      <span>${statusPill(row.alert_type || "watch")}</span>
    </div>
  `).join("");

  document.getElementById("alertStatus").textContent = critical.length > 0 ? "Escalate now" : "Monitoring";
}

function renderEmailPanel() {
  const config = state.alertConfig || {};
  const recipients = (config.recipients || []).join(", ") || "Not configured";
  const fromEmail = config.fromEmail || "Not configured";
  const missing = config.missing || [];
  const ready = Boolean(config.enabled);

  document.getElementById("emailRecipients").textContent = recipients;
  document.getElementById("emailFrom").textContent = fromEmail;
  document.getElementById("emailStatus").textContent = ready ? "Ready" : `Missing ${missing.join(", ")}`;
  const sendButton = document.getElementById("sendAlertButton");
  sendButton.disabled = !ready;
}

function renderSupplierExposure(approved, blocked) {
  const bySupplier = new Map();

  function addRow(row, key) {
    const id = row.supplier_id || row.supplier_name || "unknown";
    const entry = bySupplier.get(id) || {
      supplier: row.supplier_name || "Unknown",
      approvedValue: 0,
      blockedValue: 0,
      reliability: row.reliability_score ?? "-"
    };
    entry[key] += Number(row.recommended_value_inr || 0);
    if (entry.reliability === "-" && row.reliability_score != null) {
      entry.reliability = row.reliability_score;
    }
    bySupplier.set(id, entry);
  }

  approved.forEach(row => addRow(row, "approvedValue"));
  blocked.forEach(row => addRow(row, "blockedValue"));

  const rows = Array.from(bySupplier.values()).map(row => ({
    ...row,
    total: row.approvedValue + row.blockedValue
  })).sort((a, b) => b.total - a.total).slice(0, 8);

  document.getElementById("supplierExposure").innerHTML = rows.map(row => {
    const approvedPct = row.total > 0 ? (row.approvedValue / row.total) * 100 : 0;
    const blockedPct = row.total > 0 ? (row.blockedValue / row.total) * 100 : 0;
    return `
      <div class="exposure-card">
        <strong>${escapeHtml(row.supplier)}</strong>
        <span>Approved ${inr(row.approvedValue)} · Blocked ${inr(row.blockedValue)}</span>
        <span>Reliability ${row.reliability}</span>
        <div class="exposure-meter">
          <div class="exposure-fill" style="width:${approvedPct}%"></div>
          <div class="exposure-fill blocked" style="width:${blockedPct}%"></div>
        </div>
      </div>
    `;
  }).join("");
}

function drawBars(targetId, rows, labelKey, valueKey, labelFn) {
  if (!rows || rows.length === 0) {
    document.getElementById(targetId).innerHTML = "<span class=\"muted\">No data available.</span>";
    return;
  }
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
  else if (lowered.includes("high") || lowered.includes("medium") || lowered.includes("partial") || lowered.includes("warning") || lowered.includes("watch")) cls = "amber";
  else if (lowered.includes("fallback") || lowered.includes("low")) cls = "violet";
  return `<span class="pill ${cls}">${escapeHtml(text)}</span>`;
}

function severityClass(value) {
  const lowered = String(value || "").toLowerCase();
  if (lowered.includes("critical")) return "critical";
  if (lowered.includes("high")) return "high";
  if (lowered.includes("medium")) return "medium";
  return "low";
}

function formatWeekLabel(value) {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return date.toLocaleDateString("en-IN", { month: "short", day: "numeric" });
}

function alertCard(label, value, note, tone) {
  const cls = tone ? `alert-card ${tone}` : "alert-card";
  return `
    <div class="${cls}">
      <span>${escapeHtml(label)}</span>
      <strong>${escapeHtml(String(value))}</strong>
      <small>${escapeHtml(note)}</small>
    </div>
  `;
}

function applyFilters(rows, options = {}) {
  const dateField = options.dateField || "";
  return rows.filter(row => {
    if (filters.material && !matchesMaterial(row, filters.material)) return false;
    if (filters.supplier && !matchesSupplier(row, filters.supplier)) return false;
    if (filters.category && String(row.category || "") !== filters.category) return false;
    if (filters.alertType && String(row.alert_type || "") !== filters.alertType) return false;
    if (filters.creditStatus && String(row.credit_status || "") !== filters.creditStatus) return false;
    if (filters.moqStatus && moqStatus(row) !== filters.moqStatus) return false;
    if (!matchesDateRange(row, dateField)) return false;
    return true;
  });
}

function applyDateRange(rows, startField, endField) {
  if (!filters.dateFrom && !filters.dateTo) return rows;
  return rows.filter(row => {
    const start = parseDate(row[startField]);
    const end = parseDate(row[endField] || row[startField]);
    if (!start) return false;
    if (filters.dateFrom && end < parseDate(filters.dateFrom)) return false;
    if (filters.dateTo && start > parseDate(filters.dateTo)) return false;
    return true;
  });
}

function matchesMaterial(row, material) {
  const materialId = String(row.material_id || "");
  const source = String(row.source_material_id || "");
  const substitute = String(row.substitute_material_id || "");
  return material === materialId || material === source || material === substitute;
}

function matchesSupplier(row, supplier) {
  const id = String(row.supplier_id || "");
  const name = String(row.supplier_name || "");
  return supplier === id || supplier === name;
}

function matchesDateRange(row, dateField) {
  if (!filters.dateFrom && !filters.dateTo) return true;
  if (!dateField) return true;
  const date = parseDate(row[dateField]);
  if (!date) return false;
  if (filters.dateFrom && date < parseDate(filters.dateFrom)) return false;
  if (filters.dateTo && date > parseDate(filters.dateTo)) return false;
  return true;
}

function parseDate(value) {
  if (!value) return null;
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? null : parsed;
}

function moqStatus(row) {
  if (row == null) return "not_applicable";
  const moq = Number(row.moq || row.moq_unit || 0);
  const qty = Number(row.recommended_qty || row.recommended_full_qty || 0);
  if (!moq || Number.isNaN(moq)) return "not_applicable";
  return qty >= moq ? "meets_moq" : "below_moq";
}

function setFilterOptions() {
  const materialIds = new Set();
  const supplierNames = new Set();
  const categories = new Set();
  const alertTypes = new Set();
  const creditStatuses = new Set();

  (state.inventory.coverage || []).forEach(row => {
    if (row.material_id) materialIds.add(row.material_id);
    if (row.category) categories.add(row.category);
  });

  (state.risk?.scores || []).forEach(row => {
    if (row.material_id) materialIds.add(row.material_id);
    if (row.category) categories.add(row.category);
  });

  (state.procurement.approved || []).concat(state.procurement.blocked || []).forEach(row => {
    if (row.material_id) materialIds.add(row.material_id);
    if (row.supplier_name) supplierNames.add(row.supplier_name);
    if (row.supplier_id) supplierNames.add(row.supplier_id);
    if (row.credit_status) creditStatuses.add(row.credit_status);
  });

  (state.substitutions.allSubstitutions || []).forEach(row => {
    if (row.source_material_id) materialIds.add(row.source_material_id);
    if (row.substitute_material_id) materialIds.add(row.substitute_material_id);
    if (row.supplier_name) supplierNames.add(row.supplier_name);
    if (row.credit_status) creditStatuses.add(row.credit_status);
  });

  (state.recommendations?.recommendations || []).forEach(row => {
    if (row.material_id) materialIds.add(row.material_id);
  });

  (state.forecast?.topVolatility || []).forEach(row => {
    if (row.material_id) materialIds.add(row.material_id);
  });

  (state.quality?.unitConversions || []).forEach(row => {
    if (row.material_id) materialIds.add(row.material_id);
  });

  (state.inventory.alerts || []).forEach(row => {
    if (row.alert_type) alertTypes.add(row.alert_type);
  });

  (state.risk?.supplierRisks || []).forEach(row => {
    if (row.supplier_name) supplierNames.add(row.supplier_name);
  });

  setSelectOptions("filterMaterial", materialIds, "All materials");
  setSelectOptions("filterSupplier", supplierNames, "All suppliers");
  setSelectOptions("filterCategory", categories, "All categories");
  setSelectOptions("filterAlertType", alertTypes, "All alert types");
  setSelectOptions("filterCreditStatus", creditStatuses, "All credit statuses");
  setSelectOptions(
    "filterMoqStatus",
    new Set(["meets_moq", "below_moq", "not_applicable"]),
    "All MOQ statuses"
  );
}

function setSelectOptions(id, values, allLabel) {
  const select = document.getElementById(id);
  const sorted = Array.from(values).sort();
  select.innerHTML = [
    `<option value="">${escapeHtml(allLabel)}</option>`,
    ...sorted.map(value => `<option value="${escapeHtml(value)}">${escapeHtml(value)}</option>`)
  ].join("");
}

function bindFilters() {
  const mapping = [
    ["filterMaterial", "material"],
    ["filterSupplier", "supplier"],
    ["filterCategory", "category"],
    ["filterAlertType", "alertType"],
    ["filterCreditStatus", "creditStatus"],
    ["filterMoqStatus", "moqStatus"],
    ["filterDateFrom", "dateFrom"],
    ["filterDateTo", "dateTo"]
  ];

  mapping.forEach(([id, key]) => {
    const element = document.getElementById(id);
    element.addEventListener("change", () => {
      filters[key] = element.value;
      renderAll();
    });
  });

  document.getElementById("filterReset").addEventListener("click", () => {
    Object.assign(filters, {
      material: "",
      supplier: "",
      category: "",
      alertType: "",
      creditStatus: "",
      moqStatus: "",
      dateFrom: "",
      dateTo: ""
    });
    mapping.forEach(([id]) => {
      const element = document.getElementById(id);
      element.value = "";
    });
    renderAll();
  });
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

document.getElementById("sendAlertButton").addEventListener("click", async () => {
  const button = document.getElementById("sendAlertButton");
  const status = document.getElementById("emailStatus");
  const log = document.getElementById("emailLog");
  button.disabled = true;
  button.textContent = "Sending";
  status.textContent = "Sending";
  try {
    const response = await api("/api/send-alerts", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({})
    });
    if (response.ok) {
      status.textContent = "Sent";
      log.textContent = `Alert email sent to ${response.recipients.join(", ")}.`;
    } else {
      status.textContent = "Failed";
      log.textContent = response.error === "missing_email_settings"
        ? `Missing settings: ${response.missing.join(", ")}.`
        : `Send failed: ${response.detail || response.error}`;
    }
  } catch (error) {
    status.textContent = "Failed";
    log.textContent = error.message;
  } finally {
    button.disabled = false;
    button.textContent = "Send alerts";
  }
});

document.getElementById("bomSearch").addEventListener("input", renderBomRows);
document.getElementById("inventorySearch").addEventListener("input", renderInventoryCards);
document.getElementById("riskSearch").addEventListener("input", renderRisk);
document.getElementById("recommendationSearch").addEventListener("input", renderRecommendations);

loadAll().catch(error => {
  setRefreshState("Error");
  document.querySelector(".workspace").insertAdjacentHTML(
    "afterbegin",
    `<div class="panel"><strong>Application error</strong><p>${escapeHtml(error.message)}</p></div>`
  );
});

bindFilters();
