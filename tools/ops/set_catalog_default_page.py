#!/usr/bin/env python3
"""Point a multilingual catalog's default page at the content the app should open on.

The catalog's ``defaultPageId`` decides which page a client shows when it has no saved
selection. Production carried a podcast episode there (``if-i-had-more-time-…``), so a fresh
install opened on a podcast and the content picker therefore started on the Podcast tab.

The policy is "latest sermon": among pages whose ``contentKind`` is ``sermon`` and that are not
dev-only, pick the newest by date. Podcasts and clips never win. The tool validates against the
catalog schema and the content-kind rule, and writes a receipt with the page it chose.

  .venv/bin/python tools/ops/set_catalog_default_page.py --input production-v5.json \\
      --output production-v5.default.json --policy latest-sermon --check

It only reads and writes local files; deploying is a separate, explicit step.
"""
from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCHEMA_FILES = {f"sermon-multilingual-catalog-v{v}": ROOT / f"schemas/sermon-multilingual-catalog-v{v}.schema.json"
                for v in (2, 3, 4, 5)}


class DefaultPageError(ValueError):
    """The catalog cannot pick a valid default under the requested policy."""


def is_podcast(page: dict) -> bool:
    if page.get("contentKind") is not None:
        return page["contentKind"] == "podcast"
    return page.get("mediaType") == "podcast"


def is_selectable(page: dict) -> bool:
    return page.get("diagnosticOnly") is not True and page.get("simulationOnly") is not True


def is_sermon(page: dict) -> bool:
    if page.get("contentKind") is not None:
        return page["contentKind"] == "sermon"
    return page.get("mediaType") != "podcast"


def latest_sermon(catalog: dict) -> dict:
    candidates = [page for page in catalog["pages"] if is_selectable(page) and is_sermon(page)]
    if not candidates:
        raise DefaultPageError("the catalog has no sermon page to open by default")
    # Newest date wins; the id breaks ties so the result never depends on array order.
    return max(candidates, key=lambda page: (page["date"], page["id"]))


def apply_policy(catalog: dict, policy: str) -> tuple[dict, dict]:
    if catalog.get("schemaVersion") not in SCHEMA_FILES:
        raise DefaultPageError(f"unsupported catalog schema {catalog.get('schemaVersion')!r}")
    if policy != "latest-sermon":
        raise DefaultPageError(f"unsupported policy {policy!r}")
    chosen = latest_sermon(catalog)
    if chosen.get("contentKind") is not None and chosen["contentKind"] != "sermon":
        raise DefaultPageError(f"{chosen['id']}: policy refuses a non-sermon default")
    result = copy.deepcopy(catalog)
    previous = catalog.get("defaultPageId")
    result["defaultPageId"] = chosen["id"]
    for page in result["pages"]:
        if page["id"] == chosen["id"]:
            page.setdefault("contentKind", "sermon")
    validate(result)
    return result, {"policy": policy, "previousDefaultPageId": previous, "defaultPageId": chosen["id"],
                    "defaultPageDate": chosen["date"], "changed": previous != chosen["id"]}


def validate(catalog: dict) -> None:
    try:
        from jsonschema import Draft202012Validator, FormatChecker
    except ImportError as error:  # pragma: no cover - operator environment
        raise SystemExit("jsonschema is required: run with the repository .venv") from error
    schema = json.loads(SCHEMA_FILES[catalog["schemaVersion"]].read_text())
    errors = sorted(Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(catalog),
                    key=lambda error: str(error.json_path))
    if errors:
        raise DefaultPageError(f"invalid catalog at {errors[0].json_path}: {errors[0].message}")
    ids = [page["id"] for page in catalog["pages"]]
    if len(set(ids)) != len(ids) or catalog.get("defaultPageId") not in ids:
        raise DefaultPageError("catalog page IDs must be unique and include defaultPageId")
    default = next(page for page in catalog["pages"] if page["id"] == catalog["defaultPageId"])
    if not is_selectable(default) or is_podcast(default):
        raise DefaultPageError(f"{default['id']}: the default page must be a published sermon")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0],
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--policy", default="latest-sermon", choices=["latest-sermon"])
    parser.add_argument("--check", action="store_true", help="exit 1 when the default needs changing")
    parser.add_argument("--receipt", type=Path)
    args = parser.parse_args()

    catalog = json.loads(args.input.read_text())
    result, receipt = apply_policy(catalog, args.policy)
    receipt["input"] = str(args.input)
    print(json.dumps(receipt, ensure_ascii=False))
    if args.receipt:
        args.receipt.write_text(json.dumps(receipt, ensure_ascii=False, indent=1) + "\n")
    if args.check:
        return 1 if receipt["changed"] else 0
    if not receipt["changed"]:
        return 0
    if not args.output:
        parser.error("--output is required unless --check is used")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    print(f"wrote {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
