from __future__ import annotations

import math
from typing import Iterable

import pandas as pd

from .config import PipelineConfig
from .load_data import explode_supplier_materials, latest_capital_snapshot


def compute_material_risk_scores(
    coverage_summary: pd.DataFrame,
    supplier_master: pd.DataFrame,
    daily_material_demand: pd.DataFrame,
    procurement_recommendations: pd.DataFrame,
    blocked_by_credit: pd.DataFrame,
    substitutions: pd.DataFrame,
    working_capital_log: pd.DataFrame,
    normalized_transactions: pd.DataFrame,
    analysis_date: pd.Timestamp,
    config: PipelineConfig,
) -> pd.DataFrame:
    """Compute unified, explainable risk scores per material."""
    if coverage_summary.empty:
        return pd.DataFrame(
            columns=[
                "material_id",
                "material_name",
                "category",
                "unit",
                "risk_score",
                "severity",
                "risk_probability",
                "confidence",
                "contributing_factors",
                "explanation",
                "mitigation_suggestions",
            ]
        )

    base = coverage_summary.copy()
    base["days_to_stockout"] = pd.to_numeric(base["days_to_stockout"], errors="coerce")
    base["days_of_cover"] = pd.to_numeric(base["days_of_cover"], errors="coerce")

    supplier_stats = _supplier_stats(supplier_master)
    demand_stats = _demand_volatility(daily_material_demand)
    stockout_stats = _stockout_frequency(normalized_transactions, analysis_date)
    procurement_stats = _procurement_feasibility(procurement_recommendations)
    credit_blocks = set(blocked_by_credit.get("material_id", pd.Series(dtype=str)).dropna())
    missing_supplier_blocks = set(
        blocked_by_credit[
            blocked_by_credit.get("credit_status", pd.Series(dtype=str)).eq("blocked_missing_supplier")
            | blocked_by_credit.get("blocked_reason", pd.Series(dtype=str)).fillna("").str.contains("missing", case=False)
        ].get("material_id", pd.Series(dtype=str))
    )
    substitute_availability = _substitute_availability(substitutions)

    capital = latest_capital_snapshot(working_capital_log)
    credit_utilized = _num(capital.get("credit_utilized_inr"))
    credit_cap = float(config.credit_cap_inr) if config.credit_cap_inr else 0.0
    utilization_pct = 0.0 if credit_cap <= 0 else min(1.0, credit_utilized / credit_cap)

    frame = base[[
        "material_id",
        "material_name",
        "category",
        "unit",
        "days_to_stockout",
        "days_of_cover",
        "projected_shortage_qty",
        "total_demand_21d",
        "substitute_material_ids",
    ]].copy()

    frame = frame.merge(supplier_stats, on="material_id", how="left")
    frame = frame.merge(demand_stats, on="material_id", how="left")
    frame = frame.merge(stockout_stats, on="material_id", how="left")
    frame = frame.merge(procurement_stats, on="material_id", how="left")
    frame["credit_blocked"] = frame["material_id"].isin(credit_blocks)
    frame["missing_supplier"] = frame["material_id"].isin(missing_supplier_blocks)
    frame["substitute_available"] = frame["material_id"].map(substitute_availability).fillna(False)

    frame["stockout_risk"] = _days_to_stockout_risk(frame["days_to_stockout"], config.alert_horizon_days)
    frame["stockout_risk"] = (
        0.7 * frame["stockout_risk"]
        + 0.3 * _normalize(frame["stockout_events"].fillna(0.0))
    )

    frame["demand_volatility_risk"] = _normalize(frame["volatility_cv"].fillna(0.0))

    frame["supplier_risk"] = _supplier_risk(frame["reliability_score"])

    lead_time_risk = _normalize(frame["lead_time_days"].fillna(0.0))
    lead_time_variability = _normalize(frame["lead_time_variability"].fillna(0.0))
    frame["lead_time_risk"] = 0.7 * lead_time_risk + 0.3 * lead_time_variability

    credit_risk = utilization_pct
    frame["credit_risk"] = frame["credit_blocked"].apply(lambda blocked: 1.0 if blocked else credit_risk)

    coverage_risk = _days_to_stockout_risk(frame["days_of_cover"], config.planning_window_days)
    frame["inventory_coverage_risk"] = coverage_risk

    frame["procurement_feasibility_risk"] = _procurement_risk(
        frame["procurement_gap_days"],
        frame["moq_friction"],
        frame["missing_supplier"],
    )

    frame["substitution_risk"] = frame["substitute_available"].apply(lambda available: 0.2 if available else 1.0)

    frame["risk_score"] = (
        frame["stockout_risk"] * 0.30
        + frame["demand_volatility_risk"] * 0.15
        + frame["supplier_risk"] * 0.15
        + frame["lead_time_risk"] * 0.10
        + frame["credit_risk"] * 0.10
        + frame["procurement_feasibility_risk"] * 0.10
        + frame["inventory_coverage_risk"] * 0.05
        + frame["substitution_risk"] * 0.05
    ) * 100

    frame["risk_score"] = frame["risk_score"].clip(lower=0, upper=100).round(2)
    frame["severity"] = frame["risk_score"].apply(_severity_band)
    frame["risk_probability"] = (frame["risk_score"] / 100).round(3)

    frame["confidence"] = frame.apply(_confidence_score, axis=1).round(3)
    frame["contributing_factors"] = frame.apply(_contributing_factors, axis=1)
    frame["explanation"] = frame.apply(_explanation, axis=1)
    frame["mitigation_suggestions"] = frame.apply(_mitigation, axis=1)

    return frame.sort_values(["risk_score", "days_to_stockout"], ascending=[False, True]).reset_index(drop=True)


