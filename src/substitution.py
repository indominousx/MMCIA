from __future__ import annotations

import math

import pandas as pd

from .config import PipelineConfig
from .load_data import explode_supplier_materials, latest_capital_snapshot
from .procurement_engine import build_price_estimates


def build_substitution_recommendations(
    material_master: pd.DataFrame,
    supplier_master: pd.DataFrame,
    normalized_transactions: pd.DataFrame,
    coverage_summary: pd.DataFrame,
    working_capital_log: pd.DataFrame,
    analysis_date: pd.Timestamp,
    config: PipelineConfig,
) -> pd.DataFrame:
    material_lookup = material_master.set_index("material_id").to_dict("index")
    supplier_materials = explode_supplier_materials(supplier_master)
    price_estimates = build_price_estimates(normalized_transactions, supplier_materials)
    capital = latest_capital_snapshot(working_capital_log)
    baseline_outstanding = float(capital.get("outstanding_payables_inr", 0.0))
    baseline_utilized = float(capital.get("credit_utilized_inr", baseline_outstanding))

    rows: list[dict[str, object]] = []
    alerts = coverage_summary[
        (coverage_summary["under_3_days_stock"]) | (coverage_summary["stockout_within_21d"])
    ]
    for source in alerts.itertuples(index=False):
        substitutes = _parse_substitutes(source.substitute_material_ids)
        if source.material_id == "M01" and "M02" not in substitutes:
            substitutes.append("M02")

        for substitute_id in substitutes:
            if substitute_id not in material_lookup:
                continue
            substitute = material_lookup[substitute_id]
            supplier_options = supplier_materials[supplier_materials["material_id"] == substitute_id].copy()
            if supplier_options.empty:
                rows.append(
                    {
                        "source_material_id": source.material_id,
                        "source_material_name": source.material_name,
                        "substitute_material_id": substitute_id,
                        "substitute_material_name": substitute["name"],
                        "recommendation_type": "substitute",
                        "credit_status": "blocked_missing_supplier",
                        "risk_note": "substitute has no mapped supplier; production/client approval still required",
                    }
                )
                continue

            supplier_options = supplier_options.sort_values(
                ["reliability_score", "lead_time_days"], ascending=[False, True]
            )
            supplier = supplier_options.iloc[0]
            price_row = price_estimates[
                (price_estimates["material_id"] == substitute_id)
                & (price_estimates["supplier_id"] == supplier["supplier_id"])
            ]
            price = 0.0 if price_row.empty else float(price_row.iloc[0]["estimated_unit_price_inr"])
            price_source = "missing_price" if price_row.empty else price_row.iloc[0]["price_source"]
            moq = float(supplier["moq"])
            required_qty = max(float(source.projected_shortage_qty), float(source.total_demand_21d) - float(source.current_stock))
            purchase_qty = math.ceil(max(required_qty, moq) / moq) * moq if moq > 0 else required_qty
            line_value = purchase_qty * price
            projected_outstanding = baseline_outstanding + line_value
            projected_utilized = baseline_utilized + line_value
            credit_status = (
                "credit_safe_if_ordered_standalone"
                if projected_outstanding <= config.credit_cap_inr
                and projected_utilized <= config.credit_cap_inr
                else "would_exceed_credit_if_ordered_standalone"
            )
            available_substitute_stock = float(substitute["current_stock"])

            rows.append(
                {
                    "source_material_id": source.material_id,
                    "source_material_name": source.material_name,
                    "source_first_stockout_date": source.first_stockout_date,
                    "source_days_to_stockout": source.days_to_stockout,
                    "substitute_material_id": substitute_id,
                    "substitute_material_name": substitute["name"],
                    "substitute_current_stock": available_substitute_stock,
                    "supplier_id": supplier["supplier_id"],
                    "supplier_name": supplier["supplier_name"],
                    "lead_time_days": int(supplier["lead_time_days"]),
                    "moq": moq,
                    "unit": substitute["unit"],
                    "recommended_purchase_qty": purchase_qty,
                    "estimated_unit_price_inr": price,
                    "recommended_value_inr": line_value,
                    "projected_outstanding_if_ordered_inr": projected_outstanding,
                    "projected_credit_utilized_if_ordered_inr": projected_utilized,
                    "credit_status": credit_status,
                    "price_source": price_source,
                    "risk_note": "requires production/client approval before substitution",
                }
            )

    return pd.DataFrame(rows)


def _parse_substitutes(value: object) -> list[str]:
    if pd.isna(value) or str(value).strip() == "":
        return []
    return [item.strip() for item in str(value).split(",") if item.strip()]
