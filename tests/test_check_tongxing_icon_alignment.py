"""A small synthetic check of the icon gate's success and rejection paths."""
import contextlib
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools.development import check_tongxing_icon_alignment as gate


class IconAlignmentTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.web = self.root / "apps/listening-web"
        reader = self.web / "reader"
        reader.mkdir(parents=True)
        native = self.root / "apps/tongxing-ios/App"
        native.mkdir(parents=True)
        (native / "App.swift").write_text('Image(systemName: "play.fill")\n')
        (self.web / "icons.svg").write_text('<svg><symbol id="play.fill"/></svg>')
        (self.web / "icons.mjs").write_text("const names = new Set(['play.fill'])")
        (self.web / "index.html").write_text('<use href="/icons.svg#play.fill">')
        (reader / "index.html").write_text('<use href="/icons.svg#play.fill">')
        (self.web / "style.css").write_bytes(b"base styles")
        (reader / "styles.css").write_bytes(b"base styles and reader styles")

    def test_repository_root_matches_checkout(self):
        self.assertEqual(gate.ROOT, Path(__file__).resolve().parents[1])

    def test_matching_native_web_and_reader_icons_pass(self):
        with patch.object(gate, "ROOT", self.root), patch.object(gate, "WEB", self.web), \
             patch.object(gate, "DEV", self.web / "reader"):
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                gate.check()
        self.assertIn("PASS: 1 native symbols resolved by 1 SVG drawings", output.getvalue())

    def test_missing_svg_drawing_fails_closed(self):
        (self.root / "apps/tongxing-ios/App/App.swift").write_text('Image(systemName: "pause.fill")\n')
        with patch.object(gate, "ROOT", self.root), patch.object(gate, "WEB", self.web), \
             patch.object(gate, "DEV", self.web / "reader"):
            with self.assertRaisesRegex(ValueError, "iOS symbols missing SVG drawings: \\['pause.fill'\\]"):
                gate.check()


if __name__ == "__main__":
    unittest.main()
