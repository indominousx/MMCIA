const state = {
  overview: null,
  decision: null,
  demand: null,
  inventory: null,
  procurement: null,
  substitutions: null,
  quality: null,
  alertConfig: null
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
  const [overview, decision, demand, inventory, procurement, substitutions, quality, alertConfig] = await Promise.all([
    api("/api/overview"),
    api("/api/decision-dashboard"),
    api("/api/demand-planning"),
    api("/api/inventory-management"),
    api("/api/smart-procurement"),
    api("/api/substitutions"),
    api("/api/data-quality"),
    api("/api/alert-config")
  ]);
  Object.assign(state, { overview, decision, demand, inventory, procurement, substitutions, quality, alertConfig });
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
  renderSupplierExposure();
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

function renderAlertCenter() {
  const alerts = state.inventory.alerts || [];
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
  const recipients = (config.recipients || []).join(", ");
  const fromEmail = config.fromEmail || "Not configured";
  const missing = config.missing || [];
  const ready = Boolean(config.enabled);

  document.getElementById("emailRecipientsInput").value = recipients;
  document.getElementById("emailFrom").textContent = fromEmail;
  document.getElementById("emailStatus").textContent = ready ? "Ready" : `Missing ${missing.join(", ")}`;
  const sendButton = document.getElementById("sendAlertButton");
  sendButton.disabled = !ready;
  // We can always simulate, so no need to disable simulate button
}

function renderSupplierExposure() {
  const approved = state.procurement.approved || [];
  const blocked = state.procurement.blocked || [];
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
  const recipientsStr = document.getElementById("emailRecipientsInput").value;
  const customRecipients = recipientsStr.split(",").map(r => r.trim()).filter(r => r);

  button.disabled = true;
  button.textContent = "Sending";
  status.textContent = "Sending";
  try {
    const response = await api("/api/send-alerts", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ recipients: customRecipients.length > 0 ? customRecipients : undefined })
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

document.getElementById("simulateEmailButton")?.addEventListener("click", async () => {
  const button = document.getElementById("simulateEmailButton");
  const status = document.getElementById("emailStatus");
  const log = document.getElementById("emailLog");
  const recipientsStr = document.getElementById("emailRecipientsInput").value;
  const customRecipients = recipientsStr.split(",").map(r => r.trim()).filter(r => r);

  button.disabled = true;
  button.textContent = "Simulating";
  try {
    const response = await api("/api/send-alerts", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ 
        simulate: true, 
        recipients: customRecipients.length > 0 ? customRecipients : undefined 
      })
    });
    if (response.ok) {
      status.textContent = "Simulated";
      log.textContent = `Email simulation generated.`;
      showEmailSimulation(response);
    } else {
      status.textContent = "Failed";
      log.textContent = response.error;
    }
  } catch (error) {
    status.textContent = "Failed";
    log.textContent = error.message;
  } finally {
    button.disabled = false;
    button.textContent = "Simulate Email";
  }
});

function showEmailSimulation(data) {
  let modal = document.getElementById("emailSimulationModal");
  if (!modal) {
    modal = document.createElement("div");
    modal.id = "emailSimulationModal";
    modal.style.position = "fixed";
    modal.style.top = "0";
    modal.style.left = "0";
    modal.style.width = "100%";
    modal.style.height = "100%";
    modal.style.backgroundColor = "rgba(0,0,0,0.5)";
    modal.style.display = "flex";
    modal.style.justifyContent = "center";
    modal.style.alignItems = "center";
    modal.style.zIndex = "9999";
    
    const content = document.createElement("div");
    content.style.backgroundColor = "white";
    content.style.padding = "20px";
    content.style.borderRadius = "8px";
    content.style.maxWidth = "800px";
    content.style.width = "90%";
    content.style.maxHeight = "90%";
    content.style.overflow = "hidden";
    content.style.display = "flex";
    content.style.flexDirection = "column";
    
    const header = document.createElement("div");
    header.style.display = "flex";
    header.style.justifyContent = "space-between";
    header.style.alignItems = "center";
    header.style.marginBottom = "10px";
    
    const title = document.createElement("h2");
    title.textContent = "Simulated Email";
    title.style.margin = "0";
    
    const closeBtn = document.createElement("button");
    closeBtn.textContent = "Close";
    closeBtn.className = "button secondary";
    closeBtn.onclick = () => modal.style.display = "none";
    
    header.appendChild(title);
    header.appendChild(closeBtn);
    
    const subject = document.createElement("h3");
    subject.id = "emailSimulationSubject";
    subject.style.margin = "0 0 10px 0";
    
    const iframe = document.createElement("iframe");
    iframe.id = "emailSimulationIframe";
    iframe.style.width = "100%";
    iframe.style.flexGrow = "1";
    iframe.style.border = "1px solid #ccc";
    iframe.style.minHeight = "400px";
    
    content.appendChild(header);
    content.appendChild(subject);
    content.appendChild(iframe);
    modal.appendChild(content);
    document.body.appendChild(modal);
  }
  
  document.getElementById("emailSimulationSubject").textContent = "Subject: " + data.subject;
  const iframe = document.getElementById("emailSimulationIframe");
  iframe.srcdoc = data.html;
  modal.style.display = "flex";
}

document.getElementById("bomSearch").addEventListener("input", renderBomRows);
document.getElementById("inventorySearch").addEventListener("input", renderInventoryCards);

loadAll().catch(error => {
  setRefreshState("Error");
  document.querySelector(".workspace").insertAdjacentHTML(
    "afterbegin",
    `<div class="panel"><strong>Application error</strong><p>${escapeHtml(error.message)}</p></div>`
  );
});
