# PS 02 - The Inventory Black Hole Execution Plan

Date revised: 2026-04-30

## 1) Goal
Build an inventory intelligence pipeline for PackRight Industries that converts committed production orders into raw-material demand, detects near-term stock risk, and produces supplier-ready purchase recommendations without breaching the INR 30,00,000 working-capital cap.

The plan is optimized around the judging weights:
- 40%: BOM-aware forecasting, with a visible calculation chain from order to material demand.
- 35%: credit-limit handling, with projected payable balance shown for every recommended line.
- 25%: weekly report quality, grouped by supplier and ready for a purchase manager to send.

## 2) Operating Definitions
- Credit cap: INR 3,000,000.
- Analysis date: use a configurable `analysis_date`; default to the latest `production_orders.order_date`, which is 2024-01-01 in this dataset. Do not use the system date because the dataset is historical.
- Forecast horizon for D2: 4 weeks from `analysis_date`.
- Operational lookahead: 6 weeks from `analysis_date`, matching the problem statement's "upcoming orders" demo anchor.
- Stockout alert horizon for D5: 21 days from `analysis_date`.
- Critical low-stock threshold: less than 3 days of stock based on scheduled production demand.
- Canonical unit: `material_master.unit`.
- Purchase value timing: conservatively treat the full recommended PO value as increasing payable exposure at approval time; also record supplier payment terms and due date for reporting.

## 3) Data Inputs and Known Gotchas

| File | Role | Required handling |
| --- | --- | --- |
| `inventory_transactions.csv` | Historical receipts/issues/returns/writeoffs and price history | Normalize units; estimate prices from latest valid receipts; detect M01 stockout events as `po_number = STOCKOUT-EVENT` on zero-quantity writeoff rows. |
| `production_orders.csv` | Committed future demand | Parse `material_bom` JSON, multiply by order quantity, apply seasonality by delivery month. |
| `material_master.csv` | Current stock, canonical units, substitutes | Use `current_stock` as starting inventory; parse comma-separated `substitute_material_ids`. |
| `supplier_master.csv` | Supplier, MOQ, lead time, reliability | Parse comma-separated `material_supplied`; rank supplier options by feasibility, reliability, lead time, and price. |
| `working_capital_log.csv` | Credit baseline | Resolve duplicate months (`2022-01`, `2022-05`) deterministically; use latest snapshot for baseline and log the mismatch if latest capital month trails `analysis_date`. |
| `seasonal_index.csv` | Monthly demand multiplier | Join by delivery month after BOM demand is calculated. |

Current data facts already verified:
- `production_orders.csv`: 1,400 rows, delivery range 2022-01-18 to 2024-02-12, latest order date 2024-01-01.
- `inventory_transactions.csv`: 18,003 rows, date range 2022-01-01 to 2024-01-01.
- `working_capital_log.csv`: 24 rows, latest month 2023-11. Latest snapshot shows `credit_utilized_inr = 2,175,977`, `outstanding_payables_inr = 1,414,385`, `available_credit_inr = 824,023`.

## 4) Build Phases

### Phase A - Configuration, Schema QA, and Data Profiling
Purpose: make the pipeline reproducible and catch disqualifying data issues early.

Tasks:
- Define configurable values: `analysis_date`, credit cap, forecast horizon, alert horizon, and output directory.
- Validate required columns, datatypes, nonnegative quantities, valid dates, and valid material/supplier IDs.
- Parse BOM JSON for every production order and fail loudly on invalid JSON.
- Confirm every material appearing in a BOM exists in `material_master`.
- Confirm every purchasable material has at least one supplier in `supplier_master`.
- Detect duplicate working-capital months; keep the last file occurrence for duplicated months and document the rule.
- Detect embedded stockout events using `po_number = STOCKOUT-EVENT`, not `transaction_type`.

Outputs:
- `outputs/data_quality_report.md`
- `outputs/data_quality_issues.csv`

### Phase B - Unit Normalization (D1)
Purpose: ensure demand, stock, MOQ, and prices are compared in the same unit.

Canonical rules:
- Use `material_master.unit` as the target unit per material.
- For kg materials: normalize `KG`, `kg`, `kgs`, and `kilograms` to `kg`.
- For roll materials: normalize `roll` and `rolls` to `rolls`.
- For roll materials recorded as `pcs` or `nos`, apply a documented 1 piece/nos = 1 roll assumption only if no better conversion factor exists; flag these rows as low-confidence conversions.
- Do not silently convert between unrelated physical units. Any unsupported unit pair goes to an exception file.
- Verify BOM quantities are already expressed in canonical material units; if not, normalize them with the same conversion table.

Outputs:
- `outputs/normalized_transactions.csv`
- `outputs/unit_conversion_logic.csv`
- `outputs/unit_conversion_exceptions.csv`

### Phase C - BOM-Aware Demand Forecast (D2)
Purpose: score strongly on the core technical requirement by showing the full calculation chain.

