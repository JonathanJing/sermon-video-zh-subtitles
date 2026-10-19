"""Legacy scripts/ paths of moved experiments resolve to this checkout's experiments/."""

import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
TARGET = re.compile(r'^\s*/ "(experiments/[^"]+\.py)"$', re.M)


def moved():
    """Legacy module -> implementation file, for every scripts/ facade that loads an experiments/ file."""
    found = {}
    for facade in sorted((ROOT / "scripts").rglob("*.py")):
        text = facade.read_text(encoding="utf-8")
        match = TARGET.search(text)
        if match and "sys.modules[__name__] = _implementation" in text:
            found[".".join(facade.relative_to(ROOT).with_suffix("").parts)] = match.group(1)
    return found


def keeps_legacy_name(name):
    """Facades that run the implementation under the legacy module name (not a private cache name)."""
    return "_MODULE_NAME" not in (ROOT / (name.replace(".", "/") + ".py")).read_text(encoding="utf-8")


class ExperimentLeafFacadeTests(unittest.TestCase):
    def test_moved_experiments_have_facades(self):
        self.assertTrue(moved())

    def test_legacy_modules_load_moved_implementations_from_this_checkout(self):
        code = ("import sys; from pathlib import Path; sys.path.insert(0, sys.argv[1])\n"
                "for pair in sys.argv[2:]:\n"
                "    name, target = pair.split('=')\n"
                "    module = __import__(name, fromlist=['_'])\n"
                "    assert sys.modules[name] is module, name\n"
                "    assert Path(module.__file__).resolve() == (Path(sys.argv[1]) / target).resolve(), (name, module.__file__)\n")
        self._run(code, [f"{k}={v}" for k, v in moved().items()])

    def test_functions_pickle_by_their_legacy_module(self):
        names = [name for name in moved() if keeps_legacy_name(name)]
        self.assertTrue(names)
        code = ("import inspect, pickle, sys; sys.path.insert(0, sys.argv[1])\n"
                "for name in sys.argv[2:]:\n"
                "    module = __import__(name, fromlist=['_'])\n"
                "    assert module.__name__ == name, (name, module.__name__)\n"
                "    functions = [f for _, f in inspect.getmembers(module, inspect.isfunction) if f.__module__ == name]\n"
                "    assert functions, name\n"
                "    assert pickle.loads(pickle.dumps(functions[0])) is functions[0], name\n")
        self._run(code, names)

    def test_implementations_exist_outside_scripts(self):
        for name, target in moved().items():
            with self.subTest(name=name):
                self.assertTrue((ROOT / target).is_file())
                self.assertFalse((ROOT / target).is_relative_to(ROOT / "scripts"))

    def _run(self, code, arguments):
        environment = {key: value for key, value in os.environ.items() if key != "PYTHONPATH"}
        with tempfile.TemporaryDirectory() as elsewhere:
            result = subprocess.run([sys.executable, "-c", code, str(ROOT), *arguments],
                                    cwd=elsewhere, env=environment, capture_output=True, text=True, timeout=300)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
