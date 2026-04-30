PS 02 - The Inventory Black Hole

**Domain:** Manufacturing

**Company:** PackRight Industries, Pune

**Scale:** 14 raw materials · 9 suppliers · ₹45-60L/month procurement spend

**Annual Impact:** ₹12L stuck in slow-moving stock · 3 production halts of 14-22 hours each last quarter

**Background**

PackRight Industries manufactures corrugated packaging boxes for FMCG clients including Dabur, HUL, and Parle. They source 14 raw materials - kraft paper rolls, adhesives, inks, starch, and strapping - from 9 suppliers.

They are simultaneously experiencing two opposite problems: ₹12L worth of slow-moving adhesive WF-200 and specialty gold ink is sitting in the warehouse tying up working capital, while critical Grade A kraft paper ran out 3 times last quarter, halting production for 14-22 hours each time. Both problems exist at the same time, in the same warehouse. The procurement manager orders based on 'what feels low.'

The critical constraint: PackRight has a ₹30L working capital credit line that cannot be exceeded at any point. This means naive over-ordering is not the answer.

**Problem Statement**

Build an AI inventory intelligence system that:

- Forecasts demand for each raw material based on production orders and seasonal patterns - BOM-aware
- Recommends what to order, how much, and when - within the ₹30L credit line cap
- Flags substitutable materials when primary stock runs critically low
- Generates an automated weekly purchase recommendation report a non-technical purchase manager can execute
- Flags any material with less than 3 days of stock based on upcoming committed production orders

**The BOM Challenge (Core Technical Requirement)**

The production_orders.csv file contains a material_bom JSON column. Example:

{"M01": 0.32, "M05": 0.22, "M06": 0.014, "M11": 0.003, "M13": 0.08}

This means one medium standard box consumes 0.32 rolls of Grade A kraft, 0.22 rolls of corrugating medium, 14g of adhesive, 3g of ink, and 0.08 rolls of strapping. Teams must parse this JSON, multiply by order quantity, and aggregate across all upcoming orders to compute total material demand. Generic time-series forecasting without BOM awareness will score significantly lower.

**Data Files Provided**

| **File Name**              | **~Rows** | **Key Fields**                                                                          | **Noise / Gotcha**                                                                  | **Demo Anchor**                                                                 |
| -------------------------- | --------- | --------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------- | ------------------------------------------------------------------------------- |
| inventory_transactions.csv | ~18,000   | date, material_id, transaction_type, quantity, unit, supplier_id, unit_price, po_number | Unit inconsistency: same material appears in kg, rolls, and pieces - must normalize | 3 STOCKOUT-EVENT entries for M01 (Grade A kraft) in Q4 2023                     |
| ---                        | ---       | ---                                                                                     | ---                                                                                 | ---                                                                             |
| production_orders.csv      | ~1,400    | order_id, client_id, product_type, quantity, delivery_date, material_bom (JSON)         | BOM is a JSON column - must parse to compute material demand                        | Upcoming orders with delivery_date in next 6 weeks are the forecast input       |
| ---                        | ---       | ---                                                                                     | ---                                                                                 | ---                                                                             |
| supplier_master.csv        | 9 rows    | supplier_id, lead_time_days, moq, moq_unit, payment_terms_days, reliability_score       | MOQs are non-negotiable - all recommendations must respect them                     | SUP06 (Siegwerk, gold ink) has 21-day lead time and 60-day payment terms        |
| ---                        | ---       | ---                                                                                     | ---                                                                                 | ---                                                                             |
| material_master.csv        | 14 rows   | material_id, name, current_stock, reorder_point_current, substitute_material_ids        | substitute_material_ids is comma-separated - must parse for substitution logic      | M01 (Grade A kraft) has substitute M02 (Grade B) - critical for stockout alerts |
| ---                        | ---       | ---                                                                                     | ---                                                                                 | ---                                                                             |
| working_capital_log.csv    | 24 rows   | month, credit_utilized_inr, outstanding_payables_inr, available_credit_inr              | Monthly snapshot - all recommendations must keep total outstanding below ₹30L       | Current available credit must be computed dynamically                           |
| ---                        | ---       | ---                                                                                     | ---                                                                                 | ---                                                                             |
| seasonal_index.csv         | 12 rows   | month, fmcg_demand_multiplier, notes                                                    | Simple reference table - Oct=1.35x, Nov=1.62x (Diwali), Jan=0.78x                   | Must be applied as a multiplier to BOM-computed demand                          |
| ---                        | ---       | ---                                                                                     | ---                                                                                 | ---                                                                             |

**Constraints**

- Any purchase recommendation must not push outstanding payables beyond ₹30L credit line - breaching this disqualifies the recommendation
- Minimum order quantities (MOQs) are non-negotiable - all order recommendations must be rounded up to the nearest MOQ
- Weekly report must be a formatted PDF or Excel that the purchase manager can email directly to suppliers
- Unit normalization is the team's problem - raw data has kg vs rolls vs pieces for the same material
- Must flag when any material has less than 3 days of stock based on scheduled production orders

**Deliverables**

- D1: Unit normalization pipeline with documented conversion logic per material
- D2: BOM-aware demand forecasting model with 4-week horizon per material
- D3: Procurement recommendation engine - credit-limit-aware, MOQ-respecting
- D4: Auto-generated weekly purchase report (PDF or formatted Excel) ready to email to suppliers
- D5: Stockout risk alert for the next 21 days based on current stock + upcoming production orders
- D6: Substitution alert - when M01 is low, recommend switching to M02 with supplier and quantity details

**Judging Criteria**

| **Weight** | **Focus Area**        | **What Judges Look For**                                                                                                                                                                                           |
| ---------- | --------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| **40%**    | BOM-aware forecasting | Generic time-series forecasting scores low. Teams must parse the material_bom JSON, compute total material demand across all upcoming orders, and only then apply seasonal adjustment. Show the calculation chain. |
| ---        | ---                   | ---                                                                                                                                                                                                                |
| **35%**    | Credit limit handling | Every recommendation must show the resulting outstanding payables balance. Any single recommendation that pushes balance past ₹30L is automatically disqualified - not penalised, disqualified.                    |
| ---        | ---                   | ---                                                                                                                                                                                                                |
| **25%**    | Weekly report quality | Can the purchase manager pick up this report and email it to suppliers without modification? Column clarity, supplier-wise grouping, and MOQ compliance all evaluated.                                             |
| ---        | ---                   | ---                                                                                                                                                                                                                |