Demand calculation:
1. Filter production orders where `delivery_date > analysis_date` and `delivery_date <= analysis_date + 42 days` for the planning window.
2. Explode each `material_bom` JSON into one row per order-material pair.
3. Compute raw demand:
   `raw_required_qty = order_quantity * bom_qty_per_finished_box`
4. Join `seasonal_index` by delivery month.
5. Compute adjusted demand:
   `seasonal_required_qty = raw_required_qty * fmcg_demand_multiplier`
6. Aggregate to daily and weekly demand by `material_id`.
7. Produce the official 4-week forecast from `analysis_date` through `analysis_date + 28 days`.

Required trace columns:
- `order_id`
- `client_id`
- `product_type`
- `box_size`
- `delivery_date`
- `material_id`
- `bom_qty_per_box`
- `order_quantity`
- `raw_required_qty`
- `seasonal_multiplier`
- `seasonal_required_qty`
- `canonical_unit`

Outputs:
- `outputs/bom_exploded_order_demand.csv`
- `outputs/daily_material_demand.csv`
- `outputs/weekly_material_demand_4w.csv`

### Phase D - Inventory Projection and Stockout Alerts (D5)
Purpose: translate forecast demand into operational risk.

Tasks:
- Start from `material_master.current_stock`.
- Subtract scheduled daily demand in delivery-date order.
- Calculate `projected_stock_after_demand` for every material and day.
- Calculate days of cover using upcoming scheduled demand, not historical averages.
- Flag materials with less than 3 days of cover.
- Flag materials projected to hit zero within 21 days.
- Include the first risk date, demand causing the breach, and whether a substitute exists.
- Compare results to historical M01 `STOCKOUT-EVENT` rows as a sanity check for known risk patterns.

Outputs:
- `outputs/inventory_projection_daily.csv`
- `outputs/stockout_alerts_21d.csv`

### Phase E - Procurement Recommendation Engine (D3)
Purpose: recommend what to buy, how much, when, and from whom while respecting MOQ and credit limits.

Recommendation logic:
- For each material with a projected shortage or less than 3 days of cover, compute required replenishment through the longer of:
  - the 4-week forecast horizon, or
  - supplier lead time plus the 21-day alert horizon.
- Use `reorder_point_current` as a secondary buffer, not as the primary demand signal.
- Build eligible suppliers by parsing `supplier_master.material_supplied`.
- Rank suppliers by:
  1. Can arrive before projected stockout.
  2. Higher `reliability_score`.
  3. Shorter `lead_time_days`.
  4. Lower latest valid receipt price for that material-supplier pair.
- Estimate unit price from latest valid receipt for material-supplier; fallback to material median receipt price and mark `price_source = fallback_median`.
- Round recommended quantity up to the supplier MOQ in `moq_unit`.
- Compute `recommended_value_inr = recommended_qty * estimated_unit_price`.
- Compute `order_by_date = projected_stockout_date - lead_time_days`; if this is before `analysis_date`, mark as `immediate`.

Credit gate:
- Sort candidate recommendations by risk severity: already below zero, stockout within 21 days, less than 3 days cover, then highest forecast demand.
- For each line, calculate:
  - `baseline_outstanding_payables_inr`
  - `recommended_value_inr`
  - `projected_outstanding_after_line_inr`
  - `projected_credit_utilized_after_line_inr`
  - `remaining_available_credit_inr`
- Approve a line only if it does not push projected exposure above INR 3,000,000.
- If a needed line fails the gate, do not hide it. Mark it as `blocked_by_credit` with the shortage impact and possible substitute/partial-order option.

Outputs:
- `outputs/procurement_recommendations.csv`
- `outputs/procurement_blocked_by_credit.csv`

### Phase F - Substitution Recommendations (D6)
Purpose: give the purchase manager an executable backup when a primary material is critically low.

Minimum required behavior:
- Explicitly handle M01 Grade A kraft paper switching to M02 Grade B when M01 is below 3 days of cover or cannot be replenished before stockout.
- Include supplier, MOQ-rounded substitute quantity, lead time, price estimate, and credit impact.
- Preserve a risk note that substitution may require production/client approval.

Generalized behavior:
- Also evaluate other substitutes listed in `material_master.substitute_material_ids`, such as M06/M07 and M13/M14.
- Recommend substitution only when substitute stock or supplier availability materially reduces risk.

Outputs:
- `outputs/substitution_recommendations.csv`

### Phase G - Slow-Moving / Do-Not-Buy Watchlist
Purpose: address the business background about cash stuck in adhesive WF-200 and specialty gold ink, without distracting from the judged deliverables.

Tasks:
- Calculate 4-week demand versus current stock.
- Flag materials with high stock and low or zero near-term forecast demand.
- Highlight M06 Adhesive WF-200 and M12 Specialty Ink - Gold if coverage is excessive.
- Include this as an advisory tab in the weekly report so the manager avoids adding to already-stuck inventory.

