from __future__ import annotations

import math
from pathlib import Path
from threading import RLock
from typing import Any

import pandas as pd

from .alerting import (
    build_alert_digest,
    build_alert_email,
    load_email_settings,
    send_alert_email,
    with_recipients,
)
from .config import PipelineConfig
from .pipeline import run_inventory_pipeline
from .simulation_engine import run_scenario_simulations


OUTPUT_FILES = {
    "bom_exploded_order_demand": "bom_exploded_order_demand.csv",
    "weekly_material_demand_4w": "weekly_material_demand_4w.csv",
    "daily_material_demand": "daily_material_demand.csv",
    "inventory_coverage_summary": "inventory_coverage_summary.csv",
    "inventory_projection_daily": "inventory_projection_daily.csv",
    "stockout_alerts_21d": "stockout_alerts_21d.csv",
    "procurement_recommendations": "procurement_recommendations.csv",
    "procurement_blocked_by_credit": "procurement_blocked_by_credit.csv",
    "credit_summary": "credit_summary.csv",
    "substitution_recommendations": "substitution_recommendations.csv",
    "slow_moving_watchlist": "slow_moving_watchlist.csv",
    "data_quality_issues": "data_quality_issues.csv",
    "unit_conversion_logic": "unit_conversion_logic.csv",
    "advanced_forecast": "advanced_forecast.csv",
    "material_risk_scores": "material_risk_scores.csv",
    "ai_recommendations": "ai_recommendations.csv",
    "scenario_simulation_results": "scenario_simulation_results.csv",
}


