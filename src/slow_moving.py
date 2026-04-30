from __future__ import annotations

import pandas as pd


def build_slow_moving_watchlist(
    material_master: pd.DataFrame, weekly_material_demand_4w: pd.DataFrame
) -> pd.DataFrame:
    demand = (
        weekly_material_demand_4w.groupby("material_id", as_index=False)["seasonal_required_qty"]
        .sum()
        .rename(columns={"seasonal_required_qty": "forecast_demand_4w"})
    )
    watchlist = material_master.merge(demand, on="material_id", how="left")
    watchlist["forecast_demand_4w"] = watchlist["forecast_demand_4w"].fillna(0.0)
    watchlist["average_daily_demand_4w"] = watchlist["forecast_demand_4w"] / 28.0
    watchlist["days_cover_from_4w_forecast"] = watchlist.apply(
        lambda row: 9999
        if row["average_daily_demand_4w"] <= 0
        else row["current_stock"] / row["average_daily_demand_4w"],
        axis=1,
    )
    watchlist["watchlist_reason"] = watchlist.apply(_reason, axis=1)
    watchlist = watchlist[watchlist["watchlist_reason"] != ""].copy()
    return watchlist[
        [
            "material_id",
            "name",
            "category",
            "unit",
            "current_stock",
            "forecast_demand_4w",
            "days_cover_from_4w_forecast",
            "watchlist_reason",
        ]
    ].sort_values(["watchlist_reason", "material_id"])


def _reason(row: pd.Series) -> str:
    if row["material_id"] in {"M06", "M12"}:
        return "business background watch item; avoid ordering unless demand/stockout logic requires it"
    if row["forecast_demand_4w"] <= 0 and row["current_stock"] > 0:
        return "no 4-week forecast demand with stock on hand"
    if row["days_cover_from_4w_forecast"] > 60:
        return "more than 60 days of cover"
    return ""