def _supplier_stats(supplier_master: pd.DataFrame) -> pd.DataFrame:
    if supplier_master.empty:
        return pd.DataFrame(columns=["material_id", "reliability_score", "lead_time_days", "lead_time_variability"])
    exploded = explode_supplier_materials(supplier_master)
    if exploded.empty:
        return pd.DataFrame(columns=["material_id", "reliability_score", "lead_time_days", "lead_time_variability"])
    stats = (
        exploded.groupby("material_id", as_index=False)
        .agg(
            reliability_score=("reliability_score", "max"),
            lead_time_days=("lead_time_days", "mean"),
            lead_time_variability=("lead_time_days", "std"),
        )
        .fillna(0.0)
    )
    return stats


def _demand_volatility(daily_material_demand: pd.DataFrame) -> pd.DataFrame:
    if daily_material_demand.empty:
        return pd.DataFrame(columns=["material_id", "volatility_cv"])
    demand = daily_material_demand.copy()
    demand["seasonal_required_qty"] = pd.to_numeric(
        demand["seasonal_required_qty"], errors="coerce"
    ).fillna(0.0)
    stats = demand.groupby("material_id", as_index=False)["seasonal_required_qty"].agg(["mean", "std"])
    stats = stats.rename(columns={"mean": "demand_mean", "std": "demand_std"}).reset_index()
    stats["volatility_cv"] = stats.apply(
        lambda row: 0.0 if row["demand_mean"] <= 0 else row["demand_std"] / row["demand_mean"],
        axis=1,
    )
    return stats[["material_id", "volatility_cv"]]


def _stockout_frequency(
    normalized_transactions: pd.DataFrame, analysis_date: pd.Timestamp
) -> pd.DataFrame:
    if normalized_transactions.empty:
        return pd.DataFrame(columns=["material_id", "stockout_events"])
    tx = normalized_transactions.copy()
    tx["date"] = pd.to_datetime(tx["date"], errors="coerce")
    tx["transaction_type"] = tx["transaction_type"].astype(str).str.lower()
    recent = tx[tx["date"] >= analysis_date - pd.Timedelta(days=180)]
    stockout = recent[
        (recent["po_number"].fillna("") == "STOCKOUT-EVENT")
        | (recent["transaction_type"].isin({"stockout", "backorder"}))
    ]
    if stockout.empty:
        return pd.DataFrame(columns=["material_id", "stockout_events"])
    counts = stockout.groupby("material_id", as_index=False).size()
    counts = counts.rename(columns={"size": "stockout_events"})
    return counts


def _procurement_feasibility(procurement_recommendations: pd.DataFrame) -> pd.DataFrame:
    if procurement_recommendations.empty:
        return pd.DataFrame(
            columns=["material_id", "procurement_gap_days", "moq_friction", "missing_supplier"]
        )

    proc = procurement_recommendations.copy()
    proc["days_to_stockout"] = pd.to_numeric(proc["days_to_stockout"], errors="coerce")
    proc["lead_time_days"] = pd.to_numeric(proc["lead_time_days"], errors="coerce")
    proc["procurement_gap_days"] = proc["lead_time_days"] - proc["days_to_stockout"]
    proc["required_qty"] = pd.to_numeric(proc["required_qty"], errors="coerce").fillna(0.0)
    proc["recommended_full_qty"] = pd.to_numeric(proc["recommended_full_qty"], errors="coerce").fillna(0.0)
    proc["moq_friction"] = proc.apply(
        lambda row: 0.0
        if row["required_qty"] <= 0
        else max(0.0, row["recommended_full_qty"] / row["required_qty"] - 1.0),
        axis=1,
    )
    grouped = proc.groupby("material_id", as_index=False).agg(
        procurement_gap_days=("procurement_gap_days", "max"),
        moq_friction=("moq_friction", "max"),
    )
    grouped["missing_supplier"] = False
    return grouped


