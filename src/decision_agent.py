from __future__ import annotations

import pandas as pd

import math

from .config import PipelineConfig
from .load_data import explode_supplier_materials, latest_capital_snapshot


def build_ai_recommendations(
    coverage_summary: pd.DataFrame,
    risk_scores: pd.DataFrame,
    procurement_recommendations: pd.DataFrame,
    blocked_by_credit: pd.DataFrame,
    substitutions: pd.DataFrame,
    supplier_master: pd.DataFrame,
    working_capital_log: pd.DataFrame,
    analysis_date: pd.Timestamp,
    config: PipelineConfig,
) -> pd.DataFrame:
    """Convert analytical outputs into explainable operational decisions."""
    if coverage_summary.empty:
        return pd.DataFrame(
            columns=[
                "material_id",
                "material_name",
                "issue_detected",
                "business_impact",
                "recommended_action",
                "urgency",
                "confidence_score",
                "reasoning",
                "estimated_loss_prevented",
                "operational_priority",
            ]
        )

    risk_map = risk_scores.set_index("material_id").to_dict("index") if not risk_scores.empty else {}
    blocked_set = set(blocked_by_credit.get("material_id", pd.Series(dtype=str)).dropna())
    price_map = _material_price(procurement_recommendations)
    substitutes = _substitute_lookup(substitutions)
    supplier_options = _supplier_options(supplier_master)
    capital = latest_capital_snapshot(working_capital_log)
    credit_utilized = _num(capital.get("credit_utilized_inr"))
    credit_cap = float(config.credit_cap_inr) if config.credit_cap_inr else 0.0
    credit_pressure = 0.0 if credit_cap <= 0 else credit_utilized / credit_cap

    rows: list[dict[str, object]] = []
    for coverage in coverage_summary.itertuples(index=False):
        material_id = str(coverage.material_id)
        risk = risk_map.get(material_id, {})
        days_to_stockout = _optional_float(coverage.days_to_stockout)
        is_blocked = material_id in blocked_set
        has_substitute = substitutes.get(material_id, False)
        supplier_info = supplier_options.get(material_id, {})
        reliability_raw = _num(supplier_info.get("best_reliability"))
        reliability = reliability_raw / 100 if reliability_raw > 1.5 else reliability_raw
        alternate_suppliers = _num(supplier_info.get("supplier_count")) > 1
        lead_time = _num(supplier_info.get("lead_time_days"))
        estimated_loss = _num(coverage.projected_shortage_qty) * price_map.get(material_id, 0.0)

        issue_flags: list[str] = []
        actions: list[str] = []
        reasoning: list[str] = []

        if days_to_stockout is not None and days_to_stockout <= config.alert_horizon_days:
            issue_flags.append("imminent_stockout")
            reasoning.append("projected stockout inside planning horizon")

        if is_blocked:
            issue_flags.append("credit_blocked")
            reasoning.append("procurement blocked by credit cap")

        if reliability and reliability < 0.7:
            issue_flags.append("supplier_reliability_risk")
            reasoning.append("supplier reliability below threshold")

        if has_substitute:
            issue_flags.append("substitute_available")

        if days_to_stockout is not None and lead_time and days_to_stockout < lead_time and has_substitute:
            actions.append("trigger approved substitute and update production plan")
        elif days_to_stockout is not None and lead_time and days_to_stockout < lead_time:
            actions.append("expedite procurement or air freight critical materials")
        elif is_blocked:
            actions.append("escalate credit release and prioritize highest impact items")
        elif reliability and reliability < 0.7 and alternate_suppliers:
            actions.append("split order across alternate suppliers to de-risk")
        elif risk.get("severity") in {"HIGH", "CRITICAL"}:
            actions.append("pre-position safety stock and accelerate ordering")
        else:
            actions.append("monitor demand and maintain current procurement cadence")

        business_impact = (
            "production stoppage risk"
            if days_to_stockout is not None and days_to_stockout <= 7
            else "service level risk"
        )
        urgency = _urgency(risk.get("severity", "LOW"), days_to_stockout)
        confidence = _confidence_score(risk.get("confidence"), credit_pressure, has_substitute)

        rows.append(
            {
                "material_id": material_id,
                "material_name": coverage.material_name,
                "issue_detected": ", ".join(issue_flags) or "monitor",
                "business_impact": business_impact,
                "recommended_action": "; ".join(actions),
                "urgency": urgency,
                "confidence_score": confidence,
                "reasoning": "; ".join(reasoning) or "steady-state supply posture",
                "estimated_loss_prevented": round(estimated_loss, 2),
                "operational_priority": 0,
                "risk_score": risk.get("risk_score", 0.0),
                "severity": risk.get("severity", "LOW"),
                "days_to_stockout": coverage.days_to_stockout,
                "credit_pressure": round(credit_pressure, 3),
            }
        )

    recommendations = pd.DataFrame(rows)
    if recommendations.empty:
        return recommendations

    recommendations = recommendations.sort_values(
        ["risk_score", "days_to_stockout"], ascending=[False, True]
    ).reset_index(drop=True)
    recommendations["operational_priority"] = range(1, len(recommendations) + 1)
    return recommendations


