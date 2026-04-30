from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict

import pandas as pd

from .config import PipelineConfig


REQUIRED_COLUMNS = {
    "inventory_transactions": {
        "date",
        "material_id",
        "transaction_type",
        "quantity",
        "unit",
        "supplier_id",
        "unit_price",
        "po_number",
    },
    "production_orders": {
        "order_id",
        "client_id",
        "product_type",
        "box_size",
        "quantity",
        "delivery_date",
        "order_date",
        "material_bom",
    },
    "material_master": {
        "material_id",
        "name",
        "category",
        "unit",
        "reorder_point_current",
        "current_stock",
        "warehouse_location",
        "substitute_material_ids",
    },
    "supplier_master": {
        "supplier_id",
        "supplier_name",
        "material_supplied",
        "lead_time_days",
        "moq",
        "moq_unit",
        "payment_terms_days",
        "reliability_score",
    },
    "seasonal_index": {"month", "month_name", "fmcg_demand_multiplier", "notes"},
    "working_capital_log": {
        "month",
        "credit_utilized_inr",
        "outstanding_payables_inr",
        "available_credit_inr",
        "overdue_amount_inr",
    },
}


@dataclass
class DataBundle:
    inventory_transactions: pd.DataFrame
    production_orders: pd.DataFrame
    material_master: pd.DataFrame
    supplier_master: pd.DataFrame
    seasonal_index: pd.DataFrame
    working_capital_log: pd.DataFrame
    analysis_date: pd.Timestamp
    quality_issues: pd.DataFrame
    data_facts: dict[str, object]


def load_inputs(config: PipelineConfig) -> DataBundle:
    frames = {name: pd.read_csv(path) for name, path in config.files.items()}

    frames["inventory_transactions"]["date"] = pd.to_datetime(
        frames["inventory_transactions"]["date"], errors="coerce"
    )
    frames["production_orders"]["delivery_date"] = pd.to_datetime(
        frames["production_orders"]["delivery_date"], errors="coerce"
    )
    frames["production_orders"]["order_date"] = pd.to_datetime(
        frames["production_orders"]["order_date"], errors="coerce"
    )
    frames["working_capital_log"]["month_date"] = pd.to_datetime(
        frames["working_capital_log"]["month"] + "-01", errors="coerce"
    )

    numeric_columns = {
        "inventory_transactions": ["quantity", "unit_price"],
        "production_orders": ["quantity"],
        "material_master": ["reorder_point_current", "current_stock"],
        "supplier_master": [
            "lead_time_days",
            "moq",
            "payment_terms_days",
            "reliability_score",
        ],
        "seasonal_index": ["month", "fmcg_demand_multiplier"],
        "working_capital_log": [
            "credit_utilized_inr",
            "outstanding_payables_inr",
            "available_credit_inr",
            "overdue_amount_inr",
        ],
    }
    for name, columns in numeric_columns.items():
        for column in columns:
            frames[name][column] = pd.to_numeric(frames[name][column], errors="coerce")

    analysis_date = config.resolve_analysis_date(frames["production_orders"])
    quality_issues = validate_inputs(frames, analysis_date)
    data_facts = build_data_facts(frames, analysis_date)

    return DataBundle(
        inventory_transactions=frames["inventory_transactions"],
        production_orders=frames["production_orders"],
        material_master=frames["material_master"],
        supplier_master=frames["supplier_master"],
        seasonal_index=frames["seasonal_index"],
        working_capital_log=frames["working_capital_log"],
        analysis_date=analysis_date,
        quality_issues=quality_issues,
        data_facts=data_facts,
    )


