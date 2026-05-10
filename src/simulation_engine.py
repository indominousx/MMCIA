from __future__ import annotations

import pandas as pd

from .config import PipelineConfig


DEFAULT_SCENARIOS = [
    {
        "scenario": "Demand spike 40%",
        "demand_spike": 0.4,
        "supplier_delay_days": 0,
        "credit_reduction": 0.0,
        "inventory_shrinkage": 0.0,
        "approval_delay_days": 0,
    },
    {
        "scenario": "Supplier delay 7d",
        "demand_spike": 0.0,
        "supplier_delay_days": 7,
        "credit_reduction": 0.0,
        "inventory_shrinkage": 0.0,
        "approval_delay_days": 0,
    },
    {
        "scenario": "Supplier failure 30%",
        "demand_spike": 0.1,
        "supplier_delay_days": 10,
        "credit_reduction": 0.0,
        "inventory_shrinkage": 0.0,
        "approval_delay_days": 0,
    },
    {
        "scenario": "Credit reduction 20%",
        "demand_spike": 0.0,
        "supplier_delay_days": 0,
        "credit_reduction": 0.2,
        "inventory_shrinkage": 0.0,
        "approval_delay_days": 0,
    },
    {
        "scenario": "Inventory shrinkage 10%",
        "demand_spike": 0.0,
        "supplier_delay_days": 0,
        "credit_reduction": 0.0,
        "inventory_shrinkage": 0.1,
        "approval_delay_days": 0,
    },
    {
        "scenario": "Seasonal surge 30%",
        "demand_spike": 0.3,
        "supplier_delay_days": 0,
        "credit_reduction": 0.0,
        "inventory_shrinkage": 0.0,
        "approval_delay_days": 0,
    },
    {
        "scenario": "Delayed approvals 7d",
        "demand_spike": 0.0,
        "supplier_delay_days": 0,
        "credit_reduction": 0.0,
        "inventory_shrinkage": 0.0,
        "approval_delay_days": 7,
    },
]


def run_scenario_simulations(
    coverage_summary: pd.DataFrame,
    daily_material_demand: pd.DataFrame,
    procurement_recommendations: pd.DataFrame,
    supplier_master: pd.DataFrame,
    risk_scores: pd.DataFrame,
    analysis_date: pd.Timestamp,
    config: PipelineConfig,
    scenarios: list[dict[str, object]] | None = None,
) -> pd.DataFrame:
    """Simulate disruption scenarios and quantify operational impact."""
    baseline = _baseline_metrics(coverage_summary, procurement_recommendations, risk_scores)
    avg_price = _average_price(procurement_recommendations)

    if scenarios is None:
        scenarios = DEFAULT_SCENARIOS

    rows: list[dict[str, object]] = []
    for scenario in scenarios:
        demand_spike = float(scenario["demand_spike"])
        supplier_delay = int(scenario["supplier_delay_days"])
        credit_reduction = float(scenario["credit_reduction"])
        shrinkage = float(scenario["inventory_shrinkage"])
        approval_delay = int(scenario["approval_delay_days"])

        stockouts = _simulate_stockouts(
            coverage_summary,
            config.alert_horizon_days,
            demand_spike,
            shrinkage,
        )
        delayed_orders = _simulate_delays(
            procurement_recommendations,
            supplier_delay + approval_delay,
        )

        shortage_qty = _num(coverage_summary.get("projected_shortage_qty", pd.Series(dtype=float)).sum())
        shortage_qty *= 1 + demand_spike + shrinkage
        simulated_losses = shortage_qty * avg_price

        credit_cap = config.credit_cap_inr * (1 - credit_reduction)
        procurement_value = baseline["baseline_procurement_value_inr"] * (1 + demand_spike - credit_reduction)
        procurement_value = max(0.0, procurement_value)

        risk_change_pct = 0.0
        if baseline["baseline_avg_risk_score"] > 0:
            risk_change_pct = (demand_spike * 0.7 + supplier_delay / 30 * 0.2 + credit_reduction * 0.2) * 100

        rows.append(
            {
                "scenario": scenario["scenario"],
                "demand_spike": demand_spike,
                "supplier_delay_days": supplier_delay,
                "credit_reduction": credit_reduction,
                "inventory_shrinkage": shrinkage,
                "approval_delay_days": approval_delay,
                "projected_stockouts": stockouts,
                "delayed_orders": delayed_orders,
                "simulated_losses_inr": round(simulated_losses, 2),
                "risk_change_pct": round(risk_change_pct, 2),
                "procurement_adjustment_inr": round(procurement_value, 2),
                "credit_cap_after_reduction_inr": round(credit_cap, 2),
                "baseline_stockouts": baseline["baseline_stockouts"],
                "baseline_procurement_value_inr": baseline["baseline_procurement_value_inr"],
                "baseline_avg_risk_score": baseline["baseline_avg_risk_score"],
                "scenario_summary": _scenario_summary(stockouts, delayed_orders, simulated_losses),
            }
        )

    return pd.DataFrame(rows)


