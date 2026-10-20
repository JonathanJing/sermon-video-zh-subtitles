"""New files do not go under scripts/; they follow the target layout (AGENTS.md)."""
from pathlib import Path
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[1]
ALLOWLIST = Path(__file__).with_name("scripts_layout_allowlist.txt")


def allowed():
    lines = ALLOWLIST.read_text(encoding="utf-8").splitlines()
    return {line.strip() for line in lines if line.strip() and not line.startswith("#")}


def tracked_scripts():
    try:
        out = subprocess.run(["git", "ls-files", "scripts"], cwd=ROOT, capture_output=True, text=True, check=True).stdout
        return set(out.split())
    except (OSError, subprocess.CalledProcessError):  # not a git checkout: fall back to the tree
        return {str(p.relative_to(ROOT)) for p in (ROOT / "scripts").rglob("*")
                if p.is_file() and "__pycache__" not in p.parts}


class ScriptsLayoutGuardTests(unittest.TestCase):
    def test_no_new_files_under_scripts(self):
        new = sorted(tracked_scripts() - allowed())
        self.assertEqual(new, [], "New files under scripts/. Put production code in "
                         "packages/production/src/tongxing_production/<area>/ (run it with tools/ops/run.py), "
                         "operator tools in tools/ops/, helpers in tools/development/, research in "
                         "experiments/<line>/ (see AGENTS.md). Do not add them to the allowlist.")

    def test_allowlist_is_sorted_and_unique(self):
        entries = [line.strip() for line in ALLOWLIST.read_text(encoding="utf-8").splitlines()
                   if line.strip() and not line.startswith("#")]
        self.assertEqual(entries, sorted(set(entries)))


if __name__ == "__main__":
    unittest.main()
