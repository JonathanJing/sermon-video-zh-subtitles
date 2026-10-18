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
SELF_CONTAINED_SCRIPTS = {"mfa_alignment.py",
                          # Launches itself as an isolated `python -I` worker and loads its
                          # sibling sermon_provider_error.py; it reads only its own directory.
                          "provider_http.py",
                          # Deploys its own bytes to Spark and binds sessions to their hash
                          # (controllerSha256); it reads only its own file.
                          "spark_exclusive_session.py",
                          # Bundled standalone as scripts/sermon_log_contract.py by the experiment
                          # log release tool; only then does it read schemas/ beside itself.
                          "log_contract.py"}
# Reads other modules' file attributes, never its own location: the execution identity
# hashes the modules loaded in this process; its checkout root comes from the host.
READS_LOADED_MODULE_FILES = {"observability/accounting.py",
                             # Transports hash their own bytes into their cache identity
                             # (adapterSha256; codex_layer2 also its resource helper's),
                             # never to locate the checkout (workflows design section 4.1).
                             "compute/transports/claude_layer2.py", "compute/transports/codex_layer2.py",
                             "compute/transports/openai_layer2.py", "compute/transports/codex_cli.py"}


def imports_of(path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield alias.name
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            yield node.module


def package_imports_of(path):
    """Absolute module names a file imports from tongxing_production, relative imports resolved."""
    package = path.relative_to(PACKAGE_SRC.parent).with_suffix("").parts[:-1]
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield alias.name
        elif isinstance(node, ast.ImportFrom):
            base = list(package[:len(package) - node.level + 1]) if node.level else []
            module = ".".join(base + ([node.module] if node.module else []))
            for alias in node.names:
                yield module + "." + alias.name if not node.module or node.level else module


class ProductionPackageTests(unittest.TestCase):
    def test_layers_import_only_upstream(self):
        """Downstream may import upstream pure validators (L2 design decision 5); never the reverse.
        Cross-layer review sits below every stage: stages may import it, it imports none of them."""
        downstream = {"source": ("tongxing_production.text", "tongxing_production.audio",
                                 "tongxing_production.delivery"),
                      "text": ("tongxing_production.audio", "tongxing_production.delivery"),
                      "audio": ("tongxing_production.delivery",),
                      # The engine knows stage names only; the prepared workflow composes it.
                      "orchestration": ("tongxing_production.workflows",),
                      "review": ("tongxing_production.source", "tongxing_production.text", "tongxing_production.audio",
                                 "tongxing_production.delivery", "tongxing_production.orchestration"),
                      # Shared infrastructure sits below every stage; stages reach it through ports.
                      "storage": ("tongxing_production.source", "tongxing_production.text", "tongxing_production.audio",
                                  "tongxing_production.delivery", "tongxing_production.review",
                                  "tongxing_production.orchestration", "tongxing_production.workflows",
                                  "tongxing_production.adapters"),
                      # Shared contracts sit below everything, review included.
                      "contracts": ("tongxing_production.source", "tongxing_production.text", "tongxing_production.audio",
                                    "tongxing_production.delivery", "tongxing_production.orchestration",
                                    "tongxing_production.review", "tongxing_production.compute",
                                    "tongxing_production.adapters")}
        for layer, forbidden in downstream.items():
            for path in sorted((PACKAGE_SRC / layer).rglob("*.py")):
                with self.subTest(path=str(path.relative_to(ROOT))):
                    for name in package_imports_of(path):
                        self.assertFalse(any(name == f or name.startswith(f + ".") for f in forbidden),
                                         f"{path.name} imports {name}")

    def test_only_the_hosting_adapter_imports_google_auth(self):
        """L4 decision 3: google-auth is the optional ``hosting`` extra, imported by storage/hosting.py alone."""
        importers = sorted(str(path.relative_to(PACKAGE_SRC)) for path in PACKAGE_SRC.rglob("*.py")
                           if any(name == "google.auth" or name.startswith("google.auth.") for name in imports_of(path)))
        self.assertEqual(importers, ["storage/hosting.py"])
        import tomllib
        project = tomllib.loads((PACKAGE_SRC.parents[1] / "pyproject.toml").read_text(encoding="utf-8"))["project"]
        self.assertFalse(any(dependency.startswith("google-auth") for dependency in project["dependencies"]))
        self.assertEqual([d for d in project["optional-dependencies"]["hosting"] if d.startswith("google-auth")],
                         ["google-auth[requests]>=2.35,<3"])

    def test_legacy_adapters_stay_apart_from_the_layers(self):
        """L4 decision 5: the v2/v3 adapters may use delivery; no layer imports them."""
        for path in sorted(PACKAGE_SRC.rglob("*.py")):
            if path.is_relative_to(PACKAGE_SRC / "adapters"):
                continue
            with self.subTest(path=str(path.relative_to(ROOT))):
                for name in package_imports_of(path):
                    self.assertFalse(name.startswith("tongxing_production.adapters"), f"{path.name} imports {name}")

    def test_package_never_imports_transition_trees_or_locates_the_checkout(self):
        sources = sorted(PACKAGE_SRC.rglob("*.py"))
        self.assertTrue(sources)
        for path in sources:
            with self.subTest(path=str(path.relative_to(ROOT))):
                for name in imports_of(path):
                    self.assertFalse(name.split(".", 1)[0] in FORBIDDEN_IMPORTS, f"{path.name} imports {name}")
                if (path.name not in SELF_CONTAINED_SCRIPTS
                        and path.relative_to(PACKAGE_SRC).as_posix() not in READS_LOADED_MODULE_FILES):
                    self.assertNotIn("__file__", path.read_text(encoding="utf-8"))

    def test_every_facade_imports_by_bare_name_from_a_script_run_in_scripts(self):
        """`python scripts/x.py` puts only scripts/ on sys.path; scripts that fall back to
        bare imports (`import sermon_sentence_interpretation`) must still reach the package."""
        facades = sorted(path.stem for path in (ROOT / "scripts").glob("*.py")
                         if "sys.modules[__name__] = _implementation" in path.read_text(encoding="utf-8"))
        self.assertTrue(facades)
        code = ("import sys; from pathlib import Path; sys.path[0] = sys.argv[1]\n"
                "for name in sys.argv[2:]:\n"
                "    module = __import__(name)\n"
                # Operator/development tools and experiment facades live outside the production package.
                "    target = Path(module.__file__).resolve()\n"
                "    experiment_root = Path(sys.argv[1]).resolve().parent / 'experiments'\n"
                "    assert module.__name__.startswith(('tongxing_production.', 'tools.ops.', 'tools.development.')) or target.is_relative_to(experiment_root), (name, module.__name__, str(target))\n")
        environment = {key: value for key, value in os.environ.items() if key != "PYTHONPATH"}
        with tempfile.TemporaryDirectory() as elsewhere:
            result = subprocess.run([sys.executable, "-c", code, str(ROOT / "scripts"), *facades],
                                    cwd=elsewhere, env=environment, capture_output=True, text=True, timeout=120)
        self.assertEqual(result.returncode, 0, result.stderr[-2000:])

    def test_prepared_workflow_names_exactly_the_engine_stages(self):
        from tongxing_production.orchestration.unified import backend
        from tongxing_production.workflows.prepared import stages
        self.assertEqual(set(stages.STAGE_MODULES), backend.STAGE_NAMES)
        from scripts import sermon_unified  # noqa: F401  the host binds stage loading to the table
        self.assertIs(backend.current().stage, stages.load)

    def test_scripts_facade_is_the_package_module(self):
        from scripts import sermon_provider_limits as facade
        from tongxing_production.compute import provider_limits as implementation
        self.assertIs(facade, implementation)
        self.assertIs(sys.modules["scripts.sermon_provider_limits"], implementation)
        self.assertEqual(implementation.SCHEMA, "sermon-openai-chat-request-limits-v1")

    def test_layer2_models_facade_alias_and_editable_path_use_this_checkout(self):
        from scripts import run_target_language_models as facade
        from tongxing_production import path_aliases
        from tongxing_production.text import models as implementation
        expected = ROOT / "packages/production/src/tongxing_production/text/models.py"
        self.assertIs(facade, implementation)
        self.assertIs(sys.modules["scripts.run_target_language_models"], implementation)
        self.assertEqual(Path(implementation.__file__).resolve(), expected.resolve())
        self.assertEqual(path_aliases.resolve("scripts/run_target_language_models.py"),
                         "packages/production/src/tongxing_production/text/models.py")

        environment = {key: value for key, value in os.environ.items() if key != "PYTHONPATH"}
        with tempfile.TemporaryDirectory() as elsewhere:
            result = subprocess.run(
                [sys.executable, str(ROOT / "scripts/run_target_language_models.py"), "--help"],
                cwd=elsewhere, env=environment, capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr[-2000:])
        self.assertIn("--payload-cache-from", result.stdout)
        self.assertIn("--emit-payload-cache-success", result.stdout)

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
