from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from .bom_forecast import build_bom_forecast
from .config import PipelineConfig
from .inventory_projection import project_inventory
from .load_data import load_inputs, write_quality_report
from .procurement_engine import build_procurement_recommendations
from .reporting import build_weekly_report, write_csv_outputs
from .slow_moving import build_slow_moving_watchlist
from .substitution import build_substitution_recommendations
from .unit_normalization import normalize_transactions


@dataclass
class PipelineResult:
    analysis_date: pd.Timestamp
    output_dir: Path
    report_path: Path
    outputs: dict[str, pd.DataFrame]


def run_inventory_pipeline(config: PipelineConfig | None = None) -> PipelineResult:
    config = config or PipelineConfig()
    config.output_dir.mkdir(parents=True, exist_ok=True)

    bundle = load_inputs(config)
    write_quality_report(bundle, config.output_dir)

    normalized_transactions, conversion_logic, conversion_exceptions = normalize_transactions(
        bundle.inventory_transactions, bundle.material_master
    )

    bom_exploded, daily_demand, weekly_demand = build_bom_forecast(
        bundle.production_orders,
        bundle.material_master,
        bundle.seasonal_index,
        bundle.analysis_date,
        config,
    )

    inventory_projection, coverage_summary, stockout_alerts = project_inventory(
        bundle.material_master, daily_demand, bundle.analysis_date, config
    )

    procurement, blocked_by_credit, credit_summary = build_procurement_recommendations(
        bundle.material_master,
        bundle.supplier_master,
        normalized_transactions,
        daily_demand,
        coverage_summary,
        bundle.working_capital_log,
        bundle.analysis_date,
        config,
    )

    substitutions = build_substitution_recommendations(
        bundle.material_master,
        bundle.supplier_master,
        normalized_transactions,
        coverage_summary,
        bundle.working_capital_log,
        bundle.analysis_date,
        config,
    )

    slow_moving = build_slow_moving_watchlist(bundle.material_master, weekly_demand)

    outputs = {
        "normalized_transactions": normalized_transactions,
        "unit_conversion_logic": conversion_logic,
        "unit_conversion_exceptions": conversion_exceptions,
        "bom_exploded_order_demand": bom_exploded,
        "daily_material_demand": daily_demand,
        "weekly_material_demand_4w": weekly_demand,
        "inventory_projection_daily": inventory_projection,
        "inventory_coverage_summary": coverage_summary,
        "stockout_alerts_21d": stockout_alerts,
        "procurement_recommendations": procurement,
        "procurement_blocked_by_credit": blocked_by_credit,
        "credit_summary": credit_summary,
        "substitution_recommendations": substitutions,
        "slow_moving_watchlist": slow_moving,
        "data_quality_issues": bundle.quality_issues,
    }
    write_csv_outputs(config.output_dir, outputs)
    report_path = build_weekly_report(config.output_dir, outputs, bundle.analysis_date)

    return PipelineResult(
        analysis_date=bundle.analysis_date,
        output_dir=config.output_dir,
        report_path=report_path,
        outputs=outputs,
    )
