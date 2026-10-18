#!/usr/bin/env python3
"""Compatibility entry point for the field venue independent truth experiment."""

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import runpy
import sys


def _implementation_path():
    return (
        Path(__file__).resolve().parents[1]
        / "experiments"
        / "field-fingerprint-benchmark"
        / "field_venue_independent_truth.py"
    )


if __name__ == "__main__":
    runpy.run_path(str(_implementation_path()), run_name="__main__")
else:
    # Use the original import identity so writes, wildcard imports, and pickle
    # all resolve to one module. The source itself is loaded by exact path.
    spec = spec_from_file_location(__name__, _implementation_path())
    if spec is None or spec.loader is None:
        raise ImportError("cannot load independent truth implementation")
    implementation = module_from_spec(spec)
    facade = sys.modules[__name__]
    sys.modules[__name__] = implementation
    try:
        spec.loader.exec_module(implementation)
    except BaseException:
        if sys.modules.get(__name__) is implementation:
            sys.modules[__name__] = facade
        raise
