from __future__ import annotations

import json

import pandas as pd

from .config import PipelineConfig


def build_bom_forecast(
    production_orders: pd.DataFrame,
    material_master: pd.DataFrame,
    seasonal_index: pd.DataFrame,
    analysis_date: pd.Timestamp,
    config: PipelineConfig,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    planning_end = analysis_date + pd.Timedelta(days=config.planning_window_days)
    forecast_end = analysis_date + pd.Timedelta(days=config.forecast_horizon_days)

    orders = production_orders[
        (production_orders["delivery_date"] > analysis_date)
        & (production_orders["delivery_date"] <= planning_end)
    ].copy()

    material_lookup = material_master.set_index("material_id")[["name", "category", "unit"]]
    season_lookup = seasonal_index.set_index("month")["fmcg_demand_multiplier"].to_dict()

    rows: list[dict[str, object]] = []
    for _, order in orders.iterrows():
        bom = json.loads(order["material_bom"])
        multiplier = season_lookup.get(int(order["delivery_date"].month), 1.0)
        for material_id, bom_qty in bom.items():
            raw_required_qty = float(order["quantity"]) * float(bom_qty)
            rows.append(
                {
                    "order_id": order["order_id"],
                    "client_id": order["client_id"],
                    "product_type": order["product_type"],
                    "box_size": order["box_size"],
                    "delivery_date": order["delivery_date"],
                    "material_id": material_id,
                    "bom_qty_per_box": float(bom_qty),
                    "order_quantity": float(order["quantity"]),
                    "raw_required_qty": raw_required_qty,
                    "seasonal_multiplier": float(multiplier),
                    "seasonal_required_qty": raw_required_qty * float(multiplier),
                }
            )

    exploded = pd.DataFrame(rows)
    if exploded.empty:
        exploded = pd.DataFrame(
            columns=[
                "order_id",
                "client_id",
                "product_type",
                "box_size",
                "delivery_date",
                "material_id",
                "bom_qty_per_box",
                "order_quantity",
                "raw_required_qty",
                "seasonal_multiplier",
                "seasonal_required_qty",
            ]
        )

    exploded = exploded.merge(material_lookup, on="material_id", how="left")
    exploded = exploded.rename(columns={"name": "material_name", "unit": "canonical_unit"})
    exploded["delivery_date"] = pd.to_datetime(exploded["delivery_date"])
    exploded = exploded.sort_values(["delivery_date", "order_id", "material_id"])

    daily = (
        exploded.groupby(["delivery_date", "material_id", "material_name", "canonical_unit"], dropna=False)
        .agg(
            order_count=("order_id", "nunique"),
            raw_required_qty=("raw_required_qty", "sum"),
            seasonal_required_qty=("seasonal_required_qty", "sum"),
        )
        .reset_index()
        .sort_values(["delivery_date", "material_id"])
    )

    forecast = exploded[exploded["delivery_date"] <= forecast_end].copy()
    forecast["days_from_analysis"] = (forecast["delivery_date"] - analysis_date).dt.days
    forecast["forecast_week"] = ((forecast["days_from_analysis"] - 1) // 7 + 1).clip(lower=1)
    forecast["week_start"] = analysis_date + pd.to_timedelta((forecast["forecast_week"] - 1) * 7 + 1, unit="D")
    forecast["week_end"] = forecast["week_start"] + pd.Timedelta(days=6)

    weekly = (
        forecast.groupby(
            [
                "forecast_week",
                "week_start",
                "week_end",
                "material_id",
                "material_name",
                "canonical_unit",
            ],
            dropna=False,
        )
        .agg(
            order_count=("order_id", "nunique"),
            raw_required_qty=("raw_required_qty", "sum"),
            seasonal_required_qty=("seasonal_required_qty", "sum"),
        )
        .reset_index()
        .sort_values(["forecast_week", "material_id"])
    )

    return exploded, daily, weekly
