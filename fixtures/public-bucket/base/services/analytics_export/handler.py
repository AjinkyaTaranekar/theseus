"""analytics-export: the nightly export to the data lake.

EventBridge starts it at 03:00 UTC, after the billing run. It dumps the previous day's orders to the lake's
`raw/` zone, reads them back, and writes daily sales aggregates to `curated/`, which the analysts query. Raw
holds customer IDs; curated holds aggregates only, which is why analysts may read curated and not raw.
"""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime, timedelta
from typing import Any

from analytics_export import export

log = logging.getLogger()
log.setLevel(logging.INFO)


def _export_day(event: dict[str, Any]) -> date:
    """The day to export: the event's `day` when re-run by hand, else yesterday in UTC."""
    if "day" in event:
        return date.fromisoformat(event["day"])
    return (datetime.now(UTC) - timedelta(days=1)).date()


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    day = _export_day(event)
    orders = export.dump_orders(day)
    raw_key = export.write_raw(day, orders)

    # Read back what was written, so the aggregates come from exactly the raw file the analysts can audit.
    rows = export.read_raw(day)
    if len(rows) != len(orders):
        log.error("raw file for %s has %d rows, expected %d", day, len(rows), len(orders))
        raise RuntimeError(f"raw export for {day} is incomplete")

    totals = export.aggregate(rows)
    curated_key = export.write_curated(day, totals)
    log.info("exported %d orders for %s to %s and %s", len(orders), day, raw_key, curated_key)
    return {"day": day.isoformat(), "orders": len(orders), "raw": raw_key, "curated": curated_key}
