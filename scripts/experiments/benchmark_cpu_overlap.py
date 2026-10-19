"""Compatibility entry point for the local layer latency experiments.

The implementation lives in `experiments/local-layer-latency/benchmark_cpu_overlap.py`. Keep the old direct CLI,
module CLI and import path; resolve it from this file, independent of the CWD.
The implementation runs under this module's name, so pickled objects and
spawn-based workers still import it through the old path.
"""

from importlib import util
from pathlib import Path
import runpy
import sys


_IMPLEMENTATION = (
    Path(__file__).resolve().parents[2]
    / "experiments/local-layer-latency/benchmark_cpu_overlap.py"
).resolve()


def _load():
    spec = util.spec_from_file_location(__name__, _IMPLEMENTATION)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load benchmark_cpu_overlap: {_IMPLEMENTATION}")
    module = util.module_from_spec(spec)
    facade = sys.modules.get(__name__)
    sys.modules[__name__] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        if facade is None:
            sys.modules.pop(__name__, None)
        else:
            sys.modules[__name__] = facade
        raise
    return module


if __name__ == "__main__":
    runpy.run_path(str(_IMPLEMENTATION), run_name="__main__")
else:
    _implementation = _load()

    def __getattr__(name):
        # Also supports callers that load this facade with spec_from_file_location.
        return getattr(_implementation, name)

    sys.modules[__name__] = _implementation
