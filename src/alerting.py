from __future__ import annotations

from dataclasses import dataclass, replace
from email.message import EmailMessage
from html import escape
import os
import smtplib
from typing import Iterable

import pandas as pd
from dotenv import load_dotenv


@dataclass(frozen=True)
class EmailSettings:
    from_email: str
    app_password: str
    recipients: tuple[str, ...]
    smtp_host: str
    smtp_port: int


def load_email_settings() -> tuple[EmailSettings | None, dict[str, object]]:
    load_dotenv()
    from_email = os.getenv("EMAIL_FROM", "").strip()
    app_password = os.getenv("EMAIL_APP_PASSWORD", "").strip()
    smtp_host = os.getenv("SMTP_HOST", "smtp.gmail.com").strip() or "smtp.gmail.com"
    smtp_port = _safe_int(os.getenv("SMTP_PORT", "587"), 587)
    recipients = tuple(_parse_recipients(os.getenv("ALERT_RECIPIENTS", "")))

    missing: list[str] = []
    if not from_email:
        missing.append("EMAIL_FROM")
    if not app_password:
        missing.append("EMAIL_APP_PASSWORD")
    if not recipients:
        missing.append("ALERT_RECIPIENTS")

    status = {
        "enabled": not missing,
        "missing": missing,
        "fromEmail": from_email,
        "recipients": list(recipients),
        "smtpHost": smtp_host,
        "smtpPort": smtp_port,
    }
    if missing:
        return None, status

    return (
        EmailSettings(
            from_email=from_email,
            app_password=app_password,
            recipients=recipients,
            smtp_host=smtp_host,
            smtp_port=smtp_port,
        ),
        status,
    )


def with_recipients(settings: EmailSettings, recipients: Iterable[str]) -> EmailSettings:
    cleaned = tuple(_parse_recipients(",".join(recipients)))
    if not cleaned:
        return settings
    return replace(settings, recipients=cleaned)


def build_alert_digest(
    analysis_date: str,
    alerts: pd.DataFrame,
    approved: pd.DataFrame,
    blocked: pd.DataFrame,
    credit: pd.DataFrame,
    substitutions: pd.DataFrame,
) -> dict[str, object]:
    alerts = alerts.copy() if not alerts.empty else pd.DataFrame()
    if not alerts.empty and "alert_type" not in alerts:
        alerts["alert_type"] = alerts.apply(_alert_type_from_flags, axis=1)

    critical_mask = alerts.get("alert_type", pd.Series([], dtype=str)).eq("less_than_3_days_stock")
    critical = alerts[critical_mask] if not alerts.empty else pd.DataFrame()
    watch = alerts[~critical_mask] if not alerts.empty else pd.DataFrame()

    approved_value = _sum(approved, "recommended_value_inr")
    blocked_value = _sum(blocked, "recommended_value_inr")
    credit_row = credit.iloc[0].to_dict() if not credit.empty else {}

    top_stockouts = _records(
        alerts.sort_values(["days_of_cover", "projected_shortage_qty"], ascending=[True, False]).head(8)
    )
    blocked_top = _records(blocked.sort_values(["recommended_value_inr"], ascending=False).head(8))
    substitution_top = _records(substitutions.head(6))

    return {
        "analysisDate": analysis_date,
        "summary": {
            "criticalCount": len(critical),
            "watchCount": len(watch),
            "approvedCount": len(approved),
            "blockedCount": len(blocked),
            "approvedValueInr": approved_value,
            "blockedValueInr": blocked_value,
            "creditCapInr": _num(credit_row.get("credit_cap_inr")),
            "remainingCreditInr": _num(credit_row.get("remaining_available_credit_inr")),
            "projectedCreditUtilizedInr": _num(credit_row.get("projected_credit_utilized_after_approved_inr")),
        },
        "topStockouts": top_stockouts,
        "blockedByCredit": blocked_top,
        "substitutionOptions": substitution_top,
    }


