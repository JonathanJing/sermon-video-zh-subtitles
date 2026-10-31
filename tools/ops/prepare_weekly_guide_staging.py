#!/usr/bin/env python3
"""Prepare ignored weekly guides or bind them to a verified catalog snapshot."""
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path: sys.path.insert(0,str(ROOT))
from scripts import tongxing_host  # noqa: E402,F401
from tongxing_production.delivery.weekly_guide_staging import main  # noqa: E402
if __name__=='__main__': raise SystemExit(main())
