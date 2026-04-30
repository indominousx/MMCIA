from __future__ import annotations

import math

import pandas as pd

from .config import PipelineConfig


def project_inventory(
    material_master: pd.DataFrame,
    daily_material_demand: pd.DataFrame,
    analysis_date: pd.Timestamp,
    config: PipelineConfig,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    date_index = pd.date_range(
        analysis_date + pd.Timedelta(days=1),
        analysis_date + pd.Timedelta(days=config.planning_window_days),
        freq="D",
    )
    demand_lookup = {
        (pd.Timestamp(row.delivery_date).normalize(), row.material_id): float(row.seasonal_required_qty)
        for row in daily_material_demand.itertuples(index=False)
    }

    projection_rows: list[dict[str, object]] = []
    summary_rows: list[dict[str, object]] = []

    for material in material_master.itertuples(index=False):
        material_id = material.material_id
        stock = float(material.current_stock)
        first_stockout_date = None
        min_projected_stock = stock
        total_21d = 0.0
        total_4w = 0.0
        total_planning = 0.0

        for date in date_index:
            demand_qty = demand_lookup.get((date.normalize(), material_id), 0.0)
            if (date - analysis_date).days <= config.alert_horizon_days:
                total_21d += demand_qty
            if (date - analysis_date).days <= config.forecast_horizon_days:
                total_4w += demand_qty
            total_planning += demand_qty

            starting_stock = stock
            stock -= demand_qty
            min_projected_stock = min(min_projected_stock, stock)
            if stock <= 0 and first_stockout_date is None:
                first_stockout_date = date.normalize()

            projection_rows.append(
                {
                    "date": date.date().isoformat(),
                    "days_from_analysis": (date - analysis_date).days,
                    "material_id": material_id,
                    "material_name": material.name,
                    "unit": material.unit,
                    "starting_stock": starting_stock,
                    "scheduled_demand_qty": demand_qty,
                    "projected_stock_after_demand": stock,
                }
            )

        if first_stockout_date is None:
            days_of_cover = math.inf
            days_to_stockout = pd.NA
            first_stockout_str = ""
            coverage_note = f"no stockout within {config.planning_window_days} days"
        else:
            days_of_cover = float((first_stockout_date - analysis_date).days)
            days_to_stockout = int(days_of_cover)
            first_stockout_str = first_stockout_date.date().isoformat()
            coverage_note = "projected stockout"

        under_3_days = bool(math.isfinite(days_of_cover) and days_of_cover < config.critical_days_cover)
        within_21_days = bool(math.isfinite(days_of_cover) and days_of_cover <= config.alert_horizon_days)
        projected_shortage_qty = max(0.0, -min_projected_stock)

        summary_rows.append(
            {
                "material_id": material_id,
                "material_name": material.name,
                "category": material.category,
                "unit": material.unit,
                "current_stock": float(material.current_stock),
                "reorder_point_current": float(material.reorder_point_current),
                "total_demand_21d": total_21d,
                "total_demand_4w": total_4w,
                "total_demand_planning_window": total_planning,
                "min_projected_stock_42d": min_projected_stock,
                "projected_shortage_qty": projected_shortage_qty,
                "first_stockout_date": first_stockout_str,
                "days_to_stockout": days_to_stockout,
                "days_of_cover": days_of_cover if math.isfinite(days_of_cover) else 9999,
                "under_3_days_stock": under_3_days,
                "stockout_within_21d": within_21_days,
                "substitute_material_ids": material.substitute_material_ids
                if not pd.isna(material.substitute_material_ids)
                else "",
                "coverage_note": coverage_note,
            }
        )

    projection = pd.DataFrame(projection_rows)
    coverage = pd.DataFrame(summary_rows).sort_values(["days_of_cover", "material_id"])
    alerts = coverage[
        coverage["under_3_days_stock"] | coverage["stockout_within_21d"]
    ].copy()
    alerts["alert_type"] = alerts.apply(_alert_type, axis=1)
    return projection, coverage, alerts


def _alert_type(row: pd.Series) -> str:
    if row["under_3_days_stock"]:
        return "less_than_3_days_stock"
    if row["stockout_within_21d"]:
        return "stockout_within_21_days"
    return "watch"
