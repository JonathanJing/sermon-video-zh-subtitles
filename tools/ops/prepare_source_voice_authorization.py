#!/usr/bin/env python3
"""Create a candidate-bound source voice authorization from a user attestation."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.ops.run import bind_host

bind_host()

from tongxing_production.audio.speech_job import prepare_source_voice_authorization


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--english-source-package", required=True, type=Path)
    parser.add_argument("--candidate", required=True, type=Path)
    parser.add_argument("--adapter", required=True, type=Path)
    parser.add_argument("--user-attestation", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    receipt = prepare_source_voice_authorization(
        args.english_source_package, args.candidate, args.adapter, args.user_attestation, args.out)
    print(json.dumps({"status": "prepared", "schemaVersion": receipt["schemaVersion"],
                      "targetLocale": receipt["targetLocale"],
                      "receipt": str(args.out.resolve())}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
