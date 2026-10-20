"""The poster renderers must survive a regular wheel install, not just editable imports."""

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import textwrap
import unittest


ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "packages/production"
RESOURCES = (
    ("tongxing_production.adapters.legacy", "render_sermon_poster.swift"),
    ("tongxing_production.delivery.posters", "render_weekly_poster.swift"),
)


class ProductionWheelResourceTests(unittest.TestCase):
    def test_clean_wheel_install_keeps_poster_resources_and_old_commands(self):
        # pip builds a wheel from the package directory and installs that artifact.
        # In particular, neither an editable install nor the checkout's src/ is used.
        with tempfile.TemporaryDirectory() as temporary:
            outside = Path(temporary)
            wheelhouse = outside / "wheels"
            site = outside / "site"
            wheelhouse.mkdir()
            site.mkdir()
            env = {key: value for key, value in os.environ.items() if key != "PYTHONPATH"}

            def run(*args, environment=env):
                result = subprocess.run(
                    [sys.executable, *args], cwd=outside, env=environment,
                    capture_output=True, text=True, timeout=180,
                )
                self.assertEqual(result.returncode, 0, result.stderr[-3000:])
                return result

            run("-m", "pip", "wheel", "--disable-pip-version-check", "--no-deps",
                "--wheel-dir", str(wheelhouse), str(PACKAGE))
            wheels = list(wheelhouse.glob("tongxing_production-*.whl"))
            self.assertEqual(len(wheels), 1, wheels)
            run("-m", "pip", "install", "--disable-pip-version-check", "--no-deps",
                "--target", str(site), str(wheels[0]))

            # Run in a fresh process with only the installed target added to
            # sys.path. The checkout is still available as data for byte comparison.
            code = textwrap.dedent("""
                import importlib
                from importlib import resources
                from pathlib import Path
                import sys

                site, checkout, *source_paths = map(Path, sys.argv[1:])
                # The CI interpreter may have an editable install registered in
                # site-packages even when PYTHONPATH is clear. Remove its source
                # path before asserting which wheel this process imports.
                sys.path[:] = [p for p in sys.path if not p or not (
                    checkout == Path(p) or checkout in Path(p).parents)]
                assert not any(checkout == Path(p) or checkout in Path(p).parents
                               for p in sys.path if p), sys.path
                sys.path.insert(0, str(site))
                for package, name, source in zip(
                    ('tongxing_production.adapters.legacy', 'tongxing_production.delivery.posters'),
                    ('render_sermon_poster.swift', 'render_weekly_poster.swift'), source_paths
                ):
                    module = importlib.import_module(package)
                    assert Path(module.__file__).is_relative_to(site), module.__file__
                    installed = resources.files(package).joinpath(name)
                    assert installed.is_file(), (package, name)
                    assert installed.read_bytes() == source.read_bytes(), (package, name)
                from tongxing_production.adapters.legacy import build_sermon_poster
                from tongxing_production.delivery.posters import build
                assert build_sermon_poster.renderer_source().read_bytes() == source_paths[0].read_bytes()
                assert build.package_file(build.RENDERER).read_bytes() == source_paths[1].read_bytes()
            """)
            source_paths = [PACKAGE / "src" / Path(*package.split(".")) / name
                            for package, name in RESOURCES]
            run("-c", code, str(site), str(ROOT), *(str(path) for path in source_paths))

            # The retained script entry point must still reach the installed
            # package when invoked by absolute path from outside the checkout.
            cli_env = dict(env, PYTHONPATH=str(site))
            result = run(str(ROOT / 'tools/ops/run.py'), 'delivery.posters.build', "--help", environment=cli_env)
            self.assertIn("--page-id", result.stdout)


if __name__ == "__main__":
    unittest.main()
