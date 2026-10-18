#!/usr/bin/env python3
"""Compatibility CLI for the field venue independent truth experiment."""

from functools import lru_cache
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import runpy


def _implementation_path():
    return (
        Path(__file__).resolve().parents[1]
        / "experiments"
        / "field-fingerprint-benchmark"
        / "field_venue_independent_truth.py"
    )


@lru_cache(maxsize=4)
def _load_implementation(path):
    # Resolve the exact adjacent source; never look up an ambient module name.
    spec = spec_from_file_location(f"{__name__}._implementation", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load independent truth implementation: {path}")
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def __getattr__(name):
    if name == "__path__":
        raise AttributeError(name)
    return getattr(_load_implementation(_implementation_path()), name)


if __name__ == "__main__":
    runpy.run_path(str(_implementation_path()), run_name="__main__")
