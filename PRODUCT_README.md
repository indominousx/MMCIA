# PackRight Inventory Intelligence Product

Run the analytics pipeline:

```powershell
python run_pipeline.py
```

Run the backend and dashboard:

```powershell
python app.py --host 127.0.0.1 --port 8000
```

Open:

```text
http://127.0.0.1:8000
```

API modules:
- `/api/demand-planning`
- `/api/inventory-management`
- `/api/smart-procurement`
- `/api/decision-dashboard`
- `/api/substitutions`
- `/api/data-quality`
- `/api/report`
- `/api/daily-report`
- `/api/role-alert-digests`
- `POST /api/recompute`
- `POST /api/send-alerts`
- `POST /api/send-daily-report`

Email configuration for Gmail App Password SMTP:

```text
EMAIL_FROM=your-gmail-address
EMAIL_APP_PASSWORD=your-google-app-password
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
ALERT_RECIPIENTS=ops@example.com
PRODUCTION_ALERT_RECIPIENTS=production@example.com
FINANCE_ALERT_RECIPIENTS=finance@example.com
PROCUREMENT_ALERT_RECIPIENTS=procurement@example.com
DAILY_REPORT_RECIPIENTS=ops@example.com
```

Role alert emails are risk-gated. A role receives mail only when its domain has active risk:
production for stockout/substitution risk, finance for credit risk, and procurement for purchase-action risk.

For deployed daily reports, schedule this command with the hosting scheduler, cron, Windows Task Scheduler, systemd timer, or a Kubernetes CronJob:

```powershell
python send_daily_report.py --recompute
```
