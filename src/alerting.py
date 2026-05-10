from __future__ import annotations

from dataclasses import dataclass, replace
from email.message import EmailMessage
from html import escape
import mimetypes
import os
from pathlib import Path
import smtplib
from typing import Iterable

import pandas as pd
from dotenv import load_dotenv


@dataclass(frozen=True)
class EmailSettings:
    from_email: str
    app_password: str
    recipients: tuple[str, ...]
    role_recipients: dict[str, tuple[str, ...]]
    smtp_host: str
    smtp_port: int


ROLE_ENV_KEYS = {
    "production": "PRODUCTION_ALERT_RECIPIENTS",
    "finance": "FINANCE_ALERT_RECIPIENTS",
    "procurement": "PROCUREMENT_ALERT_RECIPIENTS",
}
ROLE_LABELS = {
    "production": "Production",
    "finance": "Finance",
    "procurement": "Procurement",
}


def load_email_settings() -> tuple[EmailSettings | None, dict[str, object]]:
    load_dotenv()
    from_email = os.getenv("EMAIL_FROM", "").strip()
    app_password = os.getenv("EMAIL_APP_PASSWORD", "").strip()
    smtp_host = os.getenv("SMTP_HOST", "smtp.gmail.com").strip() or "smtp.gmail.com"
    smtp_port = _safe_int(os.getenv("SMTP_PORT", "587"), 587)
    recipients = tuple(_parse_recipients(os.getenv("ALERT_RECIPIENTS", "")))
    role_recipients = {
        role: tuple(_parse_recipients(os.getenv(env_key, "")))
        for role, env_key in ROLE_ENV_KEYS.items()
    }
    any_recipients = any(role_recipients.values()) or bool(recipients)

    missing: list[str] = []
    if not from_email:
        missing.append("EMAIL_FROM")
    if not app_password:
        missing.append("EMAIL_APP_PASSWORD")
    if not any_recipients:
        missing.append("ALERT_RECIPIENTS or role recipient env vars")

    status = {
        "enabled": not missing,
        "missing": missing,
        "fromEmail": from_email,
        "recipients": list(recipients),
        "roleRecipients": {
            role: list(addresses or recipients)
            for role, addresses in role_recipients.items()
        },
        "roleRecipientSources": {
            role: "role" if addresses else ("fallback" if recipients else "missing")
            for role, addresses in role_recipients.items()
        },
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
            role_recipients=role_recipients,
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


def recipients_for_role(settings: EmailSettings, role: str) -> tuple[str, ...]:
    return settings.role_recipients.get(role) or settings.recipients


def daily_report_recipients(settings: EmailSettings) -> tuple[str, ...]:
    explicit = tuple(_parse_recipients(os.getenv("DAILY_REPORT_RECIPIENTS", "")))
    if explicit:
        return explicit
    merged: list[str] = []
    for addresses in settings.role_recipients.values():
        for address in addresses:
            if address not in merged:
                merged.append(address)
    for address in settings.recipients:
        if address not in merged:
            merged.append(address)
    return tuple(merged)


def build_role_risk_digest(
    role: str,
    analysis_date: str,
    data_frames: dict[str, pd.DataFrame],
    *,
    credit_utilization_threshold: float = 0.90,
    remaining_credit_threshold_inr: float = 100_000.0,
) -> dict[str, object]:
    role = role.lower().strip()
    alerts = data_frames.get("stockout_alerts_21d", pd.DataFrame()).copy()
    approved = data_frames.get("procurement_recommendations", pd.DataFrame()).copy()
    blocked = data_frames.get("procurement_blocked_by_credit", pd.DataFrame()).copy()
    credit = data_frames.get("credit_summary", pd.DataFrame()).copy()
    substitutions = data_frames.get("substitution_recommendations", pd.DataFrame()).copy()

    if not alerts.empty and "alert_type" not in alerts:
        alerts["alert_type"] = alerts.apply(_alert_type_from_flags, axis=1)

    digest: dict[str, object] = {
        "role": role,
        "roleLabel": ROLE_LABELS.get(role, role.title()),
        "analysisDate": analysis_date,
        "hasRisk": False,
        "riskReasons": [],
        "summary": _role_summary(alerts, approved, blocked, credit, substitutions),
        "sections": {},
    }

    if role == "production":
        critical = _production_alerts(alerts)
        substitution_top = substitutions.head(8)
        m01_m02 = _m01_m02_substitutions(substitutions)
        sorted_critical = _sort_if_possible(
            critical,
            ["days_of_cover", "projected_shortage_qty"],
            [True, False],
        )
        has_risk = not critical.empty or not substitution_top.empty
        reasons = []
        if not critical.empty:
            reasons.append("stockout_or_under_3_days_stock")
        if not substitution_top.empty:
            reasons.append("substitution_recommendation")
        digest.update(
            {
                "hasRisk": has_risk,
                "riskReasons": reasons,
                "sections": {
                    "stockouts": _records(sorted_critical.head(10)),
                    "substitutions": _records(substitution_top),
                    "m01ToM02": _records(m01_m02),
                },
            }
        )
        return digest

    if role == "finance":
        credit_row = credit.iloc[0].to_dict() if not credit.empty else {}
        cap = _num(credit_row.get("credit_cap_inr"))
        utilized = _num(credit_row.get("projected_credit_utilized_after_approved_inr"))
        remaining = _num(credit_row.get("remaining_available_credit_inr"))
        utilization = 0.0 if cap <= 0 else utilized / cap
        low_credit = remaining <= remaining_credit_threshold_inr if cap > 0 else False
        near_cap = utilization >= credit_utilization_threshold if cap > 0 else False
        has_risk = not blocked.empty or low_credit or near_cap
        reasons = []
        if not blocked.empty:
            reasons.append("credit_blocked_recommendations")
        if near_cap:
            reasons.append("credit_utilization_near_cap")
        if low_credit:
            reasons.append("remaining_credit_low")
        digest.update(
            {
                "hasRisk": has_risk,
                "riskReasons": reasons,
                "summary": {
                    **digest["summary"],
                    "creditUtilizationPct": round(utilization * 100, 1),
                    "remainingCreditLow": low_credit,
                    "creditNearCap": near_cap,
                },
                "sections": {
                    "blockedByCredit": _records(
                        _sort_if_possible(blocked, ["recommended_value_inr"], [False]).head(10)
                    ),
                    "creditSummary": _records(credit),
                },
            }
        )
        return digest

    if role == "procurement":
        immediate = _immediate_procurement(approved)
        lead_time_misses = _lead_time_misses(approved)
        moq_lines = _moq_rounded_lines(approved)
        blocked_top = blocked.head(10)
        has_risk = (
            not immediate.empty
            or not lead_time_misses.empty
            or not moq_lines.empty
            or not blocked_top.empty
        )
        reasons = []
        if not immediate.empty:
            reasons.append("immediate_purchase_actions")
        if not lead_time_misses.empty:
            reasons.append("supplier_cannot_arrive_before_stockout")
        if not moq_lines.empty:
            reasons.append("moq_rounded_recommendations")
        if not blocked_top.empty:
            reasons.append("blocked_purchase_lines")
        digest.update(
            {
                "hasRisk": has_risk,
                "riskReasons": reasons,
                "sections": {
                    "immediateActions": _records(immediate.head(10)),
                    "leadTimeMisses": _records(lead_time_misses.head(10)),
                    "moqRounded": _records(moq_lines.head(10)),
                    "blockedLines": _records(blocked_top),
                },
            }
        )
        return digest

    digest["riskReasons"] = ["unknown_role"]
    return digest


def build_role_alert_email(digest: dict[str, object]) -> tuple[str, str, str]:
    role_label = str(digest.get("roleLabel", "Role"))
    analysis_date = str(digest.get("analysisDate", ""))
    subject = f"PackRight {role_label} Risk Alerts - {analysis_date}"
    summary = digest.get("summary", {})

    text_lines = [
        f"PackRight {role_label} Risk Alerts",
        f"Analysis date: {analysis_date}",
        "",
        f"Critical stockouts: {summary.get('criticalStockoutCount', 0)}",
        f"21-day stockout alerts: {summary.get('stockoutAlertCount', 0)}",
        f"Approved PO value: {format_inr(summary.get('approvedValueInr', 0))}",
        f"Blocked PO value: {format_inr(summary.get('blockedValueInr', 0))}",
        f"Remaining credit: {format_inr(summary.get('remainingCreditInr', 0))}",
        "",
    ]

    sections = digest.get("sections", {})
    if isinstance(sections, dict):
        for label, rows in sections.items():
            if not rows:
                continue
            text_lines.append(_section_title(label))
            for row in rows[:8]:
                if isinstance(row, dict):
                    text_lines.append(f"- {_row_summary(row)}")
            text_lines.append("")

    return subject, "\n".join(text_lines).strip(), _build_role_alert_html(digest)


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
    stockout_count = len(alerts)

    approved_value = _sum(approved, "recommended_value_inr")
    blocked_value = _sum(blocked, "recommended_value_inr")
    credit_row = credit.iloc[0].to_dict() if not credit.empty else {}

    top_stockouts = _records(
        _sort_if_possible(alerts, ["days_of_cover", "projected_shortage_qty"], [True, False]).head(8)
    )
    blocked_top = _records(_sort_if_possible(blocked, ["recommended_value_inr"], [False]).head(8))
    substitution_top = _records(substitutions.head(6))

    return {
        "analysisDate": analysis_date,
        "summary": {
            "criticalCount": len(critical),
            "watchCount": len(watch),
            "stockoutAlertCount": stockout_count,
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
        f"21-day stockout alerts: {summary.get('stockoutAlertCount', summary.get('watchCount', 0))}",
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


def send_alert_email(
    settings: EmailSettings,
    subject: str,
    text: str,
    html: str,
    attachments: Iterable[Path] | None = None,
) -> None:
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = settings.from_email
    message["To"] = ", ".join(settings.recipients)
    message.set_content(text)
    message.add_alternative(html, subtype="html")
    for attachment in attachments or []:
        path = Path(attachment)
        maintype, subtype = _attachment_type(path)
        message.add_attachment(
            path.read_bytes(),
            maintype=maintype,
            subtype=subtype,
            filename=path.name,
        )

    with smtplib.SMTP(settings.smtp_host, settings.smtp_port) as smtp:
        smtp.starttls()
        smtp.login(settings.from_email, settings.app_password)
        smtp.send_message(message)


def build_daily_report_email(
    analysis_date: str,
    digest: dict[str, object],
    report_path: Path,
) -> tuple[str, str, str]:
    summary = digest.get("summary", {})
    subject = f"PackRight Daily Inventory Risk Report - {analysis_date}"
    text = "\n".join(
        [
            "PackRight Daily Inventory Risk Report",
            f"Analysis date: {analysis_date}",
            f"Attached report: {report_path.name}",
            "",
            f"Critical (<3 days): {summary.get('criticalCount', 0)}",
            f"21-day stockout alerts: {summary.get('stockoutAlertCount', summary.get('watchCount', 0))}",
            f"Approved PO value: {format_inr(summary.get('approvedValueInr', 0))}",
            f"Blocked PO value: {format_inr(summary.get('blockedValueInr', 0))}",
            f"Remaining credit: {format_inr(summary.get('remainingCreditInr', 0))}",
        ]
    )
    html = f"""
<!doctype html>
<html>
  <body style="font-family: Arial, sans-serif; color: #1c1c1c;">
    <h2>PackRight Daily Inventory Risk Report</h2>
    <p>Analysis date: <strong>{escape(str(analysis_date))}</strong></p>
    <p>The daily XLSX report is attached as <strong>{escape(report_path.name)}</strong>.</p>
    {_summary_table(summary)}
  </body>
</html>
"""
    return subject, text, html


def _build_alert_html(digest: dict[str, object]) -> str:
    summary = digest.get("summary", {})
    analysis_date = escape(str(digest.get("analysisDate", "")))

    def row_html(label: str, value: str) -> str:
        return f"<tr><td>{escape(label)}</td><td><strong>{escape(value)}</strong></td></tr>"

    summary_rows = "".join(
        [
            row_html("Critical (<3 days)", str(summary.get("criticalCount", 0))),
            row_html(
                "21-day stockout alerts",
                str(summary.get("stockoutAlertCount", summary.get("watchCount", 0))),
            ),
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


def _build_role_alert_html(digest: dict[str, object]) -> str:
    role_label = escape(str(digest.get("roleLabel", "Role")))
    analysis_date = escape(str(digest.get("analysisDate", "")))
    summary = digest.get("summary", {})
    sections = digest.get("sections", {})
    if not isinstance(sections, dict):
        sections = {}

    section_html = []
    for key, rows in sections.items():
        if not rows:
            continue
        section_html.append(
            f"<h3 style=\"margin-top: 20px;\">{escape(_section_title(key))}</h3>"
            f"{_generic_rows_table(rows)}"
        )

    return f"""
<!doctype html>
<html>
  <body style="font-family: Arial, sans-serif; color: #1c1c1c;">
    <h2>PackRight {role_label} Risk Alerts</h2>
    <p>Analysis date: <strong>{analysis_date}</strong></p>
    {_summary_table(summary)}
    {''.join(section_html)}
  </body>
</html>
"""


def _summary_table(summary: object) -> str:
    if not isinstance(summary, dict):
        summary = {}
    rows = [
        ("Critical stockouts", str(summary.get("criticalStockoutCount", summary.get("criticalCount", 0)))),
        ("21-day stockout alerts", str(summary.get("stockoutAlertCount", summary.get("watchCount", 0)))),
        ("Approved PO value", format_inr(summary.get("approvedValueInr", 0))),
        ("Blocked PO value", format_inr(summary.get("blockedValueInr", 0))),
        ("Remaining credit", format_inr(summary.get("remainingCreditInr", 0))),
    ]
    if "creditUtilizationPct" in summary:
        rows.append(("Credit utilization", f"{summary.get('creditUtilizationPct', 0)}%"))
    body = "".join(
        f"<tr><td>{escape(label)}</td><td><strong>{escape(value)}</strong></td></tr>"
        for label, value in rows
    )
    return f"""
    <table cellpadding="6" cellspacing="0" style="border-collapse: collapse; width: 100%;">
      <thead>
        <tr style="background: #0e8174; color: #ffffff;">
          <th align="left">Metric</th>
          <th align="left">Value</th>
        </tr>
      </thead>
      <tbody>{body}</tbody>
    </table>
"""


def _generic_rows_table(rows: object) -> str:
    if not isinstance(rows, list) or not rows:
        return "<p>No rows.</p>"
    records = [row for row in rows if isinstance(row, dict)]
    if not records:
        return "<p>No rows.</p>"
    headers = _preferred_headers(records)
    header_html = "".join(f"<th align=\"left\">{escape(_labelize(key))}</th>" for key in headers)
    body_html = "".join(
        "<tr>"
        + "".join(f"<td>{escape(_display_value(key, row.get(key)))}</td>" for key in headers)
        + "</tr>"
        for row in records
    )
    return f"""
    <table cellpadding="6" cellspacing="0" style="border-collapse: collapse; width: 100%;">
      <thead><tr style="background: #e7ecef;">{header_html}</tr></thead>
      <tbody>{body_html}</tbody>
    </table>
"""


def _preferred_headers(records: list[dict[str, object]]) -> list[str]:
    priority = [
        "material_id",
        "material_name",
        "supplier_name",
        "first_stockout_date",
        "days_to_stockout",
        "days_of_cover",
        "recommended_qty",
        "unit",
        "recommended_value_inr",
        "remaining_available_credit_inr",
        "credit_status",
        "source_material_id",
        "substitute_material_id",
        "risk_note",
    ]
    keys = []
    all_keys = {key for row in records for key in row}
    for key in priority:
        if key in all_keys:
            keys.append(key)
    for key in sorted(all_keys):
        if key not in keys and len(keys) < 8:
            keys.append(key)
    return keys[:8]


def _display_value(key: str, value: object) -> str:
    if key.endswith("_inr") or key in {"recommended_value_inr", "remaining_available_credit_inr"}:
        return format_inr(value)
    if key in {"recommended_qty", "projected_shortage_qty", "substitute_current_stock"}:
        return format_qty(value, "")
    if value is None:
        return ""
    return str(value)


def _labelize(value: str) -> str:
    return value.replace("_", " ").title()


def _section_title(value: str) -> str:
    titles = {
        "stockouts": "Stockout Risks",
        "substitutions": "Substitution Options",
        "m01ToM02": "M01 To M02 Substitution",
        "blockedByCredit": "Blocked By Credit",
        "creditSummary": "Credit Summary",
        "immediateActions": "Immediate Purchase Actions",
        "leadTimeMisses": "Supplier Lead-Time Misses",
        "moqRounded": "MOQ-Rounded Recommendations",
        "blockedLines": "Blocked Purchase Lines",
    }
    return titles.get(value, _labelize(value))


def _row_summary(row: dict[str, object]) -> str:
    material = " ".join(
        str(row.get(key, "")).strip()
        for key in ("material_id", "material_name")
        if str(row.get(key, "")).strip()
    )
    supplier = str(row.get("supplier_name", "") or "").strip()
    if "recommended_value_inr" in row:
        value = format_inr(row.get("recommended_value_inr"))
        return f"{material or supplier}: {value}".strip(": ")
    if "projected_shortage_qty" in row:
        shortage = format_qty(row.get("projected_shortage_qty"), str(row.get("unit", "")))
        return f"{material}: {row.get('days_of_cover', '-')} days cover, shortage {shortage}"
    if "source_material_id" in row or "substitute_material_id" in row:
        qty = format_qty(row.get("recommended_purchase_qty"), str(row.get("unit", "")))
        return f"{row.get('source_material_id')} -> {row.get('substitute_material_id')}: {qty}"
    return material or supplier or ", ".join(f"{key}={value}" for key, value in list(row.items())[:3])


def _role_summary(
    alerts: pd.DataFrame,
    approved: pd.DataFrame,
    blocked: pd.DataFrame,
    credit: pd.DataFrame,
    substitutions: pd.DataFrame,
) -> dict[str, object]:
    critical = _production_alerts(alerts)
    credit_row = credit.iloc[0].to_dict() if not credit.empty else {}
    return {
        "criticalStockoutCount": len(critical),
        "stockoutAlertCount": len(alerts),
        "approvedCount": len(approved),
        "blockedCount": len(blocked),
        "substitutionCount": len(substitutions),
        "approvedValueInr": _sum(approved, "recommended_value_inr"),
        "blockedValueInr": _sum(blocked, "recommended_value_inr"),
        "creditCapInr": _num(credit_row.get("credit_cap_inr")),
        "remainingCreditInr": _num(credit_row.get("remaining_available_credit_inr")),
        "projectedCreditUtilizedInr": _num(credit_row.get("projected_credit_utilized_after_approved_inr")),
    }


def _production_alerts(alerts: pd.DataFrame) -> pd.DataFrame:
    if alerts.empty:
        return alerts
    under_3 = alerts.get("under_3_days_stock", pd.Series(False, index=alerts.index)).apply(_truthy)
    within_21 = alerts.get("stockout_within_21d", pd.Series(False, index=alerts.index)).apply(_truthy)
    alert_type = alerts.get("alert_type", pd.Series("", index=alerts.index)).astype(str)
    type_risk = alert_type.str.contains("less_than_3_days|stockout_within_21", case=False, na=False)
    return alerts[under_3 | within_21 | type_risk]


def _m01_m02_substitutions(substitutions: pd.DataFrame) -> pd.DataFrame:
    if substitutions.empty:
        return substitutions
    source = substitutions.get("source_material_id", pd.Series("", index=substitutions.index)).astype(str)
    substitute = substitutions.get("substitute_material_id", pd.Series("", index=substitutions.index)).astype(str)
    return substitutions[(source == "M01") & (substitute == "M02")]


def _immediate_procurement(approved: pd.DataFrame) -> pd.DataFrame:
    if approved.empty or "action_timing" not in approved:
        return approved.head(0)
    return approved[approved["action_timing"].astype(str).str.lower().eq("immediate")]


def _lead_time_misses(approved: pd.DataFrame) -> pd.DataFrame:
    if approved.empty or "can_arrive_before_stockout" not in approved:
        return approved.head(0)
    can_arrive = approved["can_arrive_before_stockout"].apply(_truthy)
    return approved[~can_arrive]


def _moq_rounded_lines(approved: pd.DataFrame) -> pd.DataFrame:
    if approved.empty or not {"recommended_qty", "required_qty", "moq"}.issubset(approved.columns):
        return approved.head(0)
    recommended = pd.to_numeric(approved["recommended_qty"], errors="coerce").fillna(0)
    required = pd.to_numeric(approved["required_qty"], errors="coerce").fillna(0)
    moq = pd.to_numeric(approved["moq"], errors="coerce").fillna(0)
    return approved[(moq > 0) & (recommended > required)]


def _truthy(value: object) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in {"true", "1", "yes", "y"}
    return bool(value)


def _sort_if_possible(frame: pd.DataFrame, by: list[str], ascending: list[bool]) -> pd.DataFrame:
    if frame.empty or not set(by).issubset(frame.columns):
        return frame
    return frame.sort_values(by, ascending=ascending)


def _attachment_type(path: Path) -> tuple[str, str]:
    guessed = mimetypes.guess_type(path.name)[0]
    if guessed:
        maintype, subtype = guessed.split("/", 1)
        return maintype, subtype
    if path.suffix.lower() == ".xlsx":
        return "application", "vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    return "application", "octet-stream"


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
    if _truthy(row.get("under_3_days_stock")):
        return "less_than_3_days_stock"
    if _truthy(row.get("stockout_within_21d")):
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
