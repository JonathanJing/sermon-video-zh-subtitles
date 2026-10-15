"""Stage-1 acceptance for the installable production package.

Checks the structural rules the layout proposal sets for ``packages/production``
and that the ``scripts/`` facade keeps old callers on the same module object.
"""
import ast
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from scripts import sermon_accounting as accounting

ROOT = Path(__file__).resolve().parents[1]
PACKAGE_SRC = ROOT / "packages/production/src/tongxing_production"
FORBIDDEN_IMPORTS = ("scripts", "backend", "apps", "tools", "experiments")
# Shipped to another machine as one file and run there standalone; hashing its
# own bytes for the receipt is self-identity, not checkout inference.
SELF_CONTAINED_SCRIPTS = {"mfa_alignment.py"}


def imports_of(path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield alias.name
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            yield node.module


class ProductionPackageTests(unittest.TestCase):
    def test_package_never_imports_transition_trees_or_locates_the_checkout(self):
        sources = sorted(PACKAGE_SRC.rglob("*.py"))
        self.assertTrue(sources)
        for path in sources:
            with self.subTest(path=str(path.relative_to(ROOT))):
                for name in imports_of(path):
                    self.assertFalse(name.split(".", 1)[0] in FORBIDDEN_IMPORTS, f"{path.name} imports {name}")
                if path.name not in SELF_CONTAINED_SCRIPTS:
                    self.assertNotIn("__file__", path.read_text(encoding="utf-8"))

    def test_scripts_facade_is_the_package_module(self):
        from scripts import sermon_provider_limits as facade
        from tongxing_production.compute import provider_limits as implementation
        self.assertIs(facade, implementation)
        self.assertIs(sys.modules["scripts.sermon_provider_limits"], implementation)
        self.assertEqual(implementation.SCHEMA, "sermon-openai-chat-request-limits-v1")

    def test_moved_module_keeps_a_repository_identity_key(self):
        from tongxing_production.compute import provider_limits
        key = "packages/production/src/tongxing_production/compute/provider_limits.py"
        self.assertEqual(accounting.code_path(provider_limits), key)
        self.assertEqual(accounting.code_module_name(key), "tongxing_production.compute.provider_limits")
        self.assertEqual(accounting.code_module_name("packages/production/src/tongxing_production/compute/__init__.py"),
                         "tongxing_production.compute")
        self.assertEqual(accounting.code_module_name("scripts/sermon_accounting.py"), "scripts.sermon_accounting")
        identity = accounting.execution_identity()
        self.assertIn(key, identity["loadedProjectCodeSha256"])
        self.assertIn(key, accounting.safe_execution_identity(identity)["loadedProjectCodeSha256"])
        for bad in ("packages/other/x.py", "../scripts/x.py", "scripts/x.txt", "tongxing_production/compute/provider_limits.py"):
            with self.subTest(path=bad), self.assertRaises(ValueError):
                accounting.code_module_name(bad)

    def test_package_imports_outside_the_checkout(self):
        """The installed package must not depend on the repository being the CWD or on sys.path."""
        environment = {key: value for key, value in os.environ.items() if key != "PYTHONPATH"}
        with tempfile.TemporaryDirectory() as elsewhere:
            result = subprocess.run(
                [sys.executable, "-c",
                 "import tongxing_production.compute.provider_limits as m; print(m.SCHEMA)"],
                cwd=elsewhere, env=environment, capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "sermon-openai-chat-request-limits-v1")


if __name__ == "__main__":
    unittest.main()
