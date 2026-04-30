from __future__ import annotations

from src.config import PipelineConfig
from src.pipeline import run_inventory_pipeline


def main() -> None:
    result = run_inventory_pipeline(PipelineConfig())
    procurement = result.outputs["procurement_recommendations"]
    blocked_by_credit = result.outputs["procurement_blocked_by_credit"]
    stockout_alerts = result.outputs["stockout_alerts_21d"]

    print(f"Analysis date: {result.analysis_date.date()}")
    print(f"Wrote outputs to: {result.output_dir.resolve()}")
    print(f"Wrote weekly report: {result.report_path.resolve()}")
    print(f"Approved recommendation lines: {len(procurement)}")
    print(f"Blocked recommendation lines: {len(blocked_by_credit)}")
    print(f"Stockout alert lines: {len(stockout_alerts)}")


if __name__ == "__main__":
    main()
