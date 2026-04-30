from __future__ import annotations

import pandas as pd


KG_UNITS = {"kg", "kgs", "kilogram", "kilograms"}
ROLL_UNITS = {"roll", "rolls"}
PIECE_UNITS = {"pc", "pcs", "piece", "pieces", "nos", "no"}


def normalize_transactions(
    inventory_transactions: pd.DataFrame, material_master: pd.DataFrame
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    canonical_units = material_master.set_index("material_id")["unit"].to_dict()
    normalized = inventory_transactions.copy()
    normalized["original_unit"] = normalized["unit"]
    normalized["target_unit"] = normalized["material_id"].map(canonical_units)

    results = normalized.apply(
        lambda row: _conversion(row["original_unit"], row["target_unit"]), axis=1, result_type="expand"
    )
    results.columns = [
        "source_unit_normalized",
        "normalized_unit",
        "conversion_factor",
        "conversion_confidence",
        "conversion_note",
    ]
    normalized = pd.concat([normalized, results], axis=1)
    normalized["quantity_normalized"] = normalized["quantity"] * normalized["conversion_factor"]

    exceptions = normalized[normalized["conversion_factor"].isna()].copy()
    logic = (
        normalized[
            [
                "material_id",
                "target_unit",
                "original_unit",
                "source_unit_normalized",
                "normalized_unit",
                "conversion_factor",
                "conversion_confidence",
                "conversion_note",
            ]
        ]
        .drop_duplicates()
        .sort_values(["material_id", "original_unit"])
    )
    return normalized, logic, exceptions


def normalize_unit_name(unit: object) -> str:
    if pd.isna(unit):
        return ""
    return str(unit).strip().lower()


def _conversion(source_unit: object, target_unit: object) -> tuple[object, object, object, str, str]:
    source = normalize_unit_name(source_unit)
    target = normalize_unit_name(target_unit)

    if not source or not target:
        return source, target, pd.NA, "exception", "missing source or target unit"

    if target in KG_UNITS and source in KG_UNITS:
        return source, "kg", 1.0, "high", "kg spelling/case normalization"

    if target in ROLL_UNITS and source in ROLL_UNITS:
        return source, "rolls", 1.0, "high", "roll spelling normalization"

    if target in ROLL_UNITS and source in PIECE_UNITS:
        return source, "rolls", 1.0, "low", "assumption: 1 piece/nos equals 1 roll"

    if source == target:
        return source, target, 1.0, "high", "already canonical"

    return source, target, pd.NA, "exception", f"unsupported conversion from {source} to {target}"
