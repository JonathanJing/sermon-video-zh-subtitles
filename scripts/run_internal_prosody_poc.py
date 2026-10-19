"""Compatibility entry point for the multilingual prosody POC.

The implementation lives in `experiments/multilingual-prosody-poc/run_internal_prosody_poc.py`. Keep the old direct CLI,
module CLI and import path; resolve it from this file, independent of the CWD.
"""

import hashlib
from importlib import util
from pathlib import Path
import runpy
import sys


_IMPLEMENTATION = (
    Path(__file__).resolve().parents[1]
    / "experiments/multilingual-prosody-poc/run_internal_prosody_poc.py"
).resolve()
_MODULE_NAME = (
    "_multilingual_prosody_poc_run_internal_prosody_poc_"
    + hashlib.sha256(str(_IMPLEMENTATION).encode()).hexdigest()
)


def _load():
    existing = sys.modules.get(_MODULE_NAME)
    if existing is not None:
        if Path(existing.__file__).resolve() != _IMPLEMENTATION:
            raise ImportError("run_internal_prosody_poc module cache points to another checkout")
        return existing
    spec = util.spec_from_file_location(_MODULE_NAME, _IMPLEMENTATION)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load run_internal_prosody_poc: {_IMPLEMENTATION}")
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