def _substitute_availability(substitutions: pd.DataFrame) -> dict[str, bool]:
    if substitutions.empty:
        return {}
    substitutes = substitutions.copy()
    substitutes["substitute_current_stock"] = pd.to_numeric(
        substitutes.get("substitute_current_stock", pd.Series(dtype=float)), errors="coerce"
    ).fillna(0.0)
    availability = (
        substitutes.groupby("source_material_id", as_index=True)["substitute_current_stock"]
        .max()
        .apply(lambda value: value > 0)
        .to_dict()
    )
    return availability


def _days_to_stockout_risk(series: pd.Series, horizon_days: int) -> pd.Series:
    days = pd.to_numeric(series, errors="coerce")
    risk = 1 - (days / float(horizon_days)).clip(lower=0, upper=1)
    return risk.fillna(0.0)


def _supplier_risk(series: pd.Series) -> pd.Series:
    values = pd.to_numeric(series, errors="coerce").fillna(0.0)
    scale = 1.0 if values.max() <= 1.5 else 100.0
    return (1 - (values / scale).clip(lower=0, upper=1)).fillna(1.0)


def _procurement_risk(
    gap_days: pd.Series, moq_friction: pd.Series, missing_supplier: pd.Series
) -> pd.Series:
    gap = pd.to_numeric(gap_days, errors="coerce").fillna(0.0)
    friction = pd.to_numeric(moq_friction, errors="coerce").fillna(0.0)
    missing = missing_supplier.fillna(False)
    base = _normalize(gap.clip(lower=0))
    friction_risk = _normalize(friction.clip(lower=0))
    risk = 0.7 * base + 0.3 * friction_risk
    risk = risk.where(~missing, 1.0)
    return risk


def _normalize(series: Iterable[float]) -> pd.Series:
    values = pd.to_numeric(pd.Series(series), errors="coerce").fillna(0.0)
    if values.empty:
        return values
    min_val = float(values.min())
    max_val = float(values.max())
    if math.isclose(max_val, min_val):
        return pd.Series([0.0] * len(values), index=values.index)
    return (values - min_val) / (max_val - min_val)


def _severity_band(score: float) -> str:
    if score <= 30:
        return "LOW"
    if score <= 60:
        return "MEDIUM"
    if score <= 80:
        return "HIGH"
    return "CRITICAL"


def _confidence_score(row: pd.Series) -> float:
    inputs = [
        row.get("days_to_stockout"),
        row.get("reliability_score"),
        row.get("lead_time_days"),
        row.get("volatility_cv"),
        row.get("procurement_gap_days"),
        row.get("moq_friction"),
    ]
    available = sum(1 for value in inputs if not _is_null(value))
    return 0.55 + 0.45 * (available / len(inputs))


def _contributing_factors(row: pd.Series) -> str:
    contributions = {
        "stockout_risk": row.get("stockout_risk", 0.0) * 0.30,
        "demand_volatility": row.get("demand_volatility_risk", 0.0) * 0.15,
        "supplier_risk": row.get("supplier_risk", 0.0) * 0.15,
        "lead_time_risk": row.get("lead_time_risk", 0.0) * 0.10,
        "credit_risk": row.get("credit_risk", 0.0) * 0.10,
        "procurement_feasibility": row.get("procurement_feasibility_risk", 0.0) * 0.10,
        "inventory_coverage": row.get("inventory_coverage_risk", 0.0) * 0.05,
        "substitution_risk": row.get("substitution_risk", 0.0) * 0.05,
    }
    top = sorted(contributions.items(), key=lambda item: item[1], reverse=True)[:3]
    return ", ".join(name.replace("_", " ") for name, _ in top if _ > 0)


def _explanation(row: pd.Series) -> str:
    factors = _contributing_factors(row)
    if not factors:
        return "Risk score driven by stable supply and low demand volatility."
    return f"Risk driven by {factors}."


def _mitigation(row: pd.Series) -> str:
    suggestions: list[str] = []
    if row.get("stockout_risk", 0) > 0.7:
        suggestions.append("expedite replenishment or reprioritize production")
    if row.get("supplier_risk", 0) > 0.6:
        suggestions.append("qualify alternate suppliers and split orders")
    if row.get("credit_risk", 0) > 0.6:
        suggestions.append("escalate credit release or rebalance procurement")
    if row.get("substitution_risk", 0) > 0.8:
        suggestions.append("identify substitute materials with approved specs")
    if not suggestions:
        suggestions.append("monitor and maintain current procurement cadence")
    return "; ".join(suggestions)


def _num(value: object) -> float:
    try:
        if value is None or pd.isna(value):
            return 0.0
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _is_null(value: object) -> bool:
    if value is None:
        return True
    try:
        return bool(pd.isna(value))
    except Exception:
        return False
