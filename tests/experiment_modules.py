"""Load an experiments/ implementation by path: experiment lines are directories, not packages.

The module name matches the one the scripts/ facades used, so a test and any remaining facade
of the same file share one module object.
"""
import hashlib
from importlib import util
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]


def load(relative):
    path = (ROOT / relative).resolve()
    line = path.parent.name.replace("-", "_")
    name = f"_{line}_{path.stem}_" + hashlib.sha256(str(path).encode()).hexdigest()
    existing = sys.modules.get(name)
    if existing is not None:
        return existing
    spec = util.spec_from_file_location(name, path)
    module = util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        del sys.modules[name]
        raise
    return module
