#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.asr_gold import read_jsonl, validate_human_gold


def main() -> None:
    parser = argparse.ArgumentParser(description="Fail closed unless every ASR Gold case has human approval and provenance.")
    parser.add_argument("gold", type=Path)
    args = parser.parse_args()
    try:
        gold = validate_human_gold(read_jsonl(args.gold))
    except ValueError as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(1) from error
    print(json.dumps({"status": "approved_human_gold", "cases": len(gold)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
