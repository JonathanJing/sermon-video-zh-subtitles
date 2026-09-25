import importlib.util
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("docs_change_gate", ROOT / "scripts/docs_change_gate.py")
gate = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(gate)


class DocsChangeGateTests(unittest.TestCase):
    def test_only_repository_documentation_assets_get_fast_path(self):
        allowed = (
            "README.md",
            "README.zh.md",
            "docs/workflows/README.zh.md",
            "docs/diagrams/four-layer-production-workflow.svg",
            "docs/diagrams/diagram-specs.json",
            "docs/assets/firebase-production.jpg",
        )
        rejected = (
            "apps/tongxing-ios/Assets.xcassets/icon.png",
            "experiments/sermon-dubbing-poc/web/README.md",
            "docs/diagrams/render_diagrams.py",
            "docs/schema.json",
            ".github/workflows/python-tests.yml",
        )
        for path in allowed:
            with self.subTest(path=path):
                self.assertTrue(gate.is_documentation_path(path))
        for path in rejected:
            with self.subTest(path=path):
                self.assertFalse(gate.is_documentation_path(path))

    def test_changed_paths_fails_closed_for_missing_push_base(self):
        self.assertEqual(gate.changed_paths("0" * 40, "f" * 40, "push"), [])

    def test_empty_or_mixed_change_set_requires_full_tests(self):
        self.assertFalse(gate.documentation_only([]))
        self.assertFalse(gate.documentation_only(["README.md", "scripts/sermon_production_supervisor.py"]))
        self.assertTrue(gate.documentation_only(["README.md", "docs/diagrams/diagram-specs.json"]))

    def test_image_signature_catches_wrong_extension(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "capture.png"
            path.write_bytes(b"\xff\xd8\xff" + b"jpeg payload")
            with self.assertRaisesRegex(ValueError, "signature"):
                gate.check_image(path)

    def test_broken_relative_link_blocks_docs_fast_path(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "README.md"
            path.write_text("![missing](docs/missing.svg)", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "Broken local link"):
                gate.check_markdown_links(path)


if __name__ == "__main__":
    unittest.main()
