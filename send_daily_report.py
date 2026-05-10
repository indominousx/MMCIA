from __future__ import annotations

import argparse
import sys

from src.config import PipelineConfig
from src.product_service import ProductService


def main() -> int:
    parser = argparse.ArgumentParser(description="Send the PackRight daily inventory risk report.")
    parser.add_argument(
        "--recompute",
        action="store_true",
        help="Recompute pipeline outputs before building and sending the daily report.",
    )
    args = parser.parse_args()

    service = ProductService(PipelineConfig())
    if args.recompute:
        service.recompute()
    else:
        service.ensure_loaded()

    result = service.send_daily_report({})
    if not result.get("ok"):
        print(f"Daily report send failed: {result.get('error')}")
        detail = result.get("detail") or result.get("missing")
        if detail:
            print(detail)
        return 1

    print(f"Daily report sent to: {', '.join(result.get('recipients', []))}")
    print(f"Report path: {result.get('reportPath')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
