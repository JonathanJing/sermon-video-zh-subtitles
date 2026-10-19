#!/usr/bin/env python3
"""Compatibility entry point for ``tools/development/run_clip_real_e2e.py``.

Keep the old direct CLI, ``python -m scripts.run_clip_real_e2e`` and the import path
while the implementation lives in tools/development. The implementation is loaded
by absolute path from this checkout, independent of the CWD; bare and
``scripts.`` imports share one ``tools.development.run_clip_real_e2e`` module object.
"""

import importlib
from importlib import util
from pathlib import Path
import runpy
import sys


_IMPLEMENTATION = (Path(__file__).resolve().parents[1] / "tools/development/run_clip_real_e2e.py").resolve()
_MODULE_NAME = "tools.development.run_clip_real_e2e"


def _load():
    existing = sys.modules.get(_MODULE_NAME)
    if existing is not None:
        if Path(existing.__file__).resolve() != _IMPLEMENTATION:
            raise ImportError(f"{_MODULE_NAME} is already loaded from another checkout")
        return existing
    spec = util.spec_from_file_location(_MODULE_NAME, _IMPLEMENTATION)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load {_IMPLEMENTATION}")
    module = util.module_from_spec(spec)
    sys.modules[_MODULE_NAME] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        del sys.modules[_MODULE_NAME]
        raise
    try:  # ``import tools.development.run_clip_real_e2e`` also reaches it through the namespace parent.
        setattr(importlib.import_module("tools.development"), "run_clip_real_e2e", module)
    except ImportError:
        pass
    return module


if __name__ == "__main__":
    runpy.run_path(str(_IMPLEMENTATION), run_name="__main__")
else:
    _implementation = _load()

    class _Forward(type(sys)):
        # A caller that loads this file with spec_from_file_location keeps this
        # facade object; its reads, writes and mock patches reach the implementation.
        def __getattr__(self, name):
            return getattr(_implementation, name)

        def __setattr__(self, name, value):
            setattr(_implementation, name, value)

        def __delattr__(self, name):
            delattr(_implementation, name)

    def __getattr__(name):
        # Also serves a spec-loaded copy that was never put in sys.modules.
        return getattr(_implementation, name)

    _facade = sys.modules.get(__name__)
    if _facade is not None and _facade.__dict__ is globals():
        _facade.__class__ = _Forward
    sys.modules[__name__] = _implementation
