from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import pandas as pd


@dataclass(frozen=True)
class PipelineConfig:
    input_dir: Path = Path(".")
    output_dir: Path = Path("outputs")
    credit_cap_inr: float = 3_000_000.0
    forecast_horizon_days: int = 28
    planning_window_days: int = 42
    alert_horizon_days: int = 21
    critical_days_cover: int = 3
    analysis_date: Optional[pd.Timestamp] = None

    def resolve_analysis_date(self, production_orders: pd.DataFrame) -> pd.Timestamp:
        if self.analysis_date is not None:
            return pd.Timestamp(self.analysis_date).normalize()
        return pd.to_datetime(production_orders["order_date"]).max().normalize()

    @property
    def files(self) -> dict[str, Path]:
        return {
            "inventory_transactions": self.input_dir / "inventory_transactions.csv",
            "production_orders": self.input_dir / "production_orders.csv",
            "material_master": self.input_dir / "material_master.csv",
            "supplier_master": self.input_dir / "supplier_master.csv",
            "seasonal_index": self.input_dir / "seasonal_index.csv",
            "working_capital_log": self.input_dir / "working_capital_log.csv",
        }
