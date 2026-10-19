#!/usr/bin/env python3
"""Compatibility entry point for ``tools/ops/prepare_clip_voice_authorization.py``.

Keep the old direct CLI, ``python -m scripts.prepare_clip_voice_authorization`` and the import path
while the implementation lives in tools/ops. The implementation is loaded
by absolute path from this checkout, independent of the CWD; bare and
``scripts.`` imports share one ``tools.ops.prepare_clip_voice_authorization`` module object.
"""

import importlib
from importlib import util
from pathlib import Path
import runpy
import sys


_IMPLEMENTATION = (Path(__file__).resolve().parents[1] / "tools/ops/prepare_clip_voice_authorization.py").resolve()
_MODULE_NAME = "tools.ops.prepare_clip_voice_authorization"


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
    try:  # ``import tools.ops.prepare_clip_voice_authorization`` also reaches it through the namespace parent.
        setattr(importlib.import_module("tools.ops"), "prepare_clip_voice_authorization", module)
    except ImportError:
        pass
    return module


if __name__ == "__main__":
    runpy.run_path(str(_IMPLEMENTATION), run_name="__main__")
else:
    _implementation = _load()

    def __getattr__(name):
        # Callers that load this file with spec_from_file_location keep the facade.
        return getattr(_implementation, name)

    sys.modules[__name__] = _implementation
