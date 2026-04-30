# Data Quality Report

## Data Facts

- analysis_date: 2024-01-01
- inventory_rows: 18003
- inventory_min_date: 2022-01-01
- inventory_max_date: 2024-01-01
- production_order_rows: 1400
- delivery_min_date: 2022-01-18
- delivery_max_date: 2024-02-12
- latest_order_date: 2024-01-01
- latest_capital_month: 2023-11
- latest_credit_utilized_inr: 2175977.0
- latest_outstanding_payables_inr: 1414385.0
- latest_available_credit_inr: 824023.0

## Issues

- warning | working_capital_log.csv | duplicate_months_keep_last_file_occurrence: 2022-01, 2022-05
- warning | working_capital_log.csv | capital_snapshot_trails_analysis_date: latest=2023-11, analysis_date=2024-01-01
- info | inventory_transactions.csv | stockout_event_markers: 3 rows use po_number=STOCKOUT-EVENT
