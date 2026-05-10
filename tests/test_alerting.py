from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from src.alerting import (
    EmailSettings,
    build_alert_digest,
    build_role_risk_digest,
    load_email_settings,
    recipients_for_role,
    send_alert_email,
)


class AlertingTests(unittest.TestCase):
    def test_role_recipients_use_specific_group_then_fallback(self) -> None:
        env = {
            "EMAIL_FROM": "packright@example.com",
            "EMAIL_APP_PASSWORD": "app-password",
            "ALERT_RECIPIENTS": "ops@example.com",
            "PRODUCTION_ALERT_RECIPIENTS": "prod@example.com; planner@example.com",
            "FINANCE_ALERT_RECIPIENTS": "",
            "PROCUREMENT_ALERT_RECIPIENTS": "buy@example.com",
        }
        with patch.dict(os.environ, env, clear=True):
            settings, status = load_email_settings()

        self.assertIsNotNone(settings)
        assert settings is not None
        self.assertTrue(status["enabled"])
        self.assertEqual(recipients_for_role(settings, "production"), ("prod@example.com", "planner@example.com"))
        self.assertEqual(recipients_for_role(settings, "finance"), ("ops@example.com",))
        self.assertEqual(recipients_for_role(settings, "procurement"), ("buy@example.com",))

    def test_production_digest_sends_only_for_stockout_or_substitution_risk(self) -> None:
        frames = _empty_frames()
        digest = build_role_risk_digest("production", "2024-01-01", frames)
        self.assertFalse(digest["hasRisk"])

        frames["stockout_alerts_21d"] = pd.DataFrame(
            [
                {
                    "material_id": "M01",
                    "material_name": "Kraft Paper - Grade A",
                    "under_3_days_stock": "False",
                    "stockout_within_21d": "False",
                },
                {
                    "material_id": "M05",
                    "material_name": "Corrugating Medium",
                    "under_3_days_stock": "True",
                    "stockout_within_21d": "True",
                },
            ]
        )
        digest = build_role_risk_digest("production", "2024-01-01", frames)
        self.assertTrue(digest["hasRisk"])
        self.assertEqual(len(digest["sections"]["stockouts"]), 1)
        self.assertEqual(digest["sections"]["stockouts"][0]["material_id"], "M05")

    def test_finance_and_procurement_gates_are_domain_specific(self) -> None:
        frames = _empty_frames()
        self.assertFalse(build_role_risk_digest("finance", "2024-01-01", frames)["hasRisk"])
        self.assertFalse(build_role_risk_digest("procurement", "2024-01-01", frames)["hasRisk"])

        frames["credit_summary"] = pd.DataFrame(
            [
                {
                    "credit_cap_inr": 3_000_000,
                    "projected_credit_utilized_after_approved_inr": 2_950_000,
                    "remaining_available_credit_inr": 50_000,
                }
            ]
        )
        self.assertTrue(build_role_risk_digest("finance", "2024-01-01", frames)["hasRisk"])

        frames["procurement_recommendations"] = pd.DataFrame(
            [
                {
                    "material_id": "M05",
                    "material_name": "Corrugating Medium",
                    "action_timing": "immediate",
                    "can_arrive_before_stockout": False,
                    "recommended_qty": 15,
                    "required_qty": 10,
                    "moq": 15,
                }
            ]
        )
        self.assertTrue(build_role_risk_digest("procurement", "2024-01-01", frames)["hasRisk"])

    def test_alert_digest_reports_total_21_day_alerts_and_critical_subset(self) -> None:
        frames = _empty_frames()
        frames["stockout_alerts_21d"] = pd.DataFrame(
            [
                {
                    "material_id": "M01",
                    "material_name": "Kraft Paper - Grade A",
                    "under_3_days_stock": "True",
                    "stockout_within_21d": "True",
                },
                {
                    "material_id": "M02",
                    "material_name": "Kraft Paper - Grade B",
                    "under_3_days_stock": "False",
                    "stockout_within_21d": "True",
                },
            ]
        )

        digest = build_alert_digest(
            "2024-01-01",
            frames["stockout_alerts_21d"],
            frames["procurement_recommendations"],
            frames["procurement_blocked_by_credit"],
            frames["credit_summary"],
            frames["substitution_recommendations"],
        )

        self.assertEqual(digest["summary"]["criticalCount"], 1)
        self.assertEqual(digest["summary"]["watchCount"], 1)
        self.assertEqual(digest["summary"]["stockoutAlertCount"], 2)

    def test_send_alert_email_attaches_xlsx(self) -> None:
        sent_messages = []

        class FakeSMTP:
            def __init__(self, host: str, port: int) -> None:
                self.host = host
                self.port = port

            def __enter__(self) -> "FakeSMTP":
                return self

            def __exit__(self, exc_type, exc, tb) -> None:
                return None

            def starttls(self) -> None:
                return None

            def login(self, from_email: str, app_password: str) -> None:
                return None

            def send_message(self, message) -> None:
                sent_messages.append(message)

        settings = EmailSettings(
            from_email="packright@example.com",
            app_password="app-password",
            recipients=("ops@example.com",),
            role_recipients={},
            smtp_host="smtp.gmail.com",
            smtp_port=587,
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            attachment = Path(temp_dir) / "daily_risk_report.xlsx"
            attachment.write_bytes(b"fake-xlsx")
            with patch("src.alerting.smtplib.SMTP", FakeSMTP):
                send_alert_email(settings, "subject", "text", "<p>html</p>", attachments=[attachment])

        self.assertEqual(len(sent_messages), 1)
        attachments = [
            part
            for part in sent_messages[0].iter_attachments()
            if part.get_filename() == "daily_risk_report.xlsx"
        ]
        self.assertEqual(len(attachments), 1)
        self.assertEqual(
            attachments[0].get_content_type(),
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )


def _empty_frames() -> dict[str, pd.DataFrame]:
    return {
        "stockout_alerts_21d": pd.DataFrame(),
        "procurement_recommendations": pd.DataFrame(),
        "procurement_blocked_by_credit": pd.DataFrame(),
        "credit_summary": pd.DataFrame(),
        "substitution_recommendations": pd.DataFrame(),
    }


if __name__ == "__main__":
    unittest.main()
