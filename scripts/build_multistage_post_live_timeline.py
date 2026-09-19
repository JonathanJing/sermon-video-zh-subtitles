#!/usr/bin/env python3
"""Retired compatibility entry point for automatic sermon boundary discovery.

Provide operator-confirmed start/end times through the production runbook.
This module intentionally performs no media processing or model calls.
"""

RETIREMENT_MESSAGE = (
    "Automatic sermon boundary discovery has been retired. "
    "Use scripts/run_post_live_timeline_job.py to prepare source media, then "
    "provide operator-confirmed start/end times following "
    "docs/codex-local-production-runbook.zh.md."
)


def build_multistage_timeline(*args, **kwargs):
    raise SystemExit(RETIREMENT_MESSAGE)


def main() -> int:
    raise SystemExit(RETIREMENT_MESSAGE)


if __name__ == "__main__":
    raise SystemExit(main())
