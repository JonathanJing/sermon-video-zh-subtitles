#!/usr/bin/env python3
"""Give a multilingual catalog a locale-independent content kind and honest media types.

Why this exists (2026-11-16): the singer-first page publisher only accepts
``mediaType`` ``podcast`` or ``clip`` for its page configs, so Sunday sermon pages
published through it carried ``mediaType: podcast``. The iOS content picker grouped
pages by ``mediaType``, so those sermons appeared under the podcast tab while their
category label still read 周日证道 / Sunday sermon.

The unified rule:

* ``displayCategory.labels`` are presentation text; they never decide grouping.
* ``contentKind`` (``sermon`` | ``podcast`` | ``clip``) is the locale-independent
  grouping field. Clients group by it and fall back to the older ``mediaType`` rule
  only when it is absent.
* ``mediaType`` stays a technical source tag. It is kept only on podcast pages,
  where the publish gate needs it to relax the two-clock audio check.

This tool derives ``contentKind`` from the display category, removes the misleading
``mediaType`` from non-podcast pages and validates the result against the catalog
schema. It only reads and writes local files: it never deploys, uploads or touches
Firebase.
"""
from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

# The English label is the stable authoring key; zh-Hans covers catalogs without it.
KIND_BY_LABEL = {
    "Sunday sermon": "sermon",
    "Archive edition": "sermon",
    "Sermon clip": "clip",
    "Sermon Podcast": "podcast",
    "Podcast": "podcast",
    "Experiment clip": "clip",
}
KINDS = ("sermon", "podcast", "clip")
SCHEMA_FILES = {f"sermon-multilingual-catalog-v{v}": ROOT / f"schemas/sermon-multilingual-catalog-v{v}.schema.json"
                for v in (2, 3, 4)}


class CatalogKindError(ValueError):
    """The catalog or its categories cannot be classified without a decision."""


def kind_for(page: dict) -> str:
    category = page.get("displayCategory") or {}
    labels = category.get("labels") or {}
    for label in (labels.get("en"), labels.get("zh-Hans")):
        if label and label in KIND_BY_LABEL:
            return KIND_BY_LABEL[label]
    if category:
        raise CatalogKindError(f"{page['id']}: unknown display category {sorted(labels.values())}; "
                               "add it to KIND_BY_LABEL instead of guessing")
    # No category: keep the historical client rule, but make it explicit.
    return "podcast" if page.get("mediaType") == "podcast" else "sermon"


def normalize(catalog: dict) -> tuple[dict, list[dict]]:
    version = catalog.get("schemaVersion")
    schema_path = SCHEMA_FILES.get(version)
    if schema_path is None:
        raise CatalogKindError(f"unsupported catalog schema {version!r}")
    result = copy.deepcopy(catalog)
    changes = []
    for page in result["pages"]:
        kind = kind_for(page)
        before = {"contentKind": page.get("contentKind"), "mediaType": page.get("mediaType")}
        page["contentKind"] = kind
        if kind != "podcast":
            page.pop("mediaType", None)
        after = {"contentKind": page.get("contentKind"), "mediaType": page.get("mediaType")}
        if before != after:
            changes.append({"pageId": page["id"], "before": before, "after": after})
    validate(result)
    return result, changes


def validate(catalog: dict) -> None:
    try:
        from jsonschema import Draft202012Validator, FormatChecker
    except ImportError as error:  # pragma: no cover - operator environment
        raise SystemExit("jsonschema is required: run with the repository .venv") from error
    schema_path = SCHEMA_FILES.get(catalog.get("schemaVersion"))
    if schema_path is None:
        raise CatalogKindError(f"unsupported catalog schema {catalog.get('schemaVersion')!r}")
    schema = json.loads(schema_path.read_text())
    errors = sorted(Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(catalog),
                    key=lambda error: str(error.json_path))
    if errors:
        raise CatalogKindError(f"invalid catalog at {errors[0].json_path}: {errors[0].message}")
    ids = [page["id"] for page in catalog["pages"]]
    if len(set(ids)) != len(ids) or catalog.get("defaultPageId") not in ids:
        raise CatalogKindError("catalog page IDs must be unique and include defaultPageId")
    for page in catalog["pages"]:
        if page["contentKind"] not in KINDS:
            raise CatalogKindError(f"{page['id']}: contentKind {page['contentKind']!r} is not one of {KINDS}")
        if page["contentKind"] != "podcast" and page.get("mediaType") == "podcast":
            raise CatalogKindError(f"{page['id']}: a non-podcast page must not claim mediaType podcast")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--input", type=Path, required=True, help="catalog JSON to read")
    parser.add_argument("--output", type=Path, help="where to write the normalized catalog")
    parser.add_argument("--check", action="store_true",
                        help="only report what would change; exit 1 when the file needs normalizing")
    parser.add_argument("--json", type=Path, help="write a receipt with the per-page changes")
    args = parser.parse_args()

    catalog = json.loads(args.input.read_text())
    normalized, changes = normalize(catalog)
    receipt = {"input": str(args.input), "schemaVersion": normalized.get("schemaVersion"),
               "pages": len(normalized["pages"]), "changed": len(changes), "changes": changes}
    if args.json:
        args.json.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n")
    for change in changes:
        print(f"{change['pageId']}: {change['before']} -> {change['after']}")
    print(f"{len(changes)} of {len(normalized['pages'])} pages changed")

    if args.check:
        return 1 if changes else 0
    if not args.output:
        if not changes:
            return 0
        parser.error("--output is required unless --check is used")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(normalized, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    print(f"wrote {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