Outputs:
- `outputs/slow_moving_watchlist.csv`

### Phase H - Weekly Supplier-Ready Report (D4)
Purpose: produce a report a non-technical purchase manager can act on immediately.

Preferred format: formatted Excel workbook. Optional PDF export can be generated from the workbook if time allows.

Workbook tabs:
- `Executive Summary`: total approved PO value, remaining credit, blocked critical needs, top 5 risk materials.
- `Supplier PO Plan`: grouped by supplier, with one clean order table per supplier.
- `Immediate Actions`: lines requiring action today.
- `Stockout Alerts`: 21-day risks and less-than-3-days risks.
- `Substitutions`: M01 to M02 and other substitute options.
- `BOM Demand Trace`: sample or full calculation chain for judge auditability.
- `Slow Moving Watchlist`: materials to avoid ordering.
- `Data Quality Notes`: assumptions, conversion exceptions, and credit snapshot caveats.

Supplier PO Plan columns:
- `supplier_id`
- `supplier_name`
- `material_id`
- `material_name`
- `recommended_qty`
- `unit`
- `moq`
- `lead_time_days`
- `order_by_date`
- `estimated_unit_price_inr`
- `line_value_inr`
- `projected_outstanding_after_line_inr`
- `credit_status`
- `rationale`

Outputs:
- `outputs/weekly_purchase_report.xlsx`
- Optional: `outputs/weekly_purchase_report.pdf`

## 5) Validation Checklist
- BOM math: sample orders can be traced from JSON quantity to material demand.
- Seasonality: October/November demand increases after applying multipliers; January demand decreases.
- Units: no recommendation mixes kg, rolls, pcs, and nos without documented conversion.
- MOQ: every approved recommendation is an exact multiple of supplier MOQ.
- Supplier mapping: every recommendation uses a supplier that actually supplies that material.
- Lead time: every line shows whether it can arrive before projected stockout.
- Credit: every approved line shows projected payable/credit exposure and stays within INR 3,000,000.
- Alerts: all materials under 3 days cover and all 21-day stockouts appear in the report.
- Substitution: M01-to-M02 case is explicitly present when M01 is critical.
- Report usability: supplier-wise grouping is clear enough to email without editing.

## 6) Suggested Implementation Structure
- `src/config.py`: constants and `analysis_date`.
- `src/load_data.py`: CSV loading and schema checks.
- `src/unit_normalization.py`: conversion rules and exception handling.
- `src/bom_forecast.py`: BOM parsing, explosion, seasonality, weekly forecast.
- `src/inventory_projection.py`: daily stock projection and alert generation.
- `src/procurement_engine.py`: supplier selection, MOQ rounding, credit gating.
- `src/substitution.py`: substitute recommendations.
- `src/reporting.py`: Excel/PDF generation.
- `run_pipeline.py`: end-to-end runner.

## 7) Deliverables Mapping
- D1: `normalized_transactions.csv`, `unit_conversion_logic.csv`, `unit_conversion_exceptions.csv`
- D2: `bom_exploded_order_demand.csv`, `weekly_material_demand_4w.csv`
- D3: `procurement_recommendations.csv`, `procurement_blocked_by_credit.csv`
- D4: `weekly_purchase_report.xlsx` and optional PDF
- D5: `stockout_alerts_21d.csv`, `inventory_projection_daily.csv`
- D6: `substitution_recommendations.csv`

## 8) Assumptions to Document in the Final Submission
- `analysis_date` defaults to 2024-01-01 because that is the latest order date in the dataset.
- `material_master.current_stock` is treated as the stock snapshot at `analysis_date`.
- Latest working-capital snapshot is 2023-11, so credit baseline is the latest available snapshot, not a same-day finance snapshot.
- The full recommended PO value is counted against credit exposure immediately.
- `pcs` and `nos` for roll-based materials are treated as 1:1 with rolls only as a documented cleanup assumption; exceptions remain visible.
- Historical prices are used as future price estimates where supplier quotes are unavailable.

## 9) Execution Checklist
- [ ] Configure `analysis_date`, horizons, and credit cap.
- [ ] Load all CSVs and generate data quality report.
- [ ] Build and apply unit normalization rules.
- [ ] Parse and explode `material_bom` JSON.
- [ ] Apply seasonal multipliers after BOM demand calculation.
- [ ] Generate daily and weekly material demand forecasts.
- [ ] Project inventory depletion from current stock.
- [ ] Generate less-than-3-days and 21-day stockout alerts.
- [ ] Build supplier-material mapping and price estimates.
- [ ] Generate MOQ-compliant procurement candidates.
- [ ] Apply sequential credit gate and separate blocked lines.
- [ ] Generate M01-to-M02 substitution recommendation when triggered.
- [ ] Generate slow-moving watchlist.
- [ ] Build formatted supplier-ready Excel report.
- [ ] Run validation checklist and finalize outputs.
