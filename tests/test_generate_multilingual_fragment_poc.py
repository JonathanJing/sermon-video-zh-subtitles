import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

from scripts import generate_multilingual_fragment_poc as subject
from scripts import prepare_sentence_interpretation_shadow as shadow
from tests.test_prepare_sentence_interpretation_shadow import write_segments


class GenerateMultilingualFragmentPocTests(unittest.TestCase):
    def test_mismatched_anchor_stops_before_secret_or_model_call(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "segments.json"
            write_segments(source)
            receipt = shadow.prepare_shadow(source, root / "shadow")
            anchor = Path(receipt["artifacts"]["anchorManifest"]["path"])
            package = Path(receipt["artifacts"]["englishSourcePackage"]["path"])
            anchor_value = json.loads(anchor.read_text(encoding="utf-8"))
            package_value = json.loads(package.read_text(encoding="utf-8"))
            subject.validate_source_inputs(anchor_value, package_value)
            package_value["anchors"]["artifact"]["jsonSha256"] = "0" * 64
            package.write_text(json.dumps(package_value), encoding="utf-8")
            source_id = anchor_value["sourceUnits"][0]["sourceUnitId"]
            argv = ["generate_multilingual_fragment_poc.py", "--anchor-manifest", str(anchor),
                    "--english-source-package", str(package), "--source-unit", source_id,
                    "--api-key-secret", "unused", "--out", str(root / "out")]
            with mock.patch.object(sys, "argv", argv), \
                 mock.patch.object(subject, "cloud_access_secret") as secret, \
                 mock.patch.object(subject, "request_json") as model:
                with self.assertRaisesRegex(ValueError, "different runs"):
                    subject.main()
                secret.assert_not_called()
                model.assert_not_called()

    def test_blocked_package_is_not_eligible_for_shadow_translation(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "segments.json"
            write_segments(source)
            receipt = shadow.prepare_shadow(source, root / "shadow")
            anchors = json.loads(Path(receipt["artifacts"]["anchorManifest"]["path"]).read_text())
            package = json.loads(Path(receipt["artifacts"]["englishSourcePackage"]["path"]).read_text())
            package["status"] = "blocked"
            package["candidateTranslationEligible"] = False
            with self.assertRaisesRegex(ValueError, "blocked"):
                subject.validate_source_inputs(anchors, package)


if __name__ == "__main__":
    unittest.main()
