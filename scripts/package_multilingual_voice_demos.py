"""Compatibility entry point for the multilingual voice demo experiment.

Keep the old direct CLI, module CLI, and import path while the implementation
lives with the experiment. Resolve it from this file, independent of the CWD.
"""

import hashlib
from importlib import util
from pathlib import Path
import sys


_IMPLEMENTATION = (
    Path(__file__).resolve().parents[1]
    / "experiments/sermon-dubbing-poc/package_multilingual_voice_demos.py"
).resolve()
_MODULE_NAME = (
    "_sermon_dubbing_poc_package_multilingual_voice_demos_"
    + hashlib.sha256(str(_IMPLEMENTATION).encode()).hexdigest()
)


def _load():
    existing = sys.modules.get(_MODULE_NAME)
    if existing is not None:
        if Path(existing.__file__).resolve() != _IMPLEMENTATION:
            raise ImportError("Voice demo packager module cache points to another checkout")
        return existing
    spec = util.spec_from_file_location(_MODULE_NAME, _IMPLEMENTATION)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load voice demo packager: {_IMPLEMENTATION}")
    module = util.module_from_spec(spec)
    sys.modules[_MODULE_NAME] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        del sys.modules[_MODULE_NAME]
        raise
    return module


_implementation = _load()


def __getattr__(name):
    # Also supports callers that load this facade with spec_from_file_location.
    return getattr(_implementation, name)


if __name__ == "__main__":
    _implementation.main()
else:
    sys.modules[__name__] = _implementation
