const chartInstances = {};

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
  material: [],
  supplier: [],
  category: [],
  alertType: [],
  creditStatus: [],
  moqStatus: [],
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
  document.getElementById("aiRecommendationsPreview").innerHTML = recs.slice(0, 6).map((row, index) => `
    <div class="feed-item">
      <div style="display: flex; justify-content: space-between; align-items: flex-start; gap: 12px;">
        <div>
          <strong>${escapeHtml(row.material_name || row.material_id)} · ${escapeHtml(row.urgency || "-")}</strong>
          <span>${escapeHtml(row.recommended_action || "-")}</span>
          <span class="muted">${escapeHtml(row.reasoning || "")}</span>
        </div>
        <button class="button secondary small" onclick="simulateRecommendation('${escapeHtml(row.material_id)}')" style="white-space: nowrap;">Test</button>
      </div>
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

  renderOverviewCharts();
}

function renderOverviewCharts() {
  const riskSummary = state.risk?.summary || {};
  const ctxRisk = document.getElementById('overviewRiskChart');
  if (chartInstances.overviewRisk) chartInstances.overviewRisk.destroy();
  
  if (ctxRisk) {
    chartInstances.overviewRisk = new Chart(ctxRisk, {
      type: 'doughnut',
      data: {
        labels: ['Critical', 'High', 'Medium', 'Low'],
        datasets: [{
          data: [
            riskSummary.CRITICAL || 0,
            riskSummary.HIGH || 0,
            riskSummary.MEDIUM || 0,
            riskSummary.LOW || 0
          ],
          backgroundColor: ['#ef4444', '#f59e0b', '#3b82f6', '#10b981'],
          borderWidth: 0
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { position: 'right', labels: { color: '#e2e8f0' } }
        }
      }
    });
  }

  const weekTotals = applyDateRange(state.demand?.weekTotals || [], "week_start", "week_end");
  const ctxDemand = document.getElementById('overviewDemandChart');
  if (chartInstances.overviewDemand) chartInstances.overviewDemand.destroy();

  if (ctxDemand && weekTotals.length > 0) {
    chartInstances.overviewDemand = new Chart(ctxDemand, {
      type: 'bar',
      data: {
        labels: weekTotals.map(r => `Week ${r.forecast_week}`),
        datasets: [{
          label: 'Demand',
          data: weekTotals.map(r => Number(r.seasonal_required_qty || 0)),
          backgroundColor: '#6366f1',
          borderRadius: 4
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { display: false }
        },
        scales: {
          y: { grid: { color: 'rgba(255,255,255,0.05)' }, ticks: { color: '#94a3b8' } },
          x: { grid: { display: false }, ticks: { color: '#94a3b8' } }
        }
      }
    });
  }
}

function renderDemand() {
  const weekTotals = applyDateRange(state.demand.weekTotals || [], "week_start", "week_end");
  const ctxWeek = document.getElementById("weekDemandChart");
  if (chartInstances.weekDemand) chartInstances.weekDemand.destroy();
  if (ctxWeek && weekTotals.length > 0) {
    chartInstances.weekDemand = new Chart(ctxWeek, {
      type: 'line',
      data: {
        labels: weekTotals.map(row => `Week ${row.forecast_week}`),
        datasets: [{
          label: 'Total Demand',
          data: weekTotals.map(row => Number(row.seasonal_required_qty || 0)),
          borderColor: '#10b981',
          backgroundColor: 'rgba(16, 185, 129, 0.1)',
          fill: true,
          tension: 0.4
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: { legend: { display: false } },
        scales: {
          y: { grid: { color: 'rgba(255,255,255,0.05)' }, ticks: { color: '#94a3b8' } },
          x: { grid: { display: false }, ticks: { color: '#94a3b8' } }
        }
      }
    });
  }

  const materialTotals = applyFilters(state.demand.materialTotals || [], {});
  const topMaterials = materialTotals.slice(0, 10);
  const ctxMat = document.getElementById("materialDemandChart");
  if (chartInstances.materialDemand) chartInstances.materialDemand.destroy();
  if (ctxMat && topMaterials.length > 0) {
    chartInstances.materialDemand = new Chart(ctxMat, {
      type: 'bar',
      data: {
        labels: topMaterials.map(row => `${row.material_id}`),
        datasets: [{
          label: 'Material Demand',
          data: topMaterials.map(row => Number(row.seasonal_required_qty || 0)),
          backgroundColor: '#3b82f6',
          borderRadius: 4
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        onClick: (e, elements) => {
          if (elements.length > 0) {
            const index = elements[0].index;
            if (topMaterials[index]) {
              applyChartFilter('material', topMaterials[index].material_id);
            }
          }
        },
        indexAxis: 'y',
        plugins: { legend: { display: false } },
        scales: {
          x: { grid: { color: 'rgba(255,255,255,0.05)' }, ticks: { color: '#94a3b8' } },
          y: { grid: { display: false }, ticks: { color: '#94a3b8' } }
        }
      }
    });
  }
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

  const ctxRadar = document.getElementById("inventoryScatterChart");
  if (chartInstances.inventoryScatter) chartInstances.inventoryScatter.destroy();
  if (ctxRadar && rows.length > 0) {
    // Get top 5 items most at risk (lowest days_to_stockout, highest demand)
    const topRisks = [...rows]
      .sort((a, b) => {
        const aDays = a.days_to_stockout ?? 999;
        const bDays = b.days_to_stockout ?? 999;
        if (aDays !== bDays) return aDays - bDays;
        return (b.total_demand_21d || 0) - (a.total_demand_21d || 0);
      })
      .slice(0, 5);

    const maxShortage = Math.max(...topRisks.map(r => r.total_demand_21d || 1), 1);
    const maxDemand = Math.max(...topRisks.map(r => r.total_demand_21d || 1), 1); // Using demand_21d as proxy if others missing

    chartInstances.inventoryScatter = new Chart(ctxRadar, {
      type: 'radar',
      data: {
        labels: ['Urgency', 'Shortage Volume', 'Demand Pressure', 'Risk Severity'],
        datasets: topRisks.map((r, i) => {
          const colors = ['#ef4444', '#f59e0b', '#3b82f6', '#10b981', '#6366f1'];
          const days = r.days_to_stockout ?? 30;
          const urgency = Math.max(0, 100 - (days * 3.33)); // 0 days = 100, 30 days = 0
          const shortage = ((r.total_demand_21d || 0) / maxShortage) * 100;
          const demand = ((r.total_demand_21d || 0) / maxDemand) * 100;
          const severity = (r.under_3_days_stock === true || r.under_3_days_stock === "True") ? 100 : 50;

          return {
            label: r.material_id,
            data: [urgency, shortage, demand, severity],
            backgroundColor: `${colors[i % colors.length]}33`,
            borderColor: colors[i % colors.length],
            borderWidth: 2,
            pointBackgroundColor: colors[i % colors.length]
          };
        })
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        onClick: (e, elements) => {
          if (elements.length > 0) {
            const datasetIndex = elements[0].datasetIndex;
            if (topRisks[datasetIndex]) {
              applyChartFilter('material', topRisks[datasetIndex].material_id);
            }
          }
        },
        plugins: {
          legend: { position: 'right', labels: { color: '#e2e8f0' } }
        },
        scales: {
          r: {
            angleLines: { color: 'rgba(255,255,255,0.1)' },
            grid: { color: 'rgba(255,255,255,0.1)' },
            pointLabels: { color: '#94a3b8', font: { size: 11 } },
            ticks: { display: false, max: 100, min: 0, stepSize: 20 }
          }
        }
      }
    });
  }

  document.getElementById("inventoryCards").innerHTML = rows.map(row => {
    const critical = row.under_3_days_stock === true || row.under_3_days_stock === "True";
    return `
      <div class="inventory-card clickable-row ${critical ? "critical" : "watch"}" onclick="openMaterial360('${escapeHtml(row.material_id)}')">
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
    <tr class="clickable-row" onclick="openMaterial360('${escapeHtml(row.material_id)}')">
      <td><span style="color: #3b82f6; font-weight: 500;" onclick="openSupplier360('${escapeHtml(row.supplier_name)}', event)">${escapeHtml(row.supplier_name)}</span></td>
      <td>${escapeHtml(row.material_id)} · ${escapeHtml(row.material_name)}</td>
      <td>${qty(row.recommended_qty, row.unit)}</td>
      <td>${inr(row.recommended_value_inr)}</td>
      <td>${inr(row.projected_credit_utilized_after_line_inr)}</td>
    </tr>
  `).join("");
  const blocked = applyFilters(state.procurement.blocked || [], { dateField: "order_by_date" });
  document.getElementById("blockedRows").innerHTML = blocked.map(row => `
    <tr class="clickable-row" onclick="openMaterial360('${escapeHtml(row.material_id)}')">
      <td>${escapeHtml(row.material_id)} · ${escapeHtml(row.material_name)}</td>
      <td><span style="color: #3b82f6; font-weight: 500;" onclick="openSupplier360('${escapeHtml(row.supplier_name || "")}', event)">${escapeHtml(row.supplier_name || "-")}</span></td>
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

  document.getElementById("recommendationRows").innerHTML = filtered.map((row, index) => `
    <tr>
      <td>${escapeHtml(row.material_id)} · ${escapeHtml(row.material_name)}</td>
      <td>${escapeHtml(row.issue_detected || "-")}</td>
      <td>${escapeHtml(row.recommended_action || "-")}</td>
      <td>${statusPill(row.urgency || "-")}</td>
      <td>
        <div style="display: flex; justify-content: space-between; align-items: center;">
          <span>${escapeHtml(row.business_impact || "-")}</span>
          <button class="button secondary small" onclick="simulateRecommendation('${escapeHtml(row.material_id)}')" style="white-space: nowrap;">Test Impact</button>
        </div>
      </td>
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

  document.getElementById("simulationRows").innerHTML = scenarios.map((row, index) => `
    <tr>
      <td>${escapeHtml(row.scenario)}</td>
      <td>${row.projected_stockouts || 0}</td>
      <td>${row.delayed_orders || 0}</td>
      <td>${inr(row.simulated_losses_inr || 0)}</td>
      <td>${Number(row.risk_change_pct || 0).toFixed(1)}%</td>
      <td><button class="button secondary small" onclick="deleteScenario(${index})">Delete</button></td>
    </tr>
  `).join("");
}

window.deleteScenario = async function(index) {
  if (confirm("Delete this scenario permanently?")) {
    try {
      const response = await api('/api/delete-scenario', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ index })
      });
      if (response && response.ok) {
        state.simulations = { scenarios: response.scenarios };
        renderSimulations();
        renderOverview();
      } else {
        alert('Delete failed: ' + (response?.error || 'unknown'));
      }
    } catch (e) {
      alert('Delete error: ' + (e.message || e));
    }
  }
};

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
      renderOverview();
    } else if (response && response.ok) {
      state.simulations = { scenarios: response.scenarios || [] };
      renderSimulations();
      renderOverview();
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

// wire buttons
const runBtn = document.getElementById('run-sim-btn');
if (runBtn) runBtn.addEventListener('click', runScenario);
const resetBtn = document.getElementById('reset-sim-btn');
if (resetBtn) resetBtn.addEventListener('click', resetScenarioForm);

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
  const blockedValue = sum(state.procurement.blocked, "recommended_value_inr");

  document.getElementById("alertSummary").innerHTML = [
    alertCard("Critical (<3 days)", critical.length, "Immediate escalation", "red"),
    alertCard("21-day stockout alerts", alerts.length, "Includes critical items", "amber"),
    alertCard("Credit blocked value", inr(blockedValue), `${state.procurement.blocked.length} blocked lines`, "violet")
  ].join("");

  const timeline = alerts.slice(0, 6);
  document.getElementById("alertTimeline").innerHTML = timeline.map(row => `
    <div class="alert-item clickable-row" onclick="openMaterial360('${escapeHtml(row.material_id)}')">
      <div style="flex: 1;">
        <strong>${escapeHtml(row.material_id)} · ${escapeHtml(row.material_name)}</strong>
        <span>${escapeHtml(row.first_stockout_date || "No date")} · ${row.days_to_stockout || "-"} days cover · shortage ${qty(row.projected_shortage_qty, row.unit)}</span>
        <span>${statusPill(row.alert_type || "watch")}</span>
      </div>
      <button class="button secondary small" onclick="dismissAlert('${escapeHtml(row.material_id)}', event)" aria-label="Dismiss">Dismiss</button>
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
  const roleRecipients = config.roleRecipients || {};

  document.getElementById("emailRecipients").textContent = recipients;
  document.getElementById("productionRecipients").textContent = (roleRecipients.production || []).join(", ") || "Not configured";
  document.getElementById("financeRecipients").textContent = (roleRecipients.finance || []).join(", ") || "Not configured";
  document.getElementById("procurementRecipients").textContent = (roleRecipients.procurement || []).join(", ") || "Not configured";
  document.getElementById("emailFrom").textContent = fromEmail;
  document.getElementById("emailStatus").textContent = ready ? "Ready" : `Missing ${missing.join(", ")}`;
  const sendButton = document.getElementById("sendAlertButton");
  const reportButton = document.getElementById("sendDailyReportButton");
  sendButton.disabled = !ready;
  reportButton.disabled = !ready;
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

  const ctxExposure = document.getElementById("supplierExposureChart");
  if (chartInstances.supplierExposure) chartInstances.supplierExposure.destroy();
  if (ctxExposure && rows.length > 0) {
    chartInstances.supplierExposure = new Chart(ctxExposure, {
      type: 'bar',
      data: {
        labels: rows.map(r => r.supplier),
        datasets: [
          {
            label: 'Approved Value',
            data: rows.map(r => r.approvedValue),
            backgroundColor: '#10b981'
          },
          {
            label: 'Blocked Value',
            data: rows.map(r => r.blockedValue),
            backgroundColor: '#ef4444'
          },
          {
            label: 'Reliability Score',
            data: rows.map(r => {
              const num = Number(r.reliability);
              return isNaN(num) ? 50 : num * 100;
            }),
            type: 'line',
            borderColor: '#f59e0b',
            backgroundColor: '#f59e0b',
            borderWidth: 2,
            pointRadius: 4,
            yAxisID: 'y1',
          }
        ]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        onClick: (e, elements) => {
          if (elements.length > 0) {
            const index = elements[0].index;
            if (rows[index]) {
              applyChartFilter('supplier', rows[index].supplier);
            }
          }
        },
        plugins: { legend: { labels: { color: '#e2e8f0' } } },
        scales: {
          x: { grid: { display: false }, ticks: { color: '#94a3b8' } },
          y: { 
            type: 'logarithmic',
            grid: { color: 'rgba(255,255,255,0.05)' }, 
            ticks: { color: '#94a3b8' },
            title: { display: true, text: 'Value (INR, Log Scale)', color: '#94a3b8' }
          },
          y1: {
            position: 'right',
            grid: { display: false },
            ticks: { color: '#f59e0b' },
            title: { display: true, text: 'Reliability (0-100)', color: '#f59e0b' },
            min: 0,
            max: 100
          }
        }
      }
    });
  }

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

function hasMaterial(row) {
  return 'material_id' in row || 'source_material_id' in row || 'substitute_material_id' in row;
}

function hasSupplier(row) {
  return 'supplier_id' in row || 'supplier_name' in row;
}

function hasMoq(row) {
  return 'moq' in row || 'moq_unit' in row;
}

function applyFilters(rows, options = {}) {
  const dateField = options.dateField || "";
  return rows.filter(row => {
    if (filters.material.length > 0 && hasMaterial(row) && !filters.material.some(mat => matchesMaterial(row, mat))) return false;
    if (filters.supplier.length > 0 && hasSupplier(row) && !filters.supplier.some(sup => matchesSupplier(row, sup))) return false;
    if (filters.category.length > 0 && 'category' in row && !filters.category.includes(String(row.category || ""))) return false;
    if (filters.alertType.length > 0 && 'alert_type' in row && !filters.alertType.includes(String(row.alert_type || ""))) return false;
    if (filters.creditStatus.length > 0 && 'credit_status' in row && !filters.creditStatus.includes(String(row.credit_status || ""))) return false;
    if (filters.moqStatus.length > 0 && hasMoq(row) && !filters.moqStatus.includes(moqStatus(row))) return false;
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

const filterDefinitions = {
  material: { label: "All materials", optionId: "filterMaterialOptions" },
  supplier: { label: "All suppliers", optionId: "filterSupplierOptions" },
  category: { label: "All categories", optionId: "filterCategoryOptions" },
  alertType: { label: "All alert types", optionId: "filterAlertTypeOptions" },
  creditStatus: { label: "All credit statuses", optionId: "filterCreditStatusOptions" },
  moqStatus: { label: "All MOQ statuses", optionId: "filterMoqStatusOptions" }
};

const filterLabels = {
  material: "Material",
  supplier: "Supplier",
  category: "Category",
  alertType: "Alert type",
  creditStatus: "Credit status",
  moqStatus: "MOQ status",
  dateFrom: "Date from",
  dateTo: "Date to"
};

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

  setDropdownOptions("material", materialIds, filterDefinitions.material.label);
  setDropdownOptions("supplier", supplierNames, filterDefinitions.supplier.label);
  setDropdownOptions("category", categories, filterDefinitions.category.label);
  setDropdownOptions("alertType", alertTypes, filterDefinitions.alertType.label);
  setDropdownOptions("creditStatus", creditStatuses, filterDefinitions.creditStatus.label);
  setDropdownOptions(
    "moqStatus",
    new Set(["meets_moq", "below_moq", "not_applicable"]),
    filterDefinitions.moqStatus.label
  );
}

function setDropdownOptions(key, values, allLabel) {
  const container = document.getElementById(filterDefinitions[key].optionId);
  const selectedSet = new Set(filters[key] || []);
  const sorted = Array.from(values).sort();
  container.innerHTML = sorted.map(value => `
    <label class="filter-option">
      <input type="checkbox" value="${escapeHtml(value)}" data-filter="${key}" ${selectedSet.has(value) ? "checked" : ""}>
      <span>${escapeHtml(value)}</span>
    </label>
  `).join("");
  updateFilterDropdownLabel(key, allLabel);
}

function updateFilterDropdownLabel(key, allLabel) {
  const button = document.querySelector(`.filter-dropdown[data-filter="${key}"] .filter-toggle .filter-toggle-text`);
  if (!button) return;
  const values = filters[key] || [];
  if (!values.length) {
    button.textContent = allLabel;
  } else if (values.length <= 3) {
    button.textContent = values.join(", ");
  } else {
    button.textContent = `${values.length} selected`;
  }
  const toggle = button.closest(".filter-toggle");
  if (toggle) {
    toggle.classList.toggle("active", values.length > 0);
  }
}

function applyChartFilter(key, value) {
  if (!filters[key]) filters[key] = [];
  if (!filters[key].includes(value)) {
    filters[key].push(value);
  }
  
  const container = document.getElementById(filterDefinitions[key]?.optionId);
  if (container) {
    const checkbox = container.querySelector(`input[value="${escapeHtml(value)}"]`);
    if (checkbox) checkbox.checked = true;
  }
  
  updateFilterDropdownLabel(key, filterDefinitions[key]?.label);
  renderSelectedFilterSummary();
  renderAll();
  
  const filterBar = document.getElementById("filterBar");
  if (filterBar && filterBar.classList.contains("collapsed")) {
    const collapseToggle = document.getElementById("filterCollapseToggle");
    if (collapseToggle) collapseToggle.click();
  }
}

function bindFilters() {
  const dateFields = ["filterDateFrom", "filterDateTo"];
  const filterBar = document.getElementById("filterBar");
  const collapseToggle = document.getElementById("filterCollapseToggle");

  collapseToggle?.addEventListener("click", () => {
    const collapsed = filterBar.classList.toggle("collapsed");
    closeAllDropdowns();
    collapseToggle.setAttribute("aria-expanded", String(!collapsed));
    collapseToggle.textContent = collapsed ? "Edit filters" : "Hide filters";
  });

  filterBar.addEventListener("click", event => {
    if (event.target.closest("#filterCollapseToggle")) return;
    if (event.target.closest(".selected-filter-chip")) {
      const chip = event.target.closest(".selected-filter-chip");
      const key = chip?.dataset.key;
      const value = chip?.dataset.value;
      if (!key || !value) return;
      removeFilterValue(key, value);
      return;
    }

    const dropdown = event.target.closest(".filter-dropdown");
    if (!dropdown) return;
    const opened = dropdown.classList.contains("open");
    closeAllDropdowns();
    if (!opened) {
      dropdown.classList.add("open");
      const toggle = dropdown.querySelector(".filter-toggle");
      if (toggle) toggle.setAttribute("aria-expanded", "true");
    }
  });

  document.addEventListener("click", event => {
    if (!event.target.closest(".filter-dropdown")) {
      closeAllDropdowns();
    }
  });

  filterBar.addEventListener("change", event => {
    const checkbox = event.target.closest("input[type='checkbox']");
    if (!checkbox) return;
    const key = checkbox.dataset.filter;
    syncFilterValues(key);
    renderSelectedFilterSummary();
    renderAll();
  });

  filterBar.addEventListener("input", event => {
    const search = event.target.closest("input[data-search]");
    if (!search) return;
    const key = search.dataset.search;
    const query = search.value.toLowerCase();
    const options = document.querySelectorAll(`.filter-dropdown[data-filter="${key}"] .filter-option`);
    options.forEach(option => {
      const label = option.textContent.toLowerCase();
      option.style.display = label.includes(query) ? "flex" : "none";
    });
  });

  dateFields.forEach(id => {
    const element = document.getElementById(id);
    element.addEventListener("change", () => {
      filters[id === "filterDateFrom" ? "dateFrom" : "dateTo"] = element.value;
      renderSelectedFilterSummary();
      renderAll();
    });
  });

  document.getElementById("filterReset").addEventListener("click", () => {
    Object.assign(filters, {
      material: [],
      supplier: [],
      category: [],
      alertType: [],
      creditStatus: [],
      moqStatus: [],
      dateFrom: "",
      dateTo: ""
    });

    Object.values(filterDefinitions).forEach(def => {
      const container = document.getElementById(def.optionId);
      container.querySelectorAll("input[type=checkbox]").forEach(input => input.checked = false);
      const key = Object.keys(filterDefinitions).find(k => filterDefinitions[k].optionId === def.optionId);
      if (key) updateFilterDropdownLabel(key, def.label);
    });

    dateFields.forEach(id => {
      const element = document.getElementById(id);
      if (element) element.value = "";
    });

    renderSelectedFilterSummary();
    renderAll();
  });
}

function syncFilterValues(key) {
  const container = document.getElementById(filterDefinitions[key].optionId);
  filters[key] = Array.from(container.querySelectorAll("input[type=checkbox]:checked")).map(input => input.value);
  updateFilterDropdownLabel(key, filterDefinitions[key].label);
}



function removeFilterValue(key, value) {
  if (Array.isArray(filters[key])) {
    filters[key] = filters[key].filter(item => item !== value);
    const container = document.getElementById(filterDefinitions[key]?.optionId);
    if (container) {
      const input = container.querySelector(`input[type='checkbox'][value="${CSS.escape(value)}"]`);
      if (input) input.checked = false;
    }
    updateFilterDropdownLabel(key, filterDefinitions[key].label);
  } else if (key === "dateFrom" || key === "dateTo") {
    filters[key] = "";
    const input = document.getElementById(key === "dateFrom" ? "filterDateFrom" : "filterDateTo");
    if (input) input.value = "";
  }
  renderSelectedFilterSummary();
  renderAll();
}

function renderSelectedFilterSummary() {
  const chipContainer = document.getElementById("selectedFilterChips");
  const summaryMeta = document.getElementById("filterSummaryMeta");
  if (!chipContainer || !summaryMeta) return;

  const chips = [];

  Object.entries(filterDefinitions).forEach(([key]) => {
    (filters[key] || []).forEach(value => {
      chips.push({ key, label: `${filterLabels[key]}: ${value}`, value });
    });
  });

  if (filters.dateFrom) {
    chips.push({ key: "dateFrom", label: `${filterLabels.dateFrom}: ${filters.dateFrom}`, value: filters.dateFrom });
  }
  if (filters.dateTo) {
    chips.push({ key: "dateTo", label: `${filterLabels.dateTo}: ${filters.dateTo}`, value: filters.dateTo });
  }

  if (!chips.length) {
    chipContainer.innerHTML = `<span class="filter-empty-chip">No active filters</span>`;
    summaryMeta.textContent = "No filters applied";
    return;
  }

  chipContainer.innerHTML = chips.map(chip => `
    <button class="selected-filter-chip" type="button" data-key="${escapeHtml(chip.key)}" data-value="${escapeHtml(chip.value)}" title="Remove ${escapeHtml(chip.label)}">
      <span>${escapeHtml(chip.label)}</span>
      <span aria-hidden="true">×</span>
    </button>
  `).join("");
  summaryMeta.textContent = `${chips.length} active filter${chips.length === 1 ? "" : "s"}`;
}
function closeAllDropdowns() {
  document.querySelectorAll(".filter-dropdown.open").forEach(dropdown => {
    dropdown.classList.remove("open");
    const toggle = dropdown.querySelector(".filter-toggle");
    if (toggle) toggle.setAttribute("aria-expanded", "false");
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

const tabFilters = {
  decision: ["material", "supplier", "category", "alertType", "creditStatus", "moqStatus", "dateFrom", "dateTo"],
  demand: ["material", "category", "dateFrom", "dateTo"],
  inventory: ["material", "category", "alertType"],
  risk: ["material", "supplier", "category"],
  forecast: ["material", "category"],
  procurement: ["material", "supplier", "category", "creditStatus", "moqStatus", "dateFrom", "dateTo"],
  recommendations: ["material", "category", "alertType"],
  simulation: [],
  quality: ["material", "category"]
};

function updateVisibleFilters(tab) {
  const allowed = tabFilters[tab] || [];
  
  const filterBar = document.getElementById('filterBar');
  if (filterBar) {
    filterBar.style.display = allowed.length === 0 ? 'none' : '';
  }

  document.querySelectorAll('.filter-dropdown').forEach(dropdown => {
    const filterType = dropdown.dataset.filter;
    const group = dropdown.closest('.filter-group');
    if (group) {
      group.style.display = allowed.includes(filterType) ? '' : 'none';
    }
  });

  const dateFrom = document.getElementById('filterDateFrom');
  if (dateFrom) {
    const group = dateFrom.closest('.filter-group');
    if (group) group.style.display = allowed.includes('dateFrom') ? '' : 'none';
  }
  
  const dateTo = document.getElementById('filterDateTo');
  if (dateTo) {
    const group = dateTo.closest('.filter-group');
    if (group) group.style.display = allowed.includes('dateTo') ? '' : 'none';
  }
  renderSelectedFilterSummary();
}

document.querySelectorAll(".nav-item").forEach(button => {
  button.addEventListener("click", () => {
    document.querySelectorAll(".nav-item").forEach(item => item.classList.remove("active"));
    document.querySelectorAll(".tab-panel").forEach(panel => panel.classList.remove("active"));
    button.classList.add("active");
    document.getElementById(`tab-${button.dataset.tab}`).classList.add("active");
    document.querySelector(".topbar h1").textContent = button.textContent;
    updateVisibleFilters(button.dataset.tab);
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
  const overrideEmail = document.getElementById("overrideEmailInput")?.value.trim();
  const payload = overrideEmail ? { recipients: [overrideEmail] } : {};
  
  try {
    const response = await api("/api/send-alerts", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    });
    if (response.ok) {
      status.textContent = "Sent";
      const sent = (response.sentRoles || []).join(", ") || "none";
      const skipped = (response.skippedRoles || []).map(item => `${item.role}: ${item.reason}`).join("; ");
      log.textContent = `Sent role alerts: ${sent}.${skipped ? ` Skipped: ${skipped}.` : ""}`;
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

document.getElementById("sendDailyReportButton").addEventListener("click", async () => {
  const button = document.getElementById("sendDailyReportButton");
  const status = document.getElementById("emailStatus");
  const log = document.getElementById("emailLog");
  button.disabled = true;
  button.textContent = "Sending";
  status.textContent = "Sending report";
  const overrideEmail = document.getElementById("overrideEmailInput")?.value.trim();
  const payload = overrideEmail ? { recipients: [overrideEmail] } : {};

  try {
    const response = await api("/api/send-daily-report", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    });
    if (response.ok) {
      status.textContent = "Report sent";
      log.textContent = `Daily report sent to ${response.recipients.join(", ")}.`;
    } else {
      status.textContent = "Failed";
      log.textContent = response.error === "missing_email_settings"
        ? `Missing settings: ${response.missing.join(", ")}.`
        : `Report send failed: ${response.detail || response.error}`;
    }
  } catch (error) {
    status.textContent = "Failed";
    log.textContent = error.message;
  } finally {
    button.disabled = false;
    button.textContent = "Send daily report";
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
const activeTab = document.querySelector(".nav-item.active")?.dataset.tab || "decision";
updateVisibleFilters(activeTab);

window.openMaterial360 = function(materialId) {
  const panel = document.getElementById("material360Panel");
  if (!panel) return;
  
  let name = "Unknown Material";
  let unit = "";
  const row = (state.inventory?.coverage || []).find(r => r.material_id === materialId);
  if (row) {
    name = row.material_name;
    unit = row.unit;
  }
  
  document.getElementById("m360Title").textContent = `${materialId} · ${name}`;
  
  const currentStock = row?.current_stock || 0;
  const demand21d = row?.total_demand_21d || 0;
  const daysToStockout = row?.days_to_stockout || "-";
  
  document.getElementById("m360Kpis").innerHTML = `
    <div class="kpi"><span>Stock</span><strong>${qty(currentStock, unit)}</strong></div>
    <div class="kpi"><span>21D Demand</span><strong>${qty(demand21d, unit)}</strong></div>
    <div class="kpi"><span>Days Cover</span><strong>${daysToStockout}</strong></div>
  `;
  
  const approved = (state.procurement?.approved || []).filter(r => r.material_id === materialId);
  const blocked = (state.procurement?.blocked || []).filter(r => r.material_id === materialId);
  
  const suppliers = new Map();
  approved.forEach(r => {
    const s = suppliers.get(r.supplier_name) || { name: r.supplier_name, app: 0, blk: 0 };
    s.app += Number(r.recommended_value_inr || 0);
    suppliers.set(r.supplier_name, s);
  });
  blocked.forEach(r => {
    const s = suppliers.get(r.supplier_name) || { name: r.supplier_name, app: 0, blk: 0 };
    s.blk += Number(r.recommended_value_inr || 0);
    suppliers.set(r.supplier_name, s);
  });
  
  document.getElementById("m360Supplier").innerHTML = Array.from(suppliers.values()).map(s => `
    <tr><td>${escapeHtml(s.name)}</td><td>${inr(s.app)}</td><td>${inr(s.blk)}</td></tr>
  `).join("") || "<tr><td colspan='3' class='muted'>No supplier exposure</td></tr>";
  
  const alerts = (state.inventory?.alerts || []).filter(r => r.material_id === materialId);
  document.getElementById("m360Alerts").innerHTML = alerts.map(a => `
    <div class="alert-item">
      <span>${escapeHtml(a.first_stockout_date || "No date")} · Shortage ${qty(a.projected_shortage_qty, a.unit)}</span>
      <span>${statusPill(a.alert_type)}</span>
    </div>
  `).join("") || "<span class='muted'>No active alerts</span>";
  
  const bom = (state.demand?.bomTraceSample || []).filter(r => r.material_id === materialId);
  document.getElementById("m360Bom").innerHTML = bom.map(b => `
    <tr><td>${escapeHtml(b.order_id)}</td><td>${qty(b.seasonal_required_qty)}</td><td>${escapeHtml(b.delivery_date)}</td></tr>
  `).join("") || "<tr><td colspan='3' class='muted'>No BOM dependencies</td></tr>";
  
  panel.classList.add("open");
  panel.setAttribute("aria-hidden", "false");
}

window.closeMaterial360 = function() {
  const panel = document.getElementById("material360Panel");
  if (panel) {
    panel.classList.remove("open");
    panel.setAttribute("aria-hidden", "true");
  }
}

window.openSupplier360 = function(supplierName, event) {
  if (event) event.stopPropagation();
  const panel = document.getElementById("supplier360Panel");
  if (!panel) return;
  
  document.getElementById("s360Title").textContent = `${supplierName}`;
  
  const approved = (state.procurement?.approved || []).filter(r => r.supplier_name === supplierName);
  const blocked = (state.procurement?.blocked || []).filter(r => r.supplier_name === supplierName);
  
  let totalApproved = 0;
  let totalBlocked = 0;
  const materials = new Map();
  
  approved.forEach(r => {
    const m = materials.get(r.material_id) || { name: r.material_name, app: 0, blk: 0 };
    m.app += Number(r.recommended_value_inr || 0);
    totalApproved += Number(r.recommended_value_inr || 0);
    materials.set(r.material_id, m);
  });
  blocked.forEach(r => {
    const m = materials.get(r.material_id) || { name: r.material_name, app: 0, blk: 0 };
    m.blk += Number(r.recommended_value_inr || 0);
    totalBlocked += Number(r.recommended_value_inr || 0);
    materials.set(r.material_id, m);
  });
  
  const riskRows = state.risk?.supplierRisks || [];
  const riskData = riskRows.find(r => r.supplier_name === supplierName);
  const reliability = riskData?.reliability_score || "-";
  
  document.getElementById("s360Kpis").innerHTML = `
    <div class="kpi"><span>Approved POs</span><strong>${inr(totalApproved)}</strong></div>
    <div class="kpi"><span>Blocked Need</span><strong style="color: #ef4444">${inr(totalBlocked)}</strong></div>
    <div class="kpi"><span>Reliability Score</span><strong>${reliability}</strong></div>
  `;
  
  document.getElementById("s360Materials").innerHTML = Array.from(materials.entries()).map(([id, m]) => `
    <tr class="clickable-row" onclick="openMaterial360('${escapeHtml(id)}')">
      <td>${escapeHtml(id)} · ${escapeHtml(m.name)}</td>
      <td>${inr(m.app)}</td>
      <td>${inr(m.blk)}</td>
    </tr>
  `).join("") || "<tr><td colspan='3' class='muted'>No active exposure</td></tr>";
  
  panel.classList.add("open");
  panel.setAttribute("aria-hidden", "false");
}

window.closeSupplier360 = function() {
  const panel = document.getElementById("supplier360Panel");
  if (panel) {
    panel.classList.remove("open");
    panel.setAttribute("aria-hidden", "true");
  }
}

window.dismissAlert = function(materialId, event) {
  if (event) event.stopPropagation();
  if (state.inventory && state.inventory.alerts) {
    state.inventory.alerts = state.inventory.alerts.filter(a => a.material_id !== materialId);
    renderAlertCenter();
    renderOverview();
  }
}

window.simulateRecommendation = async function(materialId) {
  const recs = state.recommendations?.recommendations || [];
  const rec = recs.find(r => r.material_id === materialId);
  if (!rec) return;
  
  // Switch to Simulation Lab tab
  const simTab = document.querySelector('.nav-item[data-tab="simulation"]');
  if (simTab) simTab.click();
  
  // Reset form first
  resetScenarioForm();
  
  // Auto-fill ALL parameters based on the recommendation context
  const action = (rec.recommended_action || "").toLowerCase();
  const simName = document.getElementById('sim-name');
  if (simName) simName.value = `AI: ${rec.recommended_action} (${rec.material_id})`;
  
  if (action.includes("expedite") || action.includes("air freight") || action.includes("fast-track")) {
    const sd = document.getElementById('sim-supplier-delay');
    if (sd) sd.value = -7;
  } else if (action.includes("delay") || action.includes("lead time")) {
    const sd = document.getElementById('sim-supplier-delay');
    if (sd) sd.value = 14;
  }
  
  if (action.includes("credit") || action.includes("budget")) {
    const cr = document.getElementById('sim-credit-reduction');
    if (cr) cr.value = 0.3;
  }
  
  if (action.includes("demand") || action.includes("spike") || action.includes("surge")) {
    const ds = document.getElementById('sim-demand-spike');
    if (ds) ds.value = 0.5;
  }
  
  if (action.includes("shrink") || action.includes("wastage") || action.includes("safety stock")) {
    const sh = document.getElementById('sim-shrinkage');
    if (sh) sh.value = 0.1;
  }
  
  if (action.includes("approv")) {
    const ad = document.getElementById('sim-approval-delay');
    if (ad) ad.value = 7;
  }
  
  // Auto-run the simulation immediately
  await runScenario();
}

document.addEventListener("DOMContentLoaded", () => {
  document.body.addEventListener("click", e => {
    if (e.target.closest("#m360Close")) closeMaterial360();
    if (e.target.closest("#s360Close")) closeSupplier360();
  });
});
