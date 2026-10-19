"""Legacy scripts/ facades of tools moved by absolute path into tools/ops and tools/development."""
import os
from pathlib import Path
import re
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
TARGET = re.compile(r'^_MODULE_NAME = "(tools\.(?:ops|development)\.\w+)"$', re.MULTILINE)

# Each case runs in a fresh interpreter, because loading a facade replaces sys.modules entries.
CHECK = '''
import importlib.util, sys
from pathlib import Path
from unittest import mock
root, name, target = sys.argv[1:]
sys.path[0] = root
path = Path(root, "scripts", name + ".py")
implementation = None

def load(registered):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    if registered:
        sys.modules[name] = module
    spec.loader.exec_module(module)
    return module

# Unregistered spec load: reads still reach the implementation.
loose = load(False)
implementation = sys.modules[target]
assert implementation.__file__ == str(Path(root, *target.split(".")) ) + ".py", implementation.__file__
public = sorted(key for key in vars(implementation) if not key.startswith("_"))
assert public and all(getattr(loose, key) is getattr(implementation, key) for key in public), name

# Registered spec load: writes and mock patches reach the implementation and are undone.
held = load(True)
key = public[0]
original = getattr(implementation, key)
with mock.patch.object(held, key, "patched"):
    assert getattr(implementation, key) == "patched"
assert getattr(implementation, key) is original and getattr(held, key) is original
held._facade_probe = 1
assert implementation._facade_probe == 1
del held._facade_probe
assert not hasattr(implementation, "_facade_probe")

# Bare, scripts. and tools. imports are one module object.
sys.modules.pop(name, None)
sys.path.insert(0, str(Path(root, "scripts")))
import importlib
bare = importlib.import_module(name)
package = importlib.import_module("scripts." + name)
tools = importlib.import_module(target)
assert bare is package is tools is implementation, (bare, package, tools)
'''


def tool_facades():
    for path in sorted((ROOT / "scripts").glob("*.py")):
        match = TARGET.search(path.read_text(encoding="utf-8"))
        if match:
            yield path.stem, match.group(1)


class ToolFacadeTests(unittest.TestCase):
    def test_facades_forward_to_one_implementation(self):
        facades = list(tool_facades())
        self.assertGreaterEqual(len(facades), 36)
        environment = {key: value for key, value in os.environ.items() if key != "PYTHONPATH"}
        for name, target in facades:
            with self.subTest(name=name):
                result = subprocess.run([sys.executable, "-c", CHECK, str(ROOT), name, target],
                                        cwd=ROOT.parent, env=environment, capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr[-2000:])


if __name__ == "__main__":
    unittest.main()
