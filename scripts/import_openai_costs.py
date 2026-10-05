"""Import captured OpenAI Costs pages offline; never loads keys or sends requests.

The export binds the UTC query window, grouping and original pagination cursors.
Only unfiltered project/key totals are admitted. Line-item partitions are added
once with Decimal. Native Costs pages do not prove billing settlement, so the
normalized result always remains pending. Existing v1 evidence is unchanged.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
import sys
from decimal import Decimal

from scripts import sermon_cost_isolation as costs

VERSION = "sermon-openai-costs-export-v1"


def _cursor(value):
    if value is not None and (not isinstance(value, str) or not value or len(value) > 2048):
        costs._fail("invalid_native_cursor")
    return value


def _page_id(cursor):
    # Never echo provider cursors (or accidental sensitive input).
    return "native_" + hashlib.sha256(json.dumps(cursor).encode()).hexdigest()


def _timestamp(value):
    if type(value) is not int or value < 0 or value % 86400:
        costs._fail("invalid_native_daily_interval")
    try:
        return dt.datetime.fromtimestamp(value, dt.timezone.utc).date()
    except (ValueError, OverflowError, OSError):
        costs._fail("invalid_native_daily_interval")


def normalize(config, export):
    """Return existing daily_costs v1 input; do not infer key IDs or settlement."""
    costs.validate_config(config)
    costs._object(export, ("schemaVersion", "queryWindow", "groupBy", "pages"))
    if export["schemaVersion"] != VERSION:
        costs._fail("unsupported_native_export_schema")
    window = costs._window(export["queryWindow"])
    groups = export["groupBy"]
    if (not isinstance(groups, list) or not groups or any(not isinstance(g, str) for g in groups)
            or len(groups) != len(set(groups)) or "project_id" not in groups
            or set(groups) - {"project_id", "api_key_id", "line_item"}):
        costs._fail("unsupported_native_grouping")
    if not isinstance(export["pages"], list) or not export["pages"]:
        costs._fail("invalid_native_pages")
    pages, cursors, seen_days, result_dimensions = [], set(), set(), set()
    expected_cursor = None
    for index, captured in enumerate(export["pages"]):
        costs._object(captured, ("requestCursor", "response"))
        cursor = _cursor(captured["requestCursor"])
        if cursor != expected_cursor or cursor in cursors:
            costs._fail("broken_native_page_chain")
        cursors.add(cursor)
        response = captured["response"]
        costs._object(response, ("object", "data", "has_more"), ("next_page",))
        if response["object"] != "page" or not isinstance(response["data"], list) or type(response["has_more"]) is not bool:
            costs._fail("invalid_native_page")
        next_cursor = _cursor(response.get("next_page"))
        if response["has_more"] != (next_cursor is not None) or (next_cursor is not None and next_cursor in cursors):
            costs._fail("invalid_native_pagination")
        if index < len(export["pages"]) - 1 and not response["has_more"]:
            costs._fail("broken_native_page_chain")
        totals = {}
        for bucket in response["data"]:
            costs._object(bucket, ("object", "start_time", "end_time", "results"))
            day = _timestamp(bucket["start_time"])
            end = _timestamp(bucket["end_time"])
            if bucket["object"] != "bucket" or end.toordinal() - day.toordinal() != 1 or not isinstance(bucket["results"], list):
                costs._fail("invalid_native_daily_interval")
            if not window[0] <= day < window[1] or day in seen_days:
                costs._fail("duplicate_or_outside_native_day")
            seen_days.add(day)
            for row in bucket["results"]:
                costs._object(row, ("object", "amount"), ("project_id", "api_key_id", "line_item", "quantity", "quantity_unit"))
                if row["object"] != "organization.costs.result":
                    costs._fail("not_native_cost_result")
                quantity = row.get("quantity")
                if quantity is not None and (isinstance(quantity, bool)
                        or not isinstance(quantity, (int, float, Decimal))
                        or (isinstance(quantity, float) and not math.isfinite(quantity))
                        or (isinstance(quantity, Decimal) and not quantity.is_finite())):
                    costs._fail("invalid_native_quantity")
                if row.get("quantity_unit") is not None and not isinstance(row["quantity_unit"], str):
                    costs._fail("invalid_native_quantity_unit")
                project = costs._label(row.get("project_id"), nullable=True)
                key = costs._label(row.get("api_key_id"), nullable=True)
                line = row.get("line_item")
                if line is not None and (not isinstance(line, str) or not line or len(line) > 512):
                    costs._fail("invalid_native_line_item")
                if ("api_key_id" not in groups and key is not None) or ("line_item" not in groups and line is not None):
                    costs._fail("native_grouping_mismatch")
                dimension = (day, project, key, line)
                if dimension in result_dimensions:
                    costs._fail("duplicate_native_cost_partition")
                result_dimensions.add(dimension)
                costs._object(row["amount"], ("value", "currency"))
                if row["amount"]["currency"] != "usd":
                    costs._fail("unsupported_currency")
                if isinstance(row["amount"]["value"], bool) or not isinstance(row["amount"]["value"], (int, Decimal)):
                    costs._fail("invalid_native_amount")
                amount = costs._amount(row["amount"]["value"])
                totals.setdefault((day.isoformat(), project, key), []).append(amount)
        normalized = []
        for (day, project, key), amounts in totals.items():
            identity = json.dumps([day, project, key], separators=(",", ":"))
            normalized.append({"bucketId": "native_" + hashlib.sha256(identity.encode()).hexdigest(),
                               "day": day, "projectId": project, "apiKeyId": key,
                               "amountUsd": costs._decimal_text(costs._sum(amounts)), "currency": "USD"})
        pages.append({"pageId": _page_id(cursor), "nextPageId": None if next_cursor is None else _page_id(next_cursor), "buckets": normalized})
        expected_cursor = next_cursor
    # A complete cursor chain cannot claim a full window while omitting days.
    # Empty results inside a captured daily bucket are kept empty, never zero.
    end_day = window[1] if expected_cursor is None else (max(seen_days) + dt.timedelta(days=1) if seen_days else window[0])
    if len(seen_days) != (end_day - window[0]).days or any(not window[0] <= day < end_day for day in seen_days):
        costs._fail("incomplete_native_daily_window")
    result = {"schemaVersion": config["schemaVersion"], "kind": "daily_costs", "scope": "project_api_key_partitions",
              "queryWindow": dict(export["queryWindow"]), "paginationComplete": expected_cursor is None,
              "settlementStatus": "pending", "pages": pages}
    costs._daily(config, result)  # Existing attribution/overlap checks remain authoritative.
    return result


def main(argv=None):
    parser = costs.SafeArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True)
    parser.add_argument("--export", required=True)
    try:
        args = parser.parse_args(argv)
        result = normalize(costs._read(args.config), costs._read(args.export))
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0
    except costs.IsolationError as error:
        print(json.dumps({"valid": False, "reasonCode": str(error)}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
