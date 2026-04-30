# PS 02 - Inventory Intelligence Execution Plan

Date: 2026-04-30

## 1) Objective
Build an AI inventory intelligence system that is BOM-aware, seasonal-aware, and credit-limit-aware. The system must produce actionable procurement recommendations, low-stock alerts, and substitution guidance, packaged as a weekly supplier-ready report.

## 2) Constraints and Success Criteria
- Credit line cap: total outstanding payables must stay <= INR 3,000,000 after each recommendation.
- MOQ compliance: all recommended quantities must be rounded up to supplier MOQs and units.
- BOM-aware demand: demand derived from production orders by parsing material_bom JSON.
- Seasonality: apply monthly multipliers to BOM demand based on delivery_date month.
- Alerts: <3 days of stock and 21-day stockout risk.
- Report: supplier-wise weekly purchase report in Excel or PDF.

## 3) Inputs and Key Fields
- inventory_transactions.csv: date, material_id, transaction_type, quantity, unit, supplier_id, unit_price, po_number
- production_orders.csv: order_id, quantity, delivery_date, material_bom (JSON)
- material_master.csv: material_id, unit, current_stock, reorder_point_current, substitute_material_ids
- supplier_master.csv: supplier_id, material_supplied, lead_time_days, moq, moq_unit, payment_terms_days
- seasonal_index.csv: month, fmcg_demand_multiplier
- working_capital_log.csv: credit_utilized_inr, outstanding_payables_inr, available_credit_inr

## 4) Execution Phases

### Phase A: Data Profiling and QA
- Validate schemas, datatypes, and date ranges.
- Identify unit inconsistencies and build a unit normalization map.
- Detect duplicates and gaps (working_capital_log has duplicate months).
- Output: data profiling summary and known data issues list.

### Phase B: Unit Normalization (D1)
- Standardize units per material to material_master.unit.
- Define conversion logic per material (e.g., kg vs KG vs kilograms, rolls vs Rolls).
- Apply to inventory_transactions and any BOM quantities if needed.
- Output: normalized_transactions dataset and a conversion logic table.

### Phase C: BOM-Aware Demand Calculation (D2)
- Parse material_bom JSON to per-order material quantities.
- Multiply by order quantity to get raw material demand per order.
- Aggregate by material_id and week (or day) for the 4-week horizon.
- Apply seasonal multiplier based on delivery_date month.
- Output: weekly material demand forecast by material_id.

### Phase D: Inventory Position and Coverage
- Calculate available stock from material_master.current_stock.
- Derive net requirements = forecast demand minus available stock.
- Compute days of stock on hand using demand rate for next 21 days.
- Output: coverage metrics and stockout risk flags.

### Phase E: Procurement Recommendation Engine (D3)
- For each material with net shortage, compute order quantity:
  - Respect lead_time_days (order must arrive before projected stockout).
  - Round up to MOQ and correct unit.
  - Price estimate using last known unit_price (from receipts).
- Credit check: simulate impact on outstanding payables and ensure <= INR 3,000,000.
- Output: recommended PO lines with rationale and post-order credit utilization.

### Phase F: Substitution Logic (D6)
- If material has substitute_material_ids and primary stock is below threshold:
  - Propose substitute material with supplier and MOQ-compliant quantity.
  - Flag as substitution recommendation with risk notes.
- Output: substitution recommendations.

### Phase G: Alerts (D5)
- Alert 1: materials with <3 days of stock.
- Alert 2: materials projected to stock out within 21 days.
- Output: alert list with material_id, days of coverage, and risk window.

### Phase H: Weekly Purchase Report (D4)
- Supplier-wise grouping of recommendations.
- Include lead time, MOQ, unit, price estimate, total value, and credit impact.
- Export to Excel (preferred) and optionally PDF.
- Output: ready-to-email report.

## 5) Validation and QA
- BOM sanity checks: total demand per order matches expected per box size.
- Seasonality check: peak months (Oct-Nov) show higher demand.
- MOQ and unit compliance: no fractional MOQ violations.
- Credit constraint: each recommendation must be within the cap.

## 6) Deliverables Mapping
- D1: Unit normalization pipeline + conversion logic table
- D2: BOM-aware demand forecast (4-week horizon)
- D3: Credit-aware, MOQ-compliant procurement recommendations
- D4: Weekly supplier-ready report (Excel/PDF)
- D5: Stockout risk alerts for next 21 days
- D6: Substitution alerts for low stock materials

## 7) Suggested Output Artifacts
- outputs/normalized_transactions.csv
- outputs/weekly_material_demand.csv
- outputs/procurement_recommendations.csv
- outputs/stockout_alerts.csv
- outputs/substitution_alerts.csv
- outputs/weekly_purchase_report.xlsx

## 8) Assumptions
- Historical receipts include unit_price used as proxy for future pricing.
- Working capital snapshot uses most recent month as current baseline.
- Upcoming orders within 6 weeks drive near-term demand forecast.

## 9) Implementation Checklist
- [ ] Load and profile all input files
- [ ] Build unit normalization map and apply
- [ ] Parse BOM JSON and compute per-order demand
- [ ] Apply seasonal multipliers
- [ ] Aggregate to weekly demand by material
- [ ] Compute coverage and stockout risk
- [ ] Generate procurement recommendations with MOQ and credit checks
- [ ] Generate substitution recommendations
- [ ] Produce weekly report in Excel/PDF
- [ ] Run validations and finalize outputs
