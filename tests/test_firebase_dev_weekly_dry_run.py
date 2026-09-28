from pathlib import Path
import tempfile
import unittest

from scripts.firebase_dev_weekly_dry_run import DEV_CSS, feature_parity, paths


class FirebaseDevWeeklyDryRunTests(unittest.TestCase):
    def test_feature_parity_requires_current_js_html_and_css(self):
        with tempfile.TemporaryDirectory() as root:
            base, feature = (Path(root) / name for name in ("base", "feature"))
            base.mkdir()
            feature.mkdir()
            for name in ("app.mjs", "catalog.mjs", "published-weeks.mjs", "new-feature.mjs"):
                (feature / name).write_text("export const ready = true;\n")
                (base / name).write_text("export const ready = true;\n")
            (feature / "index.html").write_text('<main class="field-main">\n</main>\n')
            (base / "index.html").write_text(
                '  <meta name="robots" content="noindex,nofollow">\n'
                '<main class="field-main">\n'
                '    <p class="field-help dev-preview-notice" role="note">DEV</p>\n'
                '</main>\n'
                '  <script type="module" src="/dev-preview-label.mjs"></script>\n'
            )
            (feature / "style.css").write_text("body { color: red; }\n")
            (base / "style.css").write_text("body { color: red; }\n" + DEV_CSS)
            self.assertEqual(len(feature_parity(base, feature)), 4)

            (base / "new-feature.mjs").write_text("export const ready = false;\n")
            with self.assertRaisesRegex(ValueError, "new-feature.mjs"):
                feature_parity(base, feature)
            (base / "new-feature.mjs").write_text("export const ready = true;\n")
            (base / "style.css").write_text("body { color: blue; }\n" + DEV_CSS)
            with self.assertRaisesRegex(ValueError, "CSS"):
                feature_parity(base, feature)

    def test_preview_id_cannot_escape_isolated_namespace(self):
        self.assertEqual(paths("2026-10-04-preflight")[0],
                         "dry-run/2026-10-04-preflight/index.html")
        for unsafe in ("../pages", "a/b", ".", "x?week=other"):
            with self.subTest(unsafe=unsafe), self.assertRaises(ValueError):
                paths(unsafe)


if __name__ == "__main__":
    unittest.main()
