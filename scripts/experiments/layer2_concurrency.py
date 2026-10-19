"""Compatibility entry point for the local layer latency experiments.

The implementation lives in `experiments/local-layer-latency/layer2_concurrency.py`. Keep the old direct CLI,
module CLI and import path; resolve it from this file, independent of the CWD.
"""

import hashlib
from importlib import util
from pathlib import Path
import runpy
import sys


_IMPLEMENTATION = (
    Path(__file__).resolve().parents[2]
    / "experiments/local-layer-latency/layer2_concurrency.py"
).resolve()
_MODULE_NAME = (
    "_local_layer_latency_layer2_concurrency_"
    + hashlib.sha256(str(_IMPLEMENTATION).encode()).hexdigest()
)


def _load():
    existing = sys.modules.get(_MODULE_NAME)
    if existing is not None:
        if Path(existing.__file__).resolve() != _IMPLEMENTATION:
            raise ImportError("layer2_concurrency module cache points to another checkout")
        return existing
    spec = util.spec_from_file_location(_MODULE_NAME, _IMPLEMENTATION)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load layer2_concurrency: {_IMPLEMENTATION}")
    module = util.module_from_spec(spec)
    sys.modules[_MODULE_NAME] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        del sys.modules[_MODULE_NAME]
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
