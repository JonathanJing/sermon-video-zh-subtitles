#!/usr/bin/env python3
"""Route the required Python check without weakening shared client contracts.

Documentation still goes through docs_change_gate.py before this classifier.
Only a pull request confined to the native client may use the small contract
suite; pushes and every unclassified or mixed code change run the full suite.
"""

from __future__ import annotations

import argparse
from pathlib import Path, PurePosixPath
import subprocess
import sys

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.docs_change_gate import changed_paths, documentation_only, is_documentation_path


def change_scope(paths: list[str], event: str) -> str:
    if event not in {"pull_request", "push"} or not paths:
        return "full"
    if documentation_only(paths):
        return "docs"
    non_docs = [path for path in paths if not is_documentation_path(path)]
    if event == "pull_request" and all(
        path.startswith("apps/tongxing-ios/") and ".." not in PurePosixPath(path).parts
        for path in non_docs
    ):
        return "native"
    return "full"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", required=True)
    parser.add_argument("--head", required=True)
    parser.add_argument("--event", choices=("pull_request", "push"), required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        paths = changed_paths(args.base, args.head, args.event)
    except (subprocess.CalledProcessError, ValueError) as exc:
        print(f"Cannot classify changes; running full tests: {exc}", file=sys.stderr)
        paths = []
    scope = change_scope(paths, args.event)
    with args.output.open("a", encoding="utf-8") as output:
        output.write(f"scope={scope}\n")
    print(f"Python CI scope: {scope}; changed paths: {len(paths)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