def build_alert_email(digest: dict[str, object]) -> tuple[str, str, str]:
    summary = digest.get("summary", {})
    analysis_date = digest.get("analysisDate", "")
    subject = f"PackRight Inventory Alerts - {analysis_date}"

    text_lines = [
        "PackRight Inventory Alerts",
        f"Analysis date: {analysis_date}",
        "",
        f"Critical (<3 days): {summary.get('criticalCount', 0)}",
        f"Stockout within 21 days: {summary.get('watchCount', 0)}",
        f"Approved PO value: {format_inr(summary.get('approvedValueInr', 0))}",
        f"Blocked PO value: {format_inr(summary.get('blockedValueInr', 0))}",
        f"Remaining credit: {format_inr(summary.get('remainingCreditInr', 0))}",
        "",
        "Top stockout risks:",
    ]

    for row in digest.get("topStockouts", []):
        text_lines.append(
            f"- {row.get('material_id')} {row.get('material_name', '')}: "
            f"{row.get('days_of_cover', '-') } days cover, "
            f"shortage {format_qty(row.get('projected_shortage_qty', 0), row.get('unit', ''))}"
        )

    text_lines.append("")
    text_lines.append("Blocked by credit:")
    for row in digest.get("blockedByCredit", []):
        text_lines.append(
            f"- {row.get('material_id')} {row.get('material_name', '')}: "
            f"{format_inr(row.get('recommended_value_inr', 0))}"
        )

    text_lines.append("")
    text_lines.append("Substitution options:")
    for row in digest.get("substitutionOptions", []):
        text_lines.append(
            f"- {row.get('source_material_id')} -> {row.get('substitute_material_id')}: "
            f"{format_qty(row.get('recommended_purchase_qty', 0), row.get('unit', ''))}"
        )

    html = _build_alert_html(digest)
    return subject, "\n".join(text_lines), html


def send_alert_email(settings: EmailSettings, subject: str, text: str, html: str) -> None:
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = settings.from_email
    message["To"] = ", ".join(settings.recipients)
    message.set_content(text)
    message.add_alternative(html, subtype="html")

    with smtplib.SMTP(settings.smtp_host, settings.smtp_port) as smtp:
        smtp.starttls()
        smtp.login(settings.from_email, settings.app_password)
        smtp.send_message(message)