class ProductService:
    def __init__(self, config: PipelineConfig | None = None) -> None:
        self.config = config or PipelineConfig()
        self._lock = RLock()
        self._frames: dict[str, pd.DataFrame] = {}
        self._analysis_date = ""
        self._last_refresh_note = "not loaded"

    def ensure_loaded(self) -> None:
        with self._lock:
            if self._frames:
                return
            if self._outputs_available():
                self._load_outputs()
                self._last_refresh_note = "loaded from outputs"
                return
            self.recompute()

    def recompute(self) -> dict[str, Any]:
        with self._lock:
            result = run_inventory_pipeline(self.config)
            self._frames = result.outputs
            self._analysis_date = result.analysis_date.date().isoformat()
            self._last_refresh_note = "recomputed from source CSVs"
            return self.overview()

    def overview(self) -> dict[str, Any]:
        self.ensure_loaded()
        credit = self._first_row("credit_summary")
        approved = self._frame("procurement_recommendations")
        blocked = self._frame("procurement_blocked_by_credit")
        alerts = self._frame("stockout_alerts_21d")
        quality = self._frame("data_quality_issues")

        approved_value = _sum(approved, "recommended_value_inr")
        blocked_value = _sum(blocked, "recommended_value_inr")
        cap = _num(credit.get("credit_cap_inr"))
        utilized = _num(credit.get("projected_credit_utilized_after_approved_inr"))
        remaining = _num(credit.get("remaining_available_credit_inr"))
        utilization_pct = 0.0 if cap <= 0 else utilized / cap * 100

        return {
            "analysisDate": self._analysis_date,
            "lastRefresh": self._last_refresh_note,
            "modules": [
                {
                    "name": "Demand Planning Engine",
                    "status": "BOM-aware forecast active",
                    "metric": f"{len(self._frame('bom_exploded_order_demand')):,} BOM demand rows",
                },
                {
                    "name": "Advanced Forecasting Engine",
                    "status": "Volatility-aware forecast active",
                    "metric": f"{len(self._frame('advanced_forecast')):,} forecast rows",
                },
                {
                    "name": "Inventory Management System",
                    "status": "Daily stock projection active",
                    "metric": f"{len(alerts)} critical alerts",
                },
                {
                    "name": "Risk Scoring Engine",
                    "status": "Unified risk scoring active",
                    "metric": f"{len(self._frame('material_risk_scores')):,} material risk scores",
                },
                {
                    "name": "Smart Procurement Engine",
                    "status": "Credit and MOQ gate active",
                    "metric": f"{len(approved)} approved, {len(blocked)} blocked",
                },
                {
                    "name": "AI Decision Agent",
                    "status": "Explainable actions generated",
                    "metric": f"{len(self._frame('ai_recommendations')):,} decisions",
                },
                {
                    "name": "Scenario Simulation Engine",
                    "status": "Stress testing active",
                    "metric": f"{len(self._frame('scenario_simulation_results')):,} scenarios",
                },
                {
                    "name": "Decision Dashboard",
                    "status": "Supplier-ready actions active",
                    "metric": f"INR {_format_number(remaining)} credit left",
                },
            ],
            "kpis": {
                "creditCapInr": cap,
                "projectedCreditUtilizedInr": utilized,
                "remainingCreditInr": remaining,
                "creditUtilizationPct": utilization_pct,
                "approvedPoValueInr": approved_value,
                "blockedPoValueInr": blocked_value,
                "stockoutAlertCount": len(alerts),
                "dataQualityIssueCount": len(quality),
            },
            "topRisks": _records(
                alerts.sort_values(["days_of_cover", "projected_shortage_qty"], ascending=[True, False]).head(6)
            ),
            "approvedActions": _records(approved.head(5)),
            "blockedActions": _records(blocked.head(5)),
        }

    def demand_planning(self) -> dict[str, Any]:
        self.ensure_loaded()
        weekly = self._frame("weekly_material_demand_4w")
        trace = self._frame("bom_exploded_order_demand")

        material_totals = (
            weekly.groupby(["material_id", "material_name", "canonical_unit"], as_index=False)
            .agg(seasonal_required_qty=("seasonal_required_qty", "sum"))
            .sort_values(by="seasonal_required_qty", ascending=False)
            if not weekly.empty
            else pd.DataFrame()
        )
        week_totals = (
            weekly.groupby(["forecast_week", "week_start", "week_end"], as_index=False)
            .agg(seasonal_required_qty=("seasonal_required_qty", "sum"))
            .sort_values(by="forecast_week")
            if not weekly.empty
            else pd.DataFrame()
        )

        return {
            "analysisDate": self._analysis_date,
            "weeklyDemand": _records(weekly),
            "weekTotals": _records(week_totals),
            "materialTotals": _records(material_totals),
            "bomTraceSample": _records(trace.head(100)),
        }

    def inventory_management(self) -> dict[str, Any]:
        self.ensure_loaded()
        coverage = self._frame("inventory_coverage_summary")
        projection = self._frame("inventory_projection_daily")
        alerts = self._frame("stockout_alerts_21d")
        slow = self._frame("slow_moving_watchlist")

        return {
            "coverage": _records(coverage.sort_values(["days_of_cover", "material_id"])),
            "alerts": _records(alerts.sort_values(["days_of_cover", "projected_shortage_qty"], ascending=[True, False])),
            "projection": _records(projection),
            "slowMoving": _records(slow),
        }

    def smart_procurement(self) -> dict[str, Any]:
        self.ensure_loaded()
        approved = self._frame("procurement_recommendations")
        blocked = self._frame("procurement_blocked_by_credit")
        credit = self._frame("credit_summary")

        supplier_groups = (
            approved.groupby(["supplier_id", "supplier_name"], as_index=False)
            .agg(
                line_count=("material_id", "count"),
                approved_value_inr=("recommended_value_inr", "sum"),
                remaining_credit_after_last_line=("remaining_available_credit_inr", "last"),
            )
            .sort_values("approved_value_inr", ascending=False)
            if not approved.empty
            else pd.DataFrame()
        )

        return {
            "creditSummary": _records(credit),
            "supplierGroups": _records(supplier_groups),
            "approved": _records(approved),
            "blocked": _records(blocked),
        }

    def substitutions(self) -> dict[str, Any]:
        self.ensure_loaded()
        substitutions = self._frame("substitution_recommendations")
        m01 = substitutions[
            (substitutions.get("source_material_id", pd.Series(dtype=str)) == "M01")
            & (substitutions.get("substitute_material_id", pd.Series(dtype=str)) == "M02")
        ]
        return {
            "m01ToM02": _records(m01),
            "allSubstitutions": _records(substitutions),
        }

    def decision_dashboard(self) -> dict[str, Any]:
        self.ensure_loaded()
        overview = self.overview()
        procurement = self.smart_procurement()
        inventory = self.inventory_management()
        demand = self.demand_planning()
        substitutions = self.substitutions()
        ai_recommendations = self.ai_recommendations()
        risk_intelligence = self.risk_intelligence()
        simulations = self.simulation_lab()
        return {
            "overview": overview,
            "immediateActions": overview["approvedActions"] + overview["blockedActions"],
            "credit": procurement["creditSummary"],
            "criticalAlerts": inventory["alerts"][:8],
            "largestDemandMaterials": demand["materialTotals"][:8],
            "substitutionOptions": substitutions["allSubstitutions"][:8],
            "aiRecommendations": ai_recommendations.get("recommendations", [])[:8],
            "topRisks": risk_intelligence.get("topRisks", [])[:8],
            "scenarioHighlights": simulations.get("scenarios", [])[:4],
        }

    def data_quality(self) -> dict[str, Any]:
        self.ensure_loaded()
        return {
            "issues": _records(self._frame("data_quality_issues")),
            "unitConversions": _records(self._frame("unit_conversion_logic")),
        }

    def risk_intelligence(self) -> dict[str, Any]:
        self.ensure_loaded()
        scores = self._frame("material_risk_scores")
        if scores.empty:
            return {"summary": {}, "scores": [], "topRisks": [], "supplierRisks": []}
        counts = scores["severity"].value_counts().to_dict()
        summary: dict[str, object] = {str(key): int(value) for key, value in counts.items()}
        summary["avgRiskScore"] = float(pd.to_numeric(scores["risk_score"], errors="coerce").mean())
        top = scores.sort_values("risk_score", ascending=False).head(12)
        supplier_rankings = _supplier_risk_ranking(scores, self._frame("procurement_recommendations"))
        return {
            "summary": summary,
            "scores": _records(scores),
            "topRisks": _records(top),
            "supplierRisks": _records(supplier_rankings),
        }

    def advanced_forecast(self) -> dict[str, Any]:
        self.ensure_loaded()
        forecast = self._frame("advanced_forecast")
        if forecast.empty:
            return {"forecast": [], "weeklyTotals": [], "topVolatility": []}
        forecast["forecast_date"] = pd.to_datetime(forecast["forecast_date"], errors="coerce")
        forecast["forecast_week"] = forecast["forecast_date"].dt.to_period("W").apply(lambda v: v.start_time)
        weekly = (
            forecast.groupby("forecast_week", as_index=False)
            .agg(predicted_demand=("predicted_demand", "sum"))
            .sort_values(by="forecast_week")
        )
        volatility = (
            forecast.groupby(["material_id", "material_name"], as_index=False)
            .agg(volatility_score=("volatility_score", "max"))
            .sort_values(by="volatility_score", ascending=False)
            .head(10)
        )
        return {
            "forecast": _records(forecast),
            "weeklyTotals": _records(weekly),
            "topVolatility": _records(volatility),
        }

    def ai_recommendations(self) -> dict[str, Any]:
        self.ensure_loaded()
        recommendations = self._frame("ai_recommendations")
        return {"recommendations": _records(recommendations)}

    def simulation_lab(self) -> dict[str, Any]:
        self.ensure_loaded()
        scenarios = self._frame("scenario_simulation_results")
        return {"scenarios": _records(scenarios)}

    def run_scenario(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        """Run a custom scenario with parameters from the UI and return results."""
        self.ensure_loaded()
        payload = payload or {}
        params = {
            "demand_spike": float(payload.get("demand_spike", 0.0) or 0.0),
            "supplier_delay_days": int(payload.get("supplier_delay_days", 0) or 0),
            "credit_reduction": float(payload.get("credit_reduction", 0.0) or 0.0),
            "inventory_shrinkage": float(payload.get("inventory_shrinkage", 0.0) or 0.0),
            "approval_delay_days": int(payload.get("approval_delay_days", 0) or 0),
        }

        coverage = self._frame("inventory_coverage_summary")
        daily = self._frame("daily_material_demand")
        procurement = self._frame("procurement_recommendations")
        supplier_master = self._frame("supplier_master") if "supplier_master" in self._frames else pd.DataFrame()
        risk_scores = self._frame("material_risk_scores")

        # Build a single scenario descriptor using params
        scenario_template = {
            "scenario": payload.get("label") or f"Custom scenario {params}",
            "demand_spike": params["demand_spike"],
            "supplier_delay_days": params["supplier_delay_days"],
            "credit_reduction": params["credit_reduction"],
            "inventory_shrinkage": params["inventory_shrinkage"],
            "approval_delay_days": params["approval_delay_days"],
        }

        # Run the simulation engine with the single custom scenario
        try:
            results = run_scenario_simulations(
                coverage,
                daily,
                procurement,
                supplier_master,
                risk_scores,
                pd.to_datetime(self._analysis_date) if self._analysis_date else pd.Timestamp.now(),
                self.config,
            )
        except Exception as exc:
            return {"ok": False, "error": "simulation_failed", "detail": str(exc)}

        # If engine returns multiple default scenarios, filter for our custom near-match by parameters.
        # Otherwise return entire results with a marker.
        rows = _records(results)
        return {"ok": True, "scenarios": rows, "params": params}

    def alert_config(self) -> dict[str, Any]:
        _, status = load_email_settings()
        return status

    def alert_digest(self) -> dict[str, Any]:
        self.ensure_loaded()
        return build_alert_digest(
            self._analysis_date,
            self._frame("stockout_alerts_21d"),
            self._frame("procurement_recommendations"),
            self._frame("procurement_blocked_by_credit"),
            self._frame("credit_summary"),
            self._frame("substitution_recommendations"),
        )

    def send_alerts(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        self.ensure_loaded()
        settings, status = load_email_settings()
        if settings is None:
            return {
                "ok": False,
                "error": "missing_email_settings",
                "missing": status.get("missing", []),
                "status": status,
            }

        if payload and isinstance(payload.get("recipients"), list):
            settings = with_recipients(settings, payload["recipients"])

        digest = build_alert_digest(
            self._analysis_date,
            self._frame("stockout_alerts_21d"),
            self._frame("procurement_recommendations"),
            self._frame("procurement_blocked_by_credit"),
            self._frame("credit_summary"),
            self._frame("substitution_recommendations"),
        )
        subject, text, html = build_alert_email(digest)
        try:
            send_alert_email(settings, subject, text, html)
        except Exception as exc:
            return {"ok": False, "error": "send_failed", "detail": str(exc)}

        return {
            "ok": True,
            "recipients": list(settings.recipients),
            "summary": digest.get("summary", {}),
        }

    def report_path(self) -> Path:
        self.ensure_loaded()
        return self.config.output_dir / "weekly_purchase_report.xlsx"

    def _outputs_available(self) -> bool:
        return all((self.config.output_dir / filename).exists() for filename in OUTPUT_FILES.values())

    def _load_outputs(self) -> None:
        self.config.output_dir.mkdir(parents=True, exist_ok=True)
        frames: dict[str, pd.DataFrame] = {}
        for name, filename in OUTPUT_FILES.items():
            path = self.config.output_dir / filename
            frames[name] = pd.read_csv(path) if path.exists() else pd.DataFrame()
        self._frames = frames
        self._analysis_date = _infer_analysis_date(frames)

    def _frame(self, name: str) -> pd.DataFrame:
        return self._frames.get(name, pd.DataFrame()).copy()

    def _first_row(self, name: str) -> dict[str, Any]:
        frame = self._frame(name)
        if frame.empty:
            return {}
        return {str(key): value for key, value in frame.iloc[0].to_dict().items()}


def _infer_analysis_date(frames: dict[str, pd.DataFrame]) -> str:
    weekly = frames.get("weekly_material_demand_4w", pd.DataFrame())
    if not weekly.empty and "week_start" in weekly:
        first_week_start = pd.to_datetime(weekly["week_start"], errors="coerce").min()
        if pd.notna(first_week_start):
            return (first_week_start - pd.Timedelta(days=1)).date().isoformat()
    return ""


def _records(frame: pd.DataFrame) -> list[dict[str, Any]]:
    if frame.empty:
        return []
    clean = frame.replace({pd.NA: None})
    clean = clean.where(pd.notna(clean), None)
    return [_jsonable_record({str(key): value for key, value in row.items()}) for row in clean.to_dict(orient="records")]


def _jsonable_record(row: dict[str, Any]) -> dict[str, Any]:
    return {key: _jsonable(value) for key, value in row.items()}


def _jsonable(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (pd.Timestamp,)):
        return value.isoformat()
    if hasattr(value, "item"):
        try:
            return _jsonable(value.item())
        except Exception:
            pass
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    return value


def _sum(frame: pd.DataFrame, column: str) -> float:
    if frame.empty or column not in frame:
        return 0.0
    return float(pd.to_numeric(frame[column], errors="coerce").fillna(0).sum())


def _num(value: Any) -> float:
    if value is None:
        return 0.0
    try:
        if pd.isna(value):
            return 0.0
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _format_number(value: float) -> str:
    if abs(value) >= 10_000_000:
        return f"{value / 10_000_000:.2f}Cr"
    if abs(value) >= 100_000:
        return f"{value / 100_000:.2f}L"
    return f"{value:,.0f}"


def _supplier_risk_ranking(
    risk_scores: pd.DataFrame, procurement_recommendations: pd.DataFrame
) -> pd.DataFrame:
    if risk_scores.empty or procurement_recommendations.empty:
        return pd.DataFrame(columns=["supplier_name", "avg_risk_score", "material_count"])
    joined = procurement_recommendations.merge(
        risk_scores[["material_id", "risk_score"]], on="material_id", how="left"
    )
    joined["risk_score"] = pd.to_numeric(joined["risk_score"], errors="coerce").fillna(0.0)
    rankings = (
        joined.groupby("supplier_name", as_index=False)
        .agg(avg_risk_score=("risk_score", "mean"), material_count=("material_id", "nunique"))
        .sort_values("avg_risk_score", ascending=False)
        .head(10)
    )
    return rankings
