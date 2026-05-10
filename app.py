from __future__ import annotations

import argparse
import json
import mimetypes
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from src.config import PipelineConfig
from src.product_service import ProductService

import pandas as pd
pd.set_option('future.no_silent_downcasting', True)


ROOT = Path(__file__).resolve().parent
WEB_ROOT = ROOT / "web"


class InventoryAppHandler(SimpleHTTPRequestHandler):
    service: ProductService

    def do_OPTIONS(self) -> None:
        self.send_response(HTTPStatus.NO_CONTENT)
        self._send_cors_headers()
        self.end_headers()

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path

        routes = {
            "/api/health": lambda: {"ok": True, "app": "PackRight Inventory Intelligence"},
            "/api/overview": self.service.overview,
            "/api/decision-dashboard": self.service.decision_dashboard,
            "/api/demand-planning": self.service.demand_planning,
            "/api/inventory-management": self.service.inventory_management,
            "/api/smart-procurement": self.service.smart_procurement,
            "/api/substitutions": self.service.substitutions,
            "/api/risk-intelligence": self.service.risk_intelligence,
            "/api/advanced-forecast": self.service.advanced_forecast,
            "/api/ai-recommendations": self.service.ai_recommendations,
            "/api/simulation-lab": self.service.simulation_lab,
            "/api/data-quality": self.service.data_quality,
            "/api/alert-config": self.service.alert_config,
            "/api/alert-digest": self.service.alert_digest,
            "/api/role-alert-digests": self.service.role_alert_digests,
        }
        if path in routes:
            self._send_json(routes[path]())
            return

        if path == "/api/report":
            self._send_report()
            return

        if path == "/api/daily-report":
            self._send_daily_report()
            return

        if path == "/":
            self._send_static(WEB_ROOT / "index.html")
            return

        static_path = (WEB_ROOT / path.lstrip("/")).resolve()
        if WEB_ROOT in static_path.parents and static_path.exists() and static_path.is_file():
            self._send_static(static_path)
            return

        self._send_json({"error": "not_found", "path": path}, HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/recompute":
            self._send_json(self.service.recompute())
            return
        if parsed.path == "/api/send-alerts":
            payload = self._read_json()
            self._send_json(self.service.send_alerts(payload))
            return
        if parsed.path == "/api/send-daily-report":
            payload = self._read_json()
            self._send_json(self.service.send_daily_report(payload))
            return
        if parsed.path == "/api/run-scenario":
            payload = self._read_json()
            self._send_json(self.service.run_scenario(payload))
            return
        if parsed.path == "/api/delete-scenario":
            payload = self._read_json()
            self._send_json(self.service.delete_scenario(payload))
            return
        self._send_json({"error": "not_found", "path": parsed.path}, HTTPStatus.NOT_FOUND)

    def log_message(self, format: str, *args: object) -> None:
        print(f"{self.address_string()} - {format % args}")

    def _send_json(self, payload: object, status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self._send_cors_headers()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _send_static(self, path: Path) -> None:
        body = path.read_bytes()
        mime_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", mime_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _send_report(self) -> None:
        path = self.service.report_path()
        if not path.exists():
            self._send_json({"error": "report_not_found"}, HTTPStatus.NOT_FOUND)
            return
        body = path.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header(
            "Content-Type",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        self.send_header("Content-Disposition", 'attachment; filename="weekly_purchase_report.xlsx"')
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_daily_report(self) -> None:
        path = self.service.daily_report_path()
        if not path.exists():
            self._send_json({"error": "daily_report_not_found"}, HTTPStatus.NOT_FOUND)
            return
        body = path.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header(
            "Content-Type",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        self.send_header("Content-Disposition", 'attachment; filename="daily_risk_report.xlsx"')
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_cors_headers(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def _read_json(self) -> dict[str, object]:
        length = int(self.headers.get("Content-Length", 0))
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        try:
            return json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError:
            return {}


def make_handler(service: ProductService) -> type[InventoryAppHandler]:
    class BoundInventoryAppHandler(InventoryAppHandler):
        pass

    BoundInventoryAppHandler.service = service
    return BoundInventoryAppHandler


def main() -> None:
    parser = argparse.ArgumentParser(description="PackRight Inventory Intelligence web app")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument(
        "--recompute",
        action="store_true",
        help="Recompute pipeline outputs before serving the dashboard.",
    )
    args = parser.parse_args()

    service = ProductService(PipelineConfig())
    if args.recompute:
        service.recompute()
    else:
        service.ensure_loaded()

    server = ThreadingHTTPServer((args.host, args.port), make_handler(service))
    print(f"PackRight Inventory Intelligence running at http://{args.host}:{args.port}")
    print("Press Ctrl+C to stop.")
    server.serve_forever()


if __name__ == "__main__":
    main()
