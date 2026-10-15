"""packages/fingerprint owns the algorithm; the web bundle carries a verified copy."""
import hashlib
from pathlib import Path
import unittest

from scripts import pipeline_compatibility_gate as gate

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "packages/fingerprint"
CORE = PACKAGE / "src/fingerprint-core.mjs"
CLI = PACKAGE / "bin/build_fingerprint_index.mjs"
BROWSER_COPY = ROOT / "apps/listening-web/fingerprint-core.mjs"


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class FingerprintPackageTests(unittest.TestCase):
    def test_browser_copy_is_byte_identical_to_the_package_source(self):
        self.assertEqual(sha256(BROWSER_COPY), sha256(CORE),
                         "copy packages/fingerprint/src/fingerprint-core.mjs over the web copy; never edit the copy")

    def test_cli_imports_only_the_package(self):
        text = CLI.read_text(encoding="utf-8")
        self.assertIn("from '../src/fingerprint-core.mjs'", text)
        for forbidden in ("sermon-dubbing-poc", "apps/", "/web/"):
            self.assertNotIn(forbidden, text)

    def test_python_identity_bindings_point_at_the_package(self):
        for script in ("scripts/sermon_pipeline.py", "scripts/run_post_live_subtitle_generation.py"):
            text = (ROOT / script).read_text(encoding="utf-8")
            with self.subTest(script=script):
                self.assertIn("packages", text)
                self.assertNotIn("sermon-dubbing-poc/web/fingerprint-core.mjs", text)
                self.assertNotIn("sermon-dubbing-poc/build_fingerprint_index.mjs", text)

    def test_package_is_a_protected_client_contract_input(self):
        self.assertTrue(gate.protected("packages/fingerprint/src/fingerprint-core.mjs"))
        self.assertTrue(gate.protected("packages/fingerprint/bin/build_fingerprint_index.mjs"))
        self.assertFalse(gate.protected("packages/production/README.md"))


if __name__ == "__main__":
    unittest.main()
