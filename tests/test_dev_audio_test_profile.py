"""Offline checks of explicit Dev opt-in and frozen-profile admission."""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts import dev_audio_test_profile as subject


class DevAudioTestProfileTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.path = self.root / "profile.json"
        self.profile = {"schemaVersion": subject.SCHEMA, "status": "not_run",
            "productionDefaultsChanged": False, "humanApproval": False, "releaseEligible": False,
            "devTestBatchSize": {"formalTts": 2, "formalBackAsr": 4},
            "formalTts": {"primaryBatchSize": 1, "candidateBatchSizes": [2]},
            "formalBackAsr": {"primaryBatchSize": 1, "candidateBatchSizes": [4, 8]},
            "unrelated": {"preserve": "source metadata"}}
        self.write()

    def write(self):
        self.path.write_text(json.dumps(self.profile))

    def resolve(self, stage="tts", **kwargs):
        return subject.resolve(stage, enabled=True, profile_path=self.path, **kwargs)

    def test_production_default_and_explicit_batches_do_not_read_profile(self):
        with patch.object(Path, "read_bytes", side_effect=AssertionError("Production read Dev profile")):
            for stage in ("tts", "back-asr"):
                self.assertEqual(subject.resolve(stage), {"batchSize": 1, "profile": None})
                for batch in (1, 2, 4, 8):
                    self.assertEqual(subject.resolve(stage, batch_size=batch), {"batchSize": batch, "profile": None})

    def test_default_dev_batches_and_raw_file_identity_are_read_only(self):
        before = self.path.read_bytes()
        for stage, batch in (("tts", 2), ("back-asr", 4)):
            result = self.resolve(stage)
            self.assertEqual(result["batchSize"], batch)
            self.assertEqual(result["profile"], {"path": str(self.path.resolve()),
                "sha256": hashlib.sha256(before).hexdigest(), "stage": stage,
                "requestedBatchSize": batch, "defaultBatchSize": batch, "mode": "dev_test",
                "explicitBatchSize": False})
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(list(self.root.iterdir()), [self.path])

    def test_default_profile_is_used_only_in_dev_mode(self):
        with patch.object(subject, "DEFAULT_PROFILE", self.path):
            self.assertEqual(subject.resolve("tts", enabled=True)["batchSize"], 2)
            self.assertEqual(subject.resolve("back-asr", enabled=True)["batchSize"], 4)

    def test_dev_explicit_baselines_and_asr8_record_override(self):
        for stage, batches in (("tts", (1, 2)), ("back-asr", (1, 4, 8))):
            for batch in batches:
                result = self.resolve(stage, batch_size=batch)
                self.assertEqual(result["batchSize"], batch)
                self.assertEqual(result["profile"]["mode"], "dev_test_override")
                self.assertTrue(result["profile"]["explicitBatchSize"])
                self.assertEqual(result["profile"]["requestedBatchSize"], batch)
                self.assertEqual(result["profile"]["defaultBatchSize"], 2 if stage == "tts" else 4)

    def test_stage_specific_candidate_limits_reject_unapproved_batches(self):
        for stage, batches in (("tts", (4, 8)), ("back-asr", (2,))):
            for batch in batches:
                with self.assertRaisesRegex(ValueError, "not admitted"):
                    self.resolve(stage, batch_size=batch)

    def test_profile_without_opt_in_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "requires --dev-test"):
            subject.resolve("tts", profile_path=self.path)

    def test_invalid_batches_and_boolean_batches_are_rejected(self):
        for batch in (True, False, 0, 3, -1, 1.0, "2"):
            for enabled in (True, False):
                with self.subTest(batch=batch, enabled=enabled), self.assertRaises(ValueError):
                    subject.resolve("tts", enabled=enabled, batch_size=batch)

    def test_missing_corrupt_and_old_schema_profiles_are_rejected(self):
        for content in ("{", "[]", json.dumps({**self.profile, "schemaVersion": "local-production-next-dev-test-profile-v1"})):
            self.path.write_text(content)
            with self.assertRaises(ValueError):
                self.resolve()
        self.path.unlink()
        with self.assertRaises(ValueError):
            self.resolve()

    def test_approval_and_production_flags_must_be_exact_false(self):
        original = copy.deepcopy(self.profile)
        for key in ("productionDefaultsChanged", "humanApproval", "releaseEligible"):
            for value in (True, 0, "false", None):
                self.profile = {**original, key: value}
                self.write()
                with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                    self.resolve(batch_size=1)

    def test_published_or_missing_status_cannot_be_read_as_dev_pending(self):
        for status in ("approved", "published", "complete", None):
            self.profile["status"] = status
            self.write()
            with self.assertRaisesRegex(ValueError, "status"):
                self.resolve()

    def test_baseline_candidates_and_default_tampering_are_rejected(self):
        original = copy.deepcopy(self.profile)
        mutations = [("formalTts", "primaryBatchSize", 2),
                     ("formalBackAsr", "primaryBatchSize", True),
                     ("formalTts", "candidateBatchSizes", [2, 4]),
                     ("formalBackAsr", "candidateBatchSizes", [4, 4]),
                     ("formalTts", "candidateBatchSizes", [True]),
                     ("formalBackAsr", "candidateBatchSizes", [])]
        for section, field, value in mutations:
            self.profile = copy.deepcopy(original)
            self.profile[section][field] = value
            self.write()
            with self.subTest(section=section, field=field), self.assertRaises(ValueError):
                self.resolve()
        for value in (1, 4, True, "2"):
            self.profile = copy.deepcopy(original)
            self.profile["devTestBatchSize"]["formalTts"] = value
            self.write()
            with self.assertRaises(ValueError):
                self.resolve()

    def test_missing_defaults_or_audio_section_reject_even_override(self):
        original = copy.deepcopy(self.profile)
        for key in ("devTestBatchSize", "formalTts", "formalBackAsr"):
            self.profile = {k: v for k, v in original.items() if k != key}
            self.write()
            with self.assertRaises(ValueError):
                self.resolve(batch_size=1)

    def test_duplicate_keys_and_non_json_constants_are_rejected(self):
        for raw in ('{"humanApproval":true,' + self.path.read_text()[1:],
                    self.path.read_text().replace('"source metadata"', "NaN")):
            self.path.write_text(raw)
            with self.assertRaises(ValueError):
                self.resolve()

    def test_receipt_hash_tracks_raw_bytes_including_whitespace(self):
        before = self.resolve()["profile"]["sha256"]
        self.path.write_bytes(self.path.read_bytes() + b"\n")
        after = self.resolve()["profile"]["sha256"]
        self.assertNotEqual(before, after)
        self.assertEqual(after, hashlib.sha256(self.path.read_bytes()).hexdigest())

    def test_cli_defaults_and_explicit_profile(self):
        parser = argparse.ArgumentParser()
        subject.add_arguments(parser)
        empty = parser.parse_args([])
        self.assertFalse(empty.dev_test)
        self.assertIsNone(empty.dev_test_profile)
        chosen = parser.parse_args(["--dev-test", "--dev-test-profile", str(self.path)])
        self.assertTrue(chosen.dev_test)
        self.assertEqual(chosen.dev_test_profile, self.path)


if __name__ == "__main__":
    unittest.main()
