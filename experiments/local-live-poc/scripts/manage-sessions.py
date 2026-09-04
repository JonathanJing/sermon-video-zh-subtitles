#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.retention import apply_retention, retention_plan


def main() -> None:
    parser = argparse.ArgumentParser(description="Preview or apply the local session retention policy.")
    parser.add_argument("--root", default=os.environ.get("LOCAL_LIVE_SESSION_ROOT", "artifacts/sessions"))
    parser.add_argument("--days", type=int, default=int(os.environ.get("LOCAL_LIVE_RETENTION_DAYS", "30")))
    parser.add_argument("--keep-latest", type=int, default=10)
    parser.add_argument("--apply", action="store_true", help="delete only the sessions listed by this run")
    args = parser.parse_args()
    plan = retention_plan(args.root, args.days, args.keep_latest)
    result = {**plan, "mode": "apply" if args.apply else "preview"}
    if args.apply:
        result["deletedSessionIds"] = apply_retention(plan)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
