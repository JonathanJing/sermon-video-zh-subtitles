#!/usr/bin/env python3
"""Compatibility CLI for the field venue independent truth experiment."""

from pathlib import Path
import runpy


if __name__ == "__main__":
    implementation = (
        Path(__file__).resolve().parents[1]
        / "experiments"
        / "field-fingerprint-benchmark"
        / "field_venue_independent_truth.py"
    )
    runpy.run_path(str(implementation), run_name="__main__")
