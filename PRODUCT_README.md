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
- `POST /api/recompute`