def _baseline_metrics(
    coverage_summary: pd.DataFrame,
    procurement_recommendations: pd.DataFrame,
    risk_scores: pd.DataFrame,
) -> dict[str, float]:
    stockouts = int(
        _num(coverage_summary.get("stockout_within_21d", pd.Series(dtype=float)).sum())
    )
    procurement_value = _num(
        procurement_recommendations.get("recommended_value_inr", pd.Series(dtype=float)).sum()
    )
    avg_risk = _num(risk_scores.get("risk_score", pd.Series(dtype=float)).mean())
    return {
        "baseline_stockouts": stockouts,
        "baseline_procurement_value_inr": procurement_value,
        "baseline_avg_risk_score": avg_risk,
    }


def _simulate_stockouts(
    coverage_summary: pd.DataFrame,
    horizon_days: int,
    demand_spike: float,
    shrinkage: float,
) -> int:
    if coverage_summary.empty:
        return 0
    days = pd.to_numeric(coverage_summary.get("days_to_stockout"), errors="coerce").fillna(9999.0)
    adjusted = days / (1 + demand_spike + shrinkage)
    return int((adjusted <= horizon_days).sum())


def _simulate_delays(procurement_recommendations: pd.DataFrame, delay_days: int) -> int:
    if procurement_recommendations.empty or delay_days <= 0:
        return 0
    proc = procurement_recommendations.copy()
    proc["days_to_stockout"] = pd.to_numeric(proc["days_to_stockout"], errors="coerce").fillna(9999.0)
    proc["lead_time_days"] = pd.to_numeric(proc["lead_time_days"], errors="coerce").fillna(0.0)
    can_arrive = proc["lead_time_days"] + delay_days <= proc["days_to_stockout"]
    return int((~can_arrive).sum())


def _average_price(procurement_recommendations: pd.DataFrame) -> float:
    if procurement_recommendations.empty:
        return 0.0
    prices = pd.to_numeric(
        procurement_recommendations.get("estimated_unit_price_inr", pd.Series(dtype=float)), errors="coerce"
    ).fillna(0.0)
    return float(prices.mean()) if not prices.empty else 0.0


def _scenario_summary(stockouts: int, delayed_orders: int, losses: float) -> str:
    if stockouts >= 5:
        return "High disruption risk with multiple stockouts."
    if delayed_orders >= 5:
        return "Supplier delays dominate; expedite approvals."
    if losses > 1_000_000:
        return "Material losses exceed INR 10L; prioritize mitigation."
    return "Manageable risk with targeted interventions."


def _num(value: object) -> float:
    try:
        if value is None or pd.isna(value):
            return 0.0
        return float(value)
    except (TypeError, ValueError):
        return 0.0
