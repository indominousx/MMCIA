from __future__ import annotations

import math

import pandas as pd

from .config import PipelineConfig
from .load_data import explode_supplier_materials, latest_capital_snapshot


def build_procurement_recommendations(
    material_master: pd.DataFrame,
    supplier_master: pd.DataFrame,
    normalized_transactions: pd.DataFrame,
    daily_material_demand: pd.DataFrame,
    coverage_summary: pd.DataFrame,
    working_capital_log: pd.DataFrame,
    analysis_date: pd.Timestamp,
    config: PipelineConfig,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    supplier_materials = explode_supplier_materials(supplier_master)
    price_estimates = build_price_estimates(normalized_transactions, supplier_materials)
    demand_by_material_day = _demand_lookup(daily_material_demand)
    material_lookup = material_master.set_index("material_id").to_dict("index")

    candidates: list[dict[str, object]] = []
    risky_materials = coverage_summary[
        (coverage_summary["projected_shortage_qty"] > 0)
        | (coverage_summary["under_3_days_stock"])
        | (coverage_summary["stockout_within_21d"])
    ].copy()

    for coverage in risky_materials.itertuples(index=False):
        material_id = coverage.material_id
        material = material_lookup[material_id]
        eligible_suppliers = supplier_materials[supplier_materials["material_id"] == material_id].copy()
        if eligible_suppliers.empty:
            candidates.append(_missing_supplier_candidate(coverage, material))
            continue

        supplier_candidates: list[dict[str, object]] = []
        for supplier in eligible_suppliers.itertuples(index=False):
            supplier_horizon_days = max(
                config.forecast_horizon_days,
                int(supplier.lead_time_days) + config.alert_horizon_days,
            )
            supplier_horizon_days = min(supplier_horizon_days, config.planning_window_days)
            demand_until_horizon = _sum_demand_until(
                demand_by_material_day,
                material_id,
                analysis_date,
                supplier_horizon_days,
            )
            required_qty = max(
                0.0,
                demand_until_horizon
                + float(material["reorder_point_current"])
                - float(material["current_stock"]),
            )
            if required_qty <= 0 and float(coverage.projected_shortage_qty) <= 0:
                continue

            moq = float(supplier.moq)
            required_or_shortage = max(required_qty, float(coverage.projected_shortage_qty))
            recommended_full_qty = _round_up_to_moq(required_or_shortage, moq)
            price = _lookup_price(price_estimates, material_id, supplier.supplier_id)
            recommended_value = recommended_full_qty * price["estimated_unit_price_inr"]
            stockout_date = _parse_optional_date(coverage.first_stockout_date)
            can_arrive_before_stockout = (
                True
                if stockout_date is None
                else analysis_date + pd.Timedelta(days=int(supplier.lead_time_days)) <= stockout_date
            )
            order_by_date = (
                ""
                if stockout_date is None
                else (stockout_date - pd.Timedelta(days=int(supplier.lead_time_days))).date().isoformat()
            )
            action_timing = "immediate" if order_by_date and pd.Timestamp(order_by_date) <= analysis_date else "scheduled"

            supplier_candidates.append(
                {
                    "material_id": material_id,
                    "material_name": material["name"],
                    "unit": material["unit"],
                    "supplier_id": supplier.supplier_id,
                    "supplier_name": supplier.supplier_name,
                    "lead_time_days": int(supplier.lead_time_days),
                    "moq": moq,
                    "moq_unit": supplier.moq_unit,
                    "payment_terms_days": int(supplier.payment_terms_days),
                    "reliability_score": float(supplier.reliability_score),
                    "estimated_unit_price_inr": price["estimated_unit_price_inr"],
                    "price_source": price["price_source"],
                    "required_qty": required_qty,
                    "recommended_full_qty": recommended_full_qty,
                    "recommended_full_value_inr": recommended_value,
                    "first_stockout_date": coverage.first_stockout_date,
                    "days_to_stockout": coverage.days_to_stockout,
                    "projected_shortage_qty": coverage.projected_shortage_qty,
                    "demand_until_supplier_horizon": demand_until_horizon,
                    "can_arrive_before_stockout": can_arrive_before_stockout,
                    "order_by_date": order_by_date,
                    "action_timing": action_timing,
                    "rationale": _rationale(coverage),
                }
            )

        if supplier_candidates:
            chosen = sorted(
                supplier_candidates,
                key=lambda row: (
                    not row["can_arrive_before_stockout"],
                    -row["reliability_score"],
                    row["lead_time_days"],
                    row["estimated_unit_price_inr"],
                ),
            )[0]
            candidates.append(chosen)

    candidate_df = pd.DataFrame(candidates)
    if candidate_df.empty:
        return candidate_df, candidate_df.copy(), pd.DataFrame([_empty_credit_summary(config)])

    capital = latest_capital_snapshot(working_capital_log)
    baseline_outstanding = float(capital.get("outstanding_payables_inr", 0.0))
    baseline_utilized = float(capital.get("credit_utilized_inr", baseline_outstanding))
    cumulative_outstanding = baseline_outstanding
    cumulative_utilized = baseline_utilized

    approved_rows: list[dict[str, object]] = []
    blocked_rows: list[dict[str, object]] = []

    candidate_df = candidate_df.sort_values(
        by=["days_to_stockout", "projected_shortage_qty", "recommended_full_value_inr"],
        ascending=[True, False, False],
        na_position="last",
    )

    for candidate in candidate_df.to_dict("records"):
        if "missing_supplier" in candidate:
            blocked_rows.append(candidate)
            continue

        price = float(candidate["estimated_unit_price_inr"])
        moq = float(candidate["moq"])
        full_qty = float(candidate["recommended_full_qty"])
        full_value = full_qty * price
        available_by_outstanding = config.credit_cap_inr - cumulative_outstanding
        available_by_utilized = config.credit_cap_inr - cumulative_utilized
        max_available_credit = max(0.0, min(available_by_outstanding, available_by_utilized))

        if full_value <= max_available_credit:
            approved_qty = full_qty
            credit_status = "approved_full"
        else:
            affordable_blocks = math.floor(max_available_credit / (moq * price)) if price > 0 and moq > 0 else 0
            approved_qty = affordable_blocks * moq
            credit_status = "approved_partial_credit_limited" if approved_qty > 0 else "blocked_by_credit"

        if approved_qty > 0:
            approved_value = approved_qty * price
            cumulative_outstanding += approved_value
            cumulative_utilized += approved_value
            approved = candidate.copy()
            approved.update(
                {
                    "recommended_qty": approved_qty,
                    "recommended_value_inr": approved_value,
                    "unmet_qty_after_credit_gate": max(0.0, full_qty - approved_qty),
                    "baseline_outstanding_payables_inr": baseline_outstanding,
                    "baseline_credit_utilized_inr": baseline_utilized,
                    "projected_outstanding_after_line_inr": cumulative_outstanding,
                    "projected_credit_utilized_after_line_inr": cumulative_utilized,
                    "remaining_available_credit_inr": config.credit_cap_inr - cumulative_utilized,
                    "credit_status": credit_status,
                }
            )
            approved_rows.append(approved)

        if approved_qty < full_qty:
            blocked = candidate.copy()
            blocked.update(
                {
                    "recommended_qty": full_qty - approved_qty,
                    "recommended_value_inr": (full_qty - approved_qty) * price,
                    "baseline_outstanding_payables_inr": baseline_outstanding,
                    "baseline_credit_utilized_inr": baseline_utilized,
                    "projected_outstanding_after_line_inr": cumulative_outstanding + (full_qty - approved_qty) * price,
                    "projected_credit_utilized_after_line_inr": cumulative_utilized + (full_qty - approved_qty) * price,
                    "remaining_available_credit_inr": config.credit_cap_inr - cumulative_utilized,
                    "credit_status": "blocked_by_credit",
                    "blocked_reason": "insufficient credit for full MOQ-rounded requirement",
                }
            )
            blocked_rows.append(blocked)

    approved_df = _order_procurement_columns(pd.DataFrame(approved_rows))
    blocked_df = _order_procurement_columns(pd.DataFrame(blocked_rows))
    summary = pd.DataFrame(
        [
            {
                "credit_cap_inr": config.credit_cap_inr,
                "baseline_outstanding_payables_inr": baseline_outstanding,
                "baseline_credit_utilized_inr": baseline_utilized,
                "approved_po_value_inr": approved_df["recommended_value_inr"].sum()
                if not approved_df.empty
                else 0.0,
                "projected_outstanding_after_approved_inr": cumulative_outstanding,
                "projected_credit_utilized_after_approved_inr": cumulative_utilized,
                "remaining_available_credit_inr": config.credit_cap_inr - cumulative_utilized,
                "latest_capital_month": capital.get("month", ""),
                "credit_gate_rule": "approved only when projected outstanding and credit utilized stay within cap",
            }
        ]
    )
    return approved_df, blocked_df, summary


def build_price_estimates(
    normalized_transactions: pd.DataFrame, supplier_materials: pd.DataFrame
) -> pd.DataFrame:
    receipts = normalized_transactions[
        (normalized_transactions["transaction_type"] == "receipt")
        & (normalized_transactions["unit_price"] > 0)
        & normalized_transactions["supplier_id"].notna()
    ].copy()

    latest = (
        receipts.sort_values("date")
        .groupby(["material_id", "supplier_id"], as_index=False)
        .tail(1)[["material_id", "supplier_id", "unit_price", "date"]]
        .rename(columns={"unit_price": "latest_supplier_unit_price_inr", "date": "price_date"})
    )
    median = (
        receipts.groupby("material_id", as_index=False)["unit_price"]
        .median()
        .rename(columns={"unit_price": "material_median_unit_price_inr"})
    )
    prices = supplier_materials[["material_id", "supplier_id"]].drop_duplicates()
    prices = prices.merge(latest, on=["material_id", "supplier_id"], how="left")
    prices = prices.merge(median, on="material_id", how="left")
    prices["estimated_unit_price_inr"] = prices["latest_supplier_unit_price_inr"].fillna(
        prices["material_median_unit_price_inr"]
    )
    prices["price_source"] = prices["latest_supplier_unit_price_inr"].apply(
        lambda value: "latest_supplier_receipt" if pd.notna(value) else "fallback_material_median"
    )
    prices["estimated_unit_price_inr"] = prices["estimated_unit_price_inr"].fillna(0.0)
    return prices


def _demand_lookup(daily_material_demand: pd.DataFrame) -> dict[tuple[str, pd.Timestamp], float]:
    return {
        (row.material_id, pd.Timestamp(row.delivery_date).normalize()): float(row.seasonal_required_qty)
        for row in daily_material_demand.itertuples(index=False)
    }


def _sum_demand_until(
    demand_lookup: dict[tuple[str, pd.Timestamp], float],
    material_id: str,
    analysis_date: pd.Timestamp,
    horizon_days: int,
) -> float:
    horizon_end = analysis_date + pd.Timedelta(days=horizon_days)
    return sum(
        qty
        for (lookup_material, date), qty in demand_lookup.items()
        if lookup_material == material_id and analysis_date < date <= horizon_end
    )


def _lookup_price(price_estimates: pd.DataFrame, material_id: str, supplier_id: str) -> dict[str, object]:
    match = price_estimates[
        (price_estimates["material_id"] == material_id) & (price_estimates["supplier_id"] == supplier_id)
    ]
    if match.empty:
        return {"estimated_unit_price_inr": 0.0, "price_source": "missing_price"}
    row = match.iloc[0]
    return {
        "estimated_unit_price_inr": float(row["estimated_unit_price_inr"]),
        "price_source": row["price_source"],
    }


def _round_up_to_moq(quantity: float, moq: float) -> float:
    if moq <= 0:
        return quantity
    return math.ceil(quantity / moq) * moq


def _parse_optional_date(value: object) -> pd.Timestamp | None:
    if value is None or pd.isna(value) or str(value) == "":
        return None
    return pd.Timestamp(value).normalize()


def _rationale(coverage: object) -> str:
    if bool(coverage.under_3_days_stock):
        return "less than 3 days of scheduled stock cover"
    if bool(coverage.stockout_within_21d):
        return "projected stockout within 21 days"
    return "projected shortage in planning window"


def _missing_supplier_candidate(coverage: object, material: dict[str, object]) -> dict[str, object]:
    return {
        "material_id": coverage.material_id,
        "material_name": material["name"],
        "unit": material["unit"],
        "missing_supplier": True,
        "credit_status": "blocked_missing_supplier",
        "blocked_reason": "no supplier mapped to material",
    }


def _empty_credit_summary(config: PipelineConfig) -> dict[str, object]:
    return {
        "credit_cap_inr": config.credit_cap_inr,
        "approved_po_value_inr": 0.0,
        "remaining_available_credit_inr": config.credit_cap_inr,
    }


def _order_procurement_columns(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    preferred = [
        "supplier_id",
        "supplier_name",
        "material_id",
        "material_name",
        "recommended_qty",
        "unit",
        "moq",
        "moq_unit",
        "estimated_unit_price_inr",
        "recommended_value_inr",
        "required_qty",
        "recommended_full_qty",
        "unmet_qty_after_credit_gate",
        "lead_time_days",
        "order_by_date",
        "action_timing",
        "first_stockout_date",
        "days_to_stockout",
        "can_arrive_before_stockout",
        "reliability_score",
        "payment_terms_days",
        "baseline_outstanding_payables_inr",
        "baseline_credit_utilized_inr",
        "projected_outstanding_after_line_inr",
        "projected_credit_utilized_after_line_inr",
        "remaining_available_credit_inr",
        "credit_status",
        "blocked_reason",
        "price_source",
        "rationale",
    ]
    columns = [column for column in preferred if column in df.columns]
    columns += [column for column in df.columns if column not in columns]
    return df[columns]
