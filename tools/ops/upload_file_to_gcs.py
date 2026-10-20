#!/usr/bin/env python3
"""Upload one local file to GCS using the Cloud Run service account."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.cloud import upload_file_to_gcs


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True)
    parser.add_argument("--destination", required=True)
    args = parser.parse_args()
    upload_file_to_gcs(args.source, args.destination)
    print(f"Uploaded {args.source} -> {args.destination}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