def _build_alert_html(digest: dict[str, object]) -> str:
    summary = digest.get("summary", {})
    analysis_date = escape(str(digest.get("analysisDate", "")))

    def row_html(label: str, value: str) -> str:
        return f"<tr><td>{escape(label)}</td><td><strong>{escape(value)}</strong></td></tr>"

    summary_rows = "".join(
        [
            row_html("Critical (<3 days)", str(summary.get("criticalCount", 0))),
            row_html("Stockout within 21 days", str(summary.get("watchCount", 0))),
            row_html("Approved PO value", format_inr(summary.get("approvedValueInr", 0))),
            row_html("Blocked PO value", format_inr(summary.get("blockedValueInr", 0))),
            row_html("Remaining credit", format_inr(summary.get("remainingCreditInr", 0))),
        ]
    )

    stockout_rows = "".join(
        [
            "<tr>"
            f"<td>{escape(str(row.get('material_id', '')))}</td>"
            f"<td>{escape(str(row.get('material_name', '')))}</td>"
            f"<td>{escape(str(row.get('days_of_cover', '-')))}</td>"
            f"<td>{escape(format_qty(row.get('projected_shortage_qty', 0), row.get('unit', '')))}</td>"
            "</tr>"
            for row in digest.get("topStockouts", [])
        ]
    )

    blocked_rows = "".join(
        [
            "<tr>"
            f"<td>{escape(str(row.get('material_id', '')))}</td>"
            f"<td>{escape(str(row.get('material_name', '')))}</td>"
            f"<td>{escape(format_inr(row.get('recommended_value_inr', 0)))}</td>"
            "</tr>"
            for row in digest.get("blockedByCredit", [])
        ]
    )

    substitution_rows = "".join(
        [
            "<tr>"
            f"<td>{escape(str(row.get('source_material_id', '')))}</td>"
            f"<td>{escape(str(row.get('substitute_material_id', '')))}</td>"
            f"<td>{escape(format_qty(row.get('recommended_purchase_qty', 0), row.get('unit', '')))}</td>"
            "</tr>"
            for row in digest.get("substitutionOptions", [])
        ]
    )

    return f"""
<!doctype html>
<html>
  <body style="font-family: Arial, sans-serif; color: #1c1c1c;">
    <h2>PackRight Inventory Alerts</h2>
    <p>Analysis date: <strong>{analysis_date}</strong></p>

    <table cellpadding="6" cellspacing="0" style="border-collapse: collapse; width: 100%;">
      <thead>
        <tr style="background: #0e8174; color: #ffffff;">
          <th align="left">Metric</th>
          <th align="left">Value</th>
        </tr>
      </thead>
      <tbody>
        {summary_rows}
      </tbody>
    </table>

    <h3 style="margin-top: 20px;">Top stockout risks</h3>
    <table cellpadding="6" cellspacing="0" style="border-collapse: collapse; width: 100%;">
      <thead>
        <tr style="background: #e7ecef;">
          <th align="left">Material</th>
          <th align="left">Name</th>
          <th align="left">Days cover</th>
          <th align="left">Shortage</th>
        </tr>
      </thead>
      <tbody>
        {stockout_rows}
      </tbody>
    </table>

    <h3 style="margin-top: 20px;">Blocked by credit</h3>
    <table cellpadding="6" cellspacing="0" style="border-collapse: collapse; width: 100%;">
      <thead>
        <tr style="background: #e7ecef;">
          <th align="left">Material</th>
          <th align="left">Name</th>
          <th align="left">Value</th>
        </tr>
      </thead>
      <tbody>
        {blocked_rows}
      </tbody>
    </table>

    <h3 style="margin-top: 20px;">Substitution options</h3>
    <table cellpadding="6" cellspacing="0" style="border-collapse: collapse; width: 100%;">
      <thead>
        <tr style="background: #e7ecef;">
          <th align="left">From</th>
          <th align="left">To</th>
          <th align="left">Recommended qty</th>
        </tr>
      </thead>
      <tbody>
        {substitution_rows}
      </tbody>
    </table>
  </body>
</html>
"""


def _parse_recipients(raw: str) -> list[str]:
    recipients: list[str] = []
    for part in raw.replace(";", ",").split(","):
        email = part.strip()
        if email:
            recipients.append(email)
    return recipients


def _safe_int(raw: str, fallback: int) -> int:
    try:
        return int(raw)
    except (TypeError, ValueError):
        return fallback


def _alert_type_from_flags(row: pd.Series) -> str:
    if bool(row.get("under_3_days_stock")):
        return "less_than_3_days_stock"
    if bool(row.get("stockout_within_21d")):
        return "stockout_within_21_days"
    return "watch"


def _sum(frame: pd.DataFrame, column: str) -> float:
    if frame.empty or column not in frame:
        return 0.0
    return float(pd.to_numeric(frame[column], errors="coerce").fillna(0).sum())


def _num(value: object) -> float:
    try:
        if value is None or pd.isna(value):
            return 0.0
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _records(frame: pd.DataFrame) -> list[dict[str, object]]:
    if frame.empty:
        return []
    clean = frame.replace({pd.NA: None})
    clean = clean.where(pd.notna(clean), None)
    return clean.to_dict(orient="records")


def format_inr(value: object) -> str:
    n = _num(value)
    if abs(n) >= 10_000_000:
        return f"INR {n / 10_000_000:.2f} Cr"
    if abs(n) >= 100_000:
        return f"INR {n / 100_000:.2f} L"
    return f"INR {n:,.0f}"


def format_qty(value: object, unit: str) -> str:
    n = _num(value)
    unit = unit or ""
    if abs(n) >= 1_000_000:
        return f"{n / 1_000_000:.2f}M {unit}".strip()
    if abs(n) >= 1_000:
        return f"{n / 1_000:.1f}K {unit}".strip()
    return f"{n:.0f} {unit}".strip()
