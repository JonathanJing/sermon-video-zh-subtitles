#!/usr/bin/env python3
"""Prepare category-only catalog metadata changes offline; never deploy assets."""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import tempfile
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parents[1]
VERSIONS = {f"sermon-multilingual-catalog-v{v}": v for v in (2, 3, 4)}


def validate_catalog(catalog: dict) -> None:
    if not isinstance(catalog, dict):
        raise ValueError("Catalog must be a JSON object")
    version = VERSIONS.get(catalog.get("schemaVersion"))
    if version is None:
        raise ValueError("Only multilingual catalog v2/v3/v4 is supported")
    schema = json.loads((ROOT / f"schemas/sermon-multilingual-catalog-v{version}.schema.json").read_text())
    errors = sorted(Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(catalog),
                    key=lambda error: str(error.json_path))
    if errors:
        raise ValueError(f"Invalid catalog at {errors[0].json_path}: {errors[0].message}")
    ids = [page["id"] for page in catalog["pages"]]
    if len(set(ids)) != len(ids) or catalog["defaultPageId"] not in ids:
        raise ValueError("Catalog page IDs must be unique and include defaultPageId")


def update_categories(catalog: dict, updates: dict) -> dict:
    validate_catalog(catalog)
    if not isinstance(updates, dict) or not updates:
        raise ValueError("Updates must be a nonempty page-ID mapping")
    known = {page["id"] for page in catalog["pages"]}
    unknown = set(updates) - known
    if unknown:
        raise ValueError(f"Unknown page ID: {sorted(unknown)[0]}")
    result = copy.deepcopy(catalog)
    for page in result["pages"]:
        if page["id"] in updates:
            value = updates[page["id"]]
            if value is None:
                page.pop("displayCategory", None)
            else:
                page["displayCategory"] = copy.deepcopy(value)
    validate_catalog(result)
    return result


def parse_json(data: bytes) -> dict:
    def unique_pairs(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"Duplicate JSON key: {key}")
            result[key] = value
        return result
    def reject_constant(value):
        raise ValueError(f"Non-finite JSON constant: {value}")
    return json.loads(data.decode("utf-8"), object_pairs_hook=unique_pairs,
                      parse_constant=reject_constant)


def read_json(path: Path) -> dict:
    return parse_json(path.read_bytes())


def write_new(path: Path, data: bytes) -> None:
    """Atomic create without replacing an existing file, including a symlink."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--updates", type=Path, required=True,
                        help="JSON mapping page ID to displayCategory, or null to remove")
    parser.add_argument("--output", type=Path, required=True, help="New catalog file; never overwritten")
    args = parser.parse_args()
    try:
        if args.output.resolve() in {args.catalog.resolve(), args.updates.resolve()}:
            raise ValueError("Output must be distinct from both inputs")
        original = args.catalog.read_bytes()
        updates = read_json(args.updates)
        result = update_categories(parse_json(original), updates)
        encoded = (json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")
        write_new(args.output, encoded)
        print(json.dumps({"schemaVersion": "catalog-display-category-update-receipt-v1",
                          "catalogSchemaVersion": result["schemaVersion"],
                          "inputSha256": hashlib.sha256(original).hexdigest(),
                          "outputSha256": hashlib.sha256(encoded).hexdigest(),
                          "updatedPageIds": sorted(updates),
                          "output": str(args.output), "deployed": False}, ensure_ascii=False))
    except (OSError, ValueError, TypeError) as error:
        parser.exit(1, f"Category update refused: {error}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