def _material_price(procurement_recommendations: pd.DataFrame) -> dict[str, float]:
    if procurement_recommendations.empty:
        return {}
    prices = procurement_recommendations.copy()
    prices["estimated_unit_price_inr"] = pd.to_numeric(
        prices["estimated_unit_price_inr"], errors="coerce"
    ).fillna(0.0)
    price_map = prices.groupby("material_id", as_index=True)["estimated_unit_price_inr"].median().to_dict()
    return {str(key): float(value) for key, value in price_map.items()}


def _substitute_lookup(substitutions: pd.DataFrame) -> dict[str, bool]:
    if substitutions.empty:
        return {}
    substitutions = substitutions.copy()
    substitutions["substitute_current_stock"] = pd.to_numeric(
        substitutions.get("substitute_current_stock", pd.Series(dtype=float)), errors="coerce"
    ).fillna(0.0)
    lookup = (
        substitutions.groupby("source_material_id", as_index=True)["substitute_current_stock"]
        .max()
        .apply(lambda value: value > 0)
        .to_dict()
    )
    return {str(key): bool(value) for key, value in lookup.items()}


def _supplier_options(supplier_master: pd.DataFrame) -> dict[str, dict[str, object]]:
    if supplier_master.empty:
        return {}
    exploded = explode_supplier_materials(supplier_master)
    if exploded.empty:
        return {}
    stats = (
        exploded.groupby("material_id", as_index=False)
        .agg(
            supplier_count=("supplier_id", "nunique"),
            best_reliability=("reliability_score", "max"),
            lead_time_days=("lead_time_days", "mean"),
        )
        .fillna(0.0)
    )
    raw = stats.set_index("material_id").to_dict("index")
    return {str(key): {str(k): v for k, v in value.items()} for key, value in raw.items()}


def _urgency(severity: str, days_to_stockout: float | None) -> str:
    if severity == "CRITICAL" or (days_to_stockout is not None and days_to_stockout <= 3):
        return "CRITICAL"
    if severity == "HIGH" or (days_to_stockout is not None and days_to_stockout <= 7):
        return "HIGH"
    if severity == "MEDIUM":
        return "MEDIUM"
    return "LOW"


def _confidence_score(base: object, credit_pressure: float, has_substitute: bool) -> float:
    base_score = _num(base) if base is not None else 0.6
    adjustment = 0.05 if has_substitute else -0.05
    adjustment -= min(0.1, credit_pressure * 0.1)
    return float(max(0.4, min(0.95, base_score + adjustment)))


def _optional_float(value: object) -> float | None:
    if _is_null(value):
        return None
    try:
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            return float(value)
        return None
    except (TypeError, ValueError):
        return None


def _num(value: object) -> float:
    if _is_null(value):
        return 0.0
    try:
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            return float(value)
        return 0.0
    except (TypeError, ValueError):
        return 0.0


def _is_null(value: object) -> bool:
    if value is None or value is pd.NA:
        return True
    if isinstance(value, float):
        return math.isnan(value)
    return False
