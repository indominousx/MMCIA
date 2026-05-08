from __future__ import annotations

from typing import Iterable

import pandas as pd

from .config import PipelineConfig


USAGE_TRANSACTION_TYPES = {
    "issue",
    "consumption",
    "usage",
    "withdrawal",
    "backflush",
}


def build_advanced_forecast(
    daily_material_demand: pd.DataFrame,
    normalized_transactions: pd.DataFrame,
    material_master: pd.DataFrame,
    seasonal_index: pd.DataFrame,
    analysis_date: pd.Timestamp,
    config: PipelineConfig,
) -> pd.DataFrame:
    """Build a layered, interpretable demand forecast with volatility and confidence bands."""
    material_lookup = material_master.set_index("material_id").to_dict("index")
    season_lookup = (
        seasonal_index.set_index("month")["fmcg_demand_multiplier"].to_dict()
        if not seasonal_index.empty and "month" in seasonal_index
        else {}
    )

    usage_history = _usage_history(normalized_transactions, analysis_date)
    planned_history = _planned_history(daily_material_demand)

    rows: list[dict[str, object]] = []
    horizon_dates = pd.date_range(
        analysis_date + pd.Timedelta(days=1),
        analysis_date + pd.Timedelta(days=config.forecast_horizon_days),
        freq="D",
    )

    for material_id, material in material_lookup.items():
        history = usage_history.get(material_id)
        history_source = "transaction_usage"
        if history is None or history.empty:
            history = planned_history.get(material_id, pd.Series(dtype=float))
            history_source = "bom_forecast"

        history = history.sort_index()
        method, base, volatility, growth_rate, anomaly_flag, accuracy = _forecast_features(history)
        std = float(history.std()) if len(history) > 1 else 0.0

        for date in horizon_dates:
            seasonality = float(season_lookup.get(int(date.month), 1.0))
            day_offset = (date - analysis_date).days
            predicted = max(0.0, base + growth_rate * day_offset)
            predicted *= seasonality
            band = 1.96 * std
            rows.append(
                {
                    "material_id": material_id,
                    "material_name": material.get("name", ""),
                    "unit": material.get("unit", ""),
                    "forecast_date": date.date().isoformat(),
                    "predicted_demand": predicted,
                    "forecast_method": method,
                    "confidence_low": max(0.0, predicted - band),
                    "confidence_high": predicted + band,
                    "volatility_score": volatility,
                    "growth_rate": growth_rate,
                    "anomaly_flag": anomaly_flag,
                    "forecast_accuracy": accuracy,
                    "seasonality_multiplier": seasonality,
                    "base_demand_source": history_source,
                }
            )

    return pd.DataFrame(rows)


def _usage_history(
    normalized_transactions: pd.DataFrame, analysis_date: pd.Timestamp
) -> dict[str, pd.Series]:
    if normalized_transactions.empty:
        return {}
    usage = normalized_transactions.copy()
    usage["date"] = pd.to_datetime(usage["date"], errors="coerce")
    usage["transaction_type"] = usage["transaction_type"].astype(str).str.lower()
    usage = usage[
        usage["transaction_type"].isin(USAGE_TRANSACTION_TYPES)
    ].copy()
    if usage.empty:
        return {}

    usage = usage[usage["date"] <= analysis_date]
    usage["quantity_normalized"] = pd.to_numeric(usage["quantity_normalized"], errors="coerce").fillna(0.0)
    grouped = usage.groupby(["material_id", "date"], as_index=False)["quantity_normalized"].sum()

    history: dict[str, pd.Series] = {}
    for material_id, group in grouped.groupby("material_id"):
        series = group.set_index("date")["quantity_normalized"]
        series = series.sort_index()
        history[material_id] = series.tail(120)
    return history


def _planned_history(daily_material_demand: pd.DataFrame) -> dict[str, pd.Series]:
    if daily_material_demand.empty:
        return {}
    planned = daily_material_demand.copy()
    planned["delivery_date"] = pd.to_datetime(planned["delivery_date"], errors="coerce")
    planned["seasonal_required_qty"] = pd.to_numeric(
        planned["seasonal_required_qty"], errors="coerce"
    ).fillna(0.0)
    grouped = planned.groupby(["material_id", "delivery_date"], as_index=False)[
        "seasonal_required_qty"
    ].sum()

    history: dict[str, pd.Series] = {}
    for material_id, group in grouped.groupby("material_id"):
        series = group.set_index("delivery_date")["seasonal_required_qty"].sort_index()
        history[material_id] = series
    return history


def _forecast_features(history: pd.Series) -> tuple[str, float, float, float, bool, float]:
    if history.empty:
        return "naive", 0.0, 0.0, 0.0, False, 0.0

    series = history.astype(float)
    mean = float(series.mean()) if len(series) else 0.0
    std = float(series.std()) if len(series) > 1 else 0.0
    volatility = 0.0 if mean <= 0 else min(1.0, std / mean)
    growth_rate = _linear_trend(series)
    anomaly_flag = _zscore_anomaly(series)
    accuracy = _mape(series, _moving_average(series, 7))

    if len(series) < 7:
        return "naive", mean, volatility * 100, 0.0, anomaly_flag, accuracy

    if volatility > 0.6:
        base = _exp_smoothing(series, 0.35)
        return "exp_smoothing", base, volatility * 100, growth_rate, anomaly_flag, accuracy

    if abs(growth_rate) > 0.05:
        base = float(series.iloc[-1])
        return "trend_regression", base, volatility * 100, growth_rate, anomaly_flag, accuracy

    base = _moving_average(series, 7)
    return "moving_average", base, volatility * 100, 0.0, anomaly_flag, accuracy


def _moving_average(series: pd.Series, window: int) -> float:
    if series.empty:
        return 0.0
    return float(series.tail(window).mean())


def _exp_smoothing(series: pd.Series, alpha: float) -> float:
    value = float(series.iloc[0]) if not series.empty else 0.0
    for point in series.iloc[1:]:
        value = alpha * float(point) + (1 - alpha) * value
    return value


def _linear_trend(series: pd.Series) -> float:
    if len(series) < 2:
        return 0.0
    values = series.tail(28).to_list()
    n = len(values)
    xs = list(range(n))
    sum_x = sum(xs)
    sum_y = sum(values)
    sum_xy = sum(x * y for x, y in zip(xs, values))
    sum_x2 = sum(x * x for x in xs)
    denominator = n * sum_x2 - sum_x * sum_x
    if denominator == 0:
        return 0.0
    slope = (n * sum_xy - sum_x * sum_y) / denominator
    return slope


def _zscore_anomaly(series: pd.Series, threshold: float = 2.0) -> bool:
    if len(series) < 3:
        return False
    mean = float(series.mean())
    std = float(series.std())
    if std <= 0:
        return False
    zscore = (float(series.iloc[-1]) - mean) / std
    return abs(zscore) >= threshold


def _mape(actuals: Iterable[float], fitted: float) -> float:
    values = [float(value) for value in actuals]
    if not values:
        return 0.0
    non_zero = [value for value in values if value != 0]
    if not non_zero:
        return 0.0
    return float(sum(abs((value - fitted) / value) for value in non_zero) / len(non_zero))
