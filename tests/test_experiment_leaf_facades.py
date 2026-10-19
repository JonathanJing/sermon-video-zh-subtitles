"""Legacy scripts/ paths of moved experiments resolve to this checkout's experiments/."""

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]

# Legacy module -> implementation file, relative to the repository root.
MOVED = {
    "scripts.experiments.agent_api_trials": "experiments/agents-api-trials/agent_api_trials.py",
    "scripts.experiments.build_agent_trial_variants": "experiments/agents-api-trials/build_agent_trial_variants.py",
    "scripts.experiments.supervisor_ab": "experiments/agents-api-trials/supervisor_ab.py",
}


class ExperimentLeafFacadeTests(unittest.TestCase):
    def test_legacy_modules_load_moved_implementations_from_this_checkout(self):
        code = ("import sys; from pathlib import Path; sys.path.insert(0, sys.argv[1])\n"
                "for pair in sys.argv[2:]:\n"
                "    name, target = pair.split('=')\n"
                "    module = __import__(name, fromlist=['_'])\n"
                "    assert sys.modules[name] is module, name\n"
                "    assert Path(module.__file__).resolve() == (Path(sys.argv[1]) / target).resolve(), (name, module.__file__)\n")
        environment = {key: value for key, value in os.environ.items() if key != "PYTHONPATH"}
        with tempfile.TemporaryDirectory() as elsewhere:
            result = subprocess.run([sys.executable, "-c", code, str(ROOT), *(f"{k}={v}" for k, v in MOVED.items())],
                                    cwd=elsewhere, env=environment, capture_output=True, text=True, timeout=120)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_legacy_facades_are_thin(self):
        for name, target in MOVED.items():
            with self.subTest(name=name):
                facade = ROOT / (name.replace(".", "/") + ".py")
                text = facade.read_text(encoding="utf-8")
                self.assertIn(f'"{target}"', text)
                self.assertIn("sys.modules[__name__] = _implementation", text)
                self.assertTrue((ROOT / target).is_file())


if __name__ == "__main__":
    unittest.main()