def validate_inputs(frames: Dict[str, pd.DataFrame], analysis_date: pd.Timestamp) -> pd.DataFrame:
    issues: list[dict[str, object]] = []

    for name, required in REQUIRED_COLUMNS.items():
        missing = sorted(required - set(frames[name].columns))
        if missing:
            issues.append(
                {
                    "severity": "error",
                    "file": f"{name}.csv",
                    "issue_type": "missing_columns",
                    "detail": ", ".join(missing),
                }
            )

    material_ids = set(frames["material_master"]["material_id"].dropna())
    supplier_ids = set(frames["supplier_master"]["supplier_id"].dropna())

    inv = frames["inventory_transactions"]
    unknown_inv_materials = sorted(set(inv["material_id"].dropna()) - material_ids)
    if unknown_inv_materials:
        issues.append(_issue("error", "inventory_transactions.csv", "unknown_material_id", unknown_inv_materials))
    unknown_inv_suppliers = sorted(set(inv["supplier_id"].dropna()) - supplier_ids)
    if unknown_inv_suppliers:
        issues.append(_issue("warning", "inventory_transactions.csv", "unknown_supplier_id", unknown_inv_suppliers))
    _add_null_date_issue(issues, inv, "inventory_transactions.csv", "date")
    _add_negative_issue(issues, inv, "inventory_transactions.csv", "quantity")
    _add_negative_issue(issues, inv, "inventory_transactions.csv", "unit_price")

    orders = frames["production_orders"]
    _add_null_date_issue(issues, orders, "production_orders.csv", "delivery_date")
    _add_null_date_issue(issues, orders, "production_orders.csv", "order_date")
    _add_negative_issue(issues, orders, "production_orders.csv", "quantity")

    bad_json = 0
    unknown_bom_materials: set[str] = set()
    for raw_bom in orders["material_bom"].dropna():
        try:
            parsed = json.loads(raw_bom)
        except json.JSONDecodeError:
            bad_json += 1
            continue
        unknown_bom_materials.update(set(parsed.keys()) - material_ids)
    if bad_json:
        issues.append(_issue("error", "production_orders.csv", "invalid_material_bom_json", bad_json))
    if unknown_bom_materials:
        issues.append(_issue("error", "production_orders.csv", "unknown_bom_material_id", sorted(unknown_bom_materials)))

    supplied_materials = explode_supplier_materials(frames["supplier_master"])["material_id"]
    missing_supplier_materials = sorted(material_ids - set(supplied_materials))
    if missing_supplier_materials:
        issues.append(
            _issue("error", "supplier_master.csv", "materials_without_supplier", missing_supplier_materials)
        )

    capital = frames["working_capital_log"]
    duplicates = capital[capital.duplicated("month", keep=False)]["month"].dropna().unique()
    if len(duplicates):
        issues.append(
            _issue(
                "warning",
                "working_capital_log.csv",
                "duplicate_months_keep_last_file_occurrence",
                sorted(duplicates),
            )
        )

    latest_capital_month = capital["month_date"].max()
    if pd.notna(latest_capital_month) and latest_capital_month < analysis_date.replace(day=1):
        issues.append(
            _issue(
                "warning",
                "working_capital_log.csv",
                "capital_snapshot_trails_analysis_date",
                f"latest={latest_capital_month.strftime('%Y-%m')}, analysis_date={analysis_date.date()}",
            )
        )

    stockout_markers = inv["po_number"].fillna("").eq("STOCKOUT-EVENT").sum()
    if stockout_markers:
        issues.append(
            _issue(
                "info",
                "inventory_transactions.csv",
                "stockout_event_markers",
                f"{stockout_markers} rows use po_number=STOCKOUT-EVENT",
            )
        )

    return pd.DataFrame(issues, columns=["severity", "file", "issue_type", "detail"])


def build_data_facts(frames: Dict[str, pd.DataFrame], analysis_date: pd.Timestamp) -> dict[str, object]:
    inv = frames["inventory_transactions"]
    orders = frames["production_orders"]
    capital = frames["working_capital_log"]
    latest_capital = latest_capital_snapshot(capital)
    return {
        "analysis_date": analysis_date.date().isoformat(),
        "inventory_rows": len(inv),
        "inventory_min_date": _date_str(inv["date"].min()),
        "inventory_max_date": _date_str(inv["date"].max()),
        "production_order_rows": len(orders),
        "delivery_min_date": _date_str(orders["delivery_date"].min()),
        "delivery_max_date": _date_str(orders["delivery_date"].max()),
        "latest_order_date": _date_str(orders["order_date"].max()),
        "latest_capital_month": latest_capital.get("month", ""),
        "latest_credit_utilized_inr": latest_capital.get("credit_utilized_inr", 0.0),
        "latest_outstanding_payables_inr": latest_capital.get("outstanding_payables_inr", 0.0),
        "latest_available_credit_inr": latest_capital.get("available_credit_inr", 0.0),
    }


def latest_capital_snapshot(working_capital_log: pd.DataFrame) -> dict[str, object]:
    capital = working_capital_log.copy()
    capital = capital.drop_duplicates("month", keep="last")
    capital = capital.sort_values("month_date")
    if capital.empty:
        return {}
    return capital.iloc[-1].to_dict()


def explode_supplier_materials(supplier_master: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for _, supplier in supplier_master.iterrows():
        materials = str(supplier["material_supplied"]).split(",")
        for material_id in materials:
            material_id = material_id.strip()
            if material_id:
                row = supplier.to_dict()
                row["material_id"] = material_id
                rows.append(row)
    return pd.DataFrame(rows)


def write_quality_report(bundle: DataBundle, output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    bundle.quality_issues.to_csv(output_dir / "data_quality_issues.csv", index=False)

    lines = [
        "# Data Quality Report",
        "",
        "## Data Facts",
        "",
    ]
    for key, value in bundle.data_facts.items():
        lines.append(f"- {key}: {value}")
    lines.extend(["", "## Issues", ""])
    if bundle.quality_issues.empty:
        lines.append("No data quality issues found.")
    else:
        for _, issue in bundle.quality_issues.iterrows():
            lines.append(
                f"- {issue['severity']} | {issue['file']} | {issue['issue_type']}: {issue['detail']}"
            )
    (output_dir / "data_quality_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _issue(severity: str, file: str, issue_type: str, detail: object) -> dict[str, object]:
    if isinstance(detail, list):
        detail = ", ".join(map(str, detail))
    return {"severity": severity, "file": file, "issue_type": issue_type, "detail": detail}


def _add_null_date_issue(
    issues: list[dict[str, object]], df: pd.DataFrame, file: str, column: str
) -> None:
    count = df[column].isna().sum()
    if count:
        issues.append(_issue("error", file, f"invalid_{column}", int(count)))


def _add_negative_issue(
    issues: list[dict[str, object]], df: pd.DataFrame, file: str, column: str
) -> None:
    count = df[column].lt(0).sum()
    if count:
        issues.append(_issue("error", file, f"negative_{column}", int(count)))


def _date_str(value: object) -> str:
    if pd.isna(value):
        return ""
    return pd.Timestamp(value).date().isoformat()
