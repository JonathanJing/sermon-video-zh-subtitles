from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from scripts import sermon_source_text_review as review_module


def digest(contents):
    return hashlib.sha256(contents).hexdigest()


class SourceTextReviewTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.audio = self.root / "source.m4a"
        self.asr = self.root / "asr.json"
        self.evidence = self.root / "audio-review.json"
        self.review_path = self.root / "source-review.json"
        self.audio.write_bytes(b"fixed source audio fixture")
        self.asr.write_text('{"text":"committed tonight to shield"}')
        self.evidence.write_text('{"negation":"committed to not shield"}')
        self.segments = [
            {"id": 44, "start": 1036.647, "end": 1064.012,
             "text": "But I have committed tonight to shield you.",
             "source": "gpt-transcribe-reading-layout",
             "timingQuality": "synthetic_not_for_subtitles", "metadata": {"sourceIds": [0]}},
            {"id": 7, "start": 1064.012, "end": 1090.0, "text": "Let's see the end of the psalm."},
        ]
        self.review = {
            "schemaVersion": review_module.SCHEMA,
            "reviewType": "model", "model": "gpt-6-astra", "humanApproval": False,
            "status": "approved_for_source_correction",
            "authority": "user_directed_conversation_review",
            "reviewedBy": "Astra conversation review", "reviewedAt": "2026-09-05T12:00:00Z",
            "sourceAudioSha256": digest(self.audio.read_bytes()),
            "asrSha256": digest(self.asr.read_bytes()),
            "evidence": [{"path": str(self.evidence), "sha256": digest(self.evidence.read_bytes())}],
            "patches": [{
                "segmentId": 44, "originalTextSha256": digest(self.segments[0]["text"].encode()),
                "correctedText": "But I have committed to not shield you.",
                "reason": "Reviewed source evidence confirms the negation.",
                "evidenceSha256": digest(self.evidence.read_bytes()),
            }],
        }

    def apply(self, review=None, segments=None):
        self.review_path.write_text(json.dumps(self.review if review is None else review))
        return review_module.apply_review(
            self.segments if segments is None else segments,
            self.review_path, self.audio, self.asr,
        )

    def test_applies_only_reviewed_text_and_retains_model_provenance(self):
        original = deepcopy(self.segments)
        files_before = {path: path.read_bytes() for path in [self.audio, self.asr, self.evidence]}
        corrected, provenance = self.apply()
        expected = deepcopy(original)
        expected[0]["text"] = "But I have committed to not shield you."
        self.assertEqual(corrected, expected)
        self.assertEqual(self.segments, original)
        self.assertEqual([row["id"] for row in corrected], [44, 7])
        self.assertEqual(provenance["reviewSha256"], digest(self.review_path.read_bytes()))
        self.assertEqual(provenance["sourceAudioSha256"], digest(self.audio.read_bytes()))
        self.assertEqual(provenance["asrSha256"], digest(self.asr.read_bytes()))
        self.assertEqual(provenance["correctedSegmentIds"], [44])
        self.assertEqual(provenance["patchCount"], 1)
        self.assertEqual(provenance["patches"][0]["correctedTextSha256"], digest(expected[0]["text"].encode()))
        self.assertEqual(provenance["reviewType"], "model")
        self.assertEqual(provenance["model"], "gpt-6-astra")
        self.assertIs(provenance["humanApproval"], False)
        self.assertEqual(provenance["status"], "approved_for_source_correction")
        self.assertEqual(files_before, {path: path.read_bytes() for path in files_before})
        corrected[0]["metadata"]["sourceIds"].append(1)
        self.assertEqual(self.segments, original)

    def test_stale_source_audio_is_rejected(self):
        self.audio.write_bytes(b"changed source")
        with self.assertRaisesRegex(ValueError, "stale sourceAudioSha256"):
            self.apply()

    def test_stale_asr_is_rejected(self):
        self.asr.write_text('{"text":"changed ASR"}')
        with self.assertRaisesRegex(ValueError, "stale asrSha256"):
            self.apply()

    def test_stale_original_segment_text_is_rejected(self):
        self.segments[0]["text"] += " A different sentence."
        with self.assertRaisesRegex(ValueError, "segment 44 text changed"):
            self.apply()

    def test_changed_evidence_is_rejected(self):
        self.evidence.write_text('{"negation":"unresolved"}')
        with self.assertRaisesRegex(ValueError, "evidence changed"):
            self.apply()

    def test_all_evidence_is_verified_even_if_no_patch_references_it(self):
        other = self.root / "other-evidence.json"
        other.write_text('{"review":"original"}')
        self.review["evidence"].append({"path": str(other), "sha256": digest(other.read_bytes())})
        other.write_text('{"review":"changed"}')
        with self.assertRaisesRegex(ValueError, "evidence changed"):
            self.apply()

    def test_missing_bound_files_are_rejected(self):
        for path in [self.audio, self.asr, self.evidence]:
            with self.subTest(file=path.name):
                contents = path.read_bytes()
                path.unlink()
                with self.assertRaisesRegex(ValueError, "unavailable"):
                    self.apply()
                path.write_bytes(contents)

    def test_model_identity_cannot_be_promoted_or_mislabelled(self):
        mutations = {
            "schemaVersion": [1, "sermon-source-text-review-v0"],
            "reviewType": ["human", None],
            "model": ["gpt-5.6-sol", None],
            "humanApproval": [True, 0, "false", None],
            "status": ["approved", "pending", "approved_for_synthesis"],
            "authority": ["automatic_review", "human_review", None],
        }
        for field, values in mutations.items():
            for value in values:
                with self.subTest(field=field, value=value):
                    review = deepcopy(self.review)
                    review[field] = value
                    with self.assertRaisesRegex(ValueError, "model identity"):
                        self.apply(review)

    def test_review_metadata_is_required_and_timestamp_has_timezone(self):
        for field, values in {
            "reviewedBy": [None, "", "  ", True],
            "reviewedAt": [None, "", "  ", True, "yesterday", "2026-09-05", "2026-09-05T12:00:00"],
        }.items():
            for value in values:
                with self.subTest(field=field, value=value):
                    review = deepcopy(self.review)
                    review[field] = value
                    with self.assertRaises(ValueError):
                        self.apply(review)

    def test_hashes_must_be_valid_sha256_values(self):
        for location, field in [("review", "sourceAudioSha256"), ("review", "asrSha256"),
                                ("evidence", "sha256"), ("patch", "originalTextSha256"),
                                ("patch", "evidenceSha256")]:
            for value in [None, "", "not-a-hash", "F" * 64, 64]:
                with self.subTest(location=location, field=field, value=value):
                    review = deepcopy(self.review)
                    target = review if location == "review" else review["evidence" if location == "evidence" else "patches"][0]
                    target[field] = value
                    with self.assertRaisesRegex(ValueError, "SHA-256"):
                        self.apply(review)

    def test_patch_evidence_must_reference_verified_evidence(self):
        self.review["patches"][0]["evidenceSha256"] = "a" * 64
        with self.assertRaisesRegex(ValueError, "missing its verified evidence"):
            self.apply()

    def test_evidence_requires_distinct_existing_paths(self):
        for evidence in [None, [], "file", [None], [{"path": "", "sha256": "a" * 64}],
                         [self.review["evidence"][0], deepcopy(self.review["evidence"][0])]]:
            with self.subTest(evidence=evidence):
                review = deepcopy(self.review)
                review["evidence"] = evidence
                with self.assertRaises(ValueError):
                    self.apply(review)

    def test_relative_evidence_paths_use_review_directory(self):
        self.review["evidence"][0]["path"] = self.evidence.name
        _, provenance = self.apply()
        self.assertEqual(provenance["evidence"][0]["path"], str(self.evidence.resolve()))

    def test_evidence_path_aliases_are_duplicates(self):
        self.review["evidence"].append({"path": self.evidence.name, "sha256": digest(self.evidence.read_bytes())})
        with self.assertRaisesRegex(ValueError, "repeated evidence paths"):
            self.apply()

    def test_empty_or_malformed_patch_lists_are_rejected(self):
        for patches in [None, [], {}, "none", [None], [{}]]:
            with self.subTest(patches=patches):
                review = deepcopy(self.review)
                review["patches"] = patches
                with self.assertRaises(ValueError):
                    self.apply(review)

    def test_unknown_duplicate_or_boolean_patch_ids_are_rejected(self):
        for value in [False, True, "44", 999, -1, None, 44.0]:
            with self.subTest(value=value):
                review = deepcopy(self.review)
                review["patches"][0]["segmentId"] = value
                with self.assertRaisesRegex(ValueError, "unknown or repeated segment ID"):
                    self.apply(review)
        self.review["patches"].append(deepcopy(self.review["patches"][0]))
        with self.assertRaisesRegex(ValueError, "unknown or repeated segment ID"):
            self.apply()

    def test_empty_noop_or_unexplained_corrections_are_rejected(self):
        for field, values in {
            "correctedText": [None, "", "  ", True, self.segments[0]["text"]],
            "reason": [None, "", "  ", True],
        }.items():
            for value in values:
                with self.subTest(field=field, value=value):
                    review = deepcopy(self.review)
                    review["patches"][0][field] = value
                    with self.assertRaises(ValueError):
                        self.apply(review)

    def test_patch_cannot_smuggle_timing_or_other_fields(self):
        self.review["patches"][0]["start"] = 900
        with self.assertRaisesRegex(ValueError, "unknown fields"):
            self.apply()

    def test_invalid_or_duplicate_source_segment_ids_are_rejected(self):
        for value in [True, "44", 44.0, None, -1, 7]:
            with self.subTest(value=value):
                segments = deepcopy(self.segments)
                segments[0]["id"] = value
                with self.assertRaisesRegex(ValueError, "invalid or repeated IDs"):
                    self.apply(segments=segments)

    def test_invalid_source_segment_data_is_rejected(self):
        for segments in [[], {}, [None], [{"id": 44, "text": ""}], [{"id": 44, "text": None}]]:
            with self.subTest(segments=segments):
                with self.assertRaises(ValueError):
                    self.apply(segments=segments)

    def test_failure_does_not_partially_mutate_segments(self):
        original = deepcopy(self.segments)
        self.review["patches"].append({**self.review["patches"][0], "segmentId": 999})
        with self.assertRaises(ValueError):
            self.apply()
        self.assertEqual(self.segments, original)

    def test_multiple_patches_keep_source_order(self):
        self.review["patches"].insert(0, {
            "segmentId": 7, "originalTextSha256": digest(self.segments[1]["text"].encode()),
            "correctedText": "Let's see the end of this psalm.", "reason": "Second reviewed correction.",
            "evidenceSha256": digest(self.evidence.read_bytes()),
        })
        corrected, provenance = self.apply()
        self.assertEqual([row["id"] for row in corrected], [44, 7])
        self.assertEqual(provenance["correctedSegmentIds"], [44, 7])
        self.assertEqual(provenance["patchCount"], 2)

    def test_review_change_updates_provenance_hash(self):
        _, first = self.apply()
        self.review["reviewedAt"] = "2026-09-05T13:00:00Z"
        _, second = self.apply()
        self.assertNotEqual(first["reviewSha256"], second["reviewSha256"])

    def test_missing_malformed_or_duplicate_key_review_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "unavailable"):
            review_module.apply_review(self.segments, self.review_path, self.audio, self.asr)
        for contents in [b"{", b"[]", b"\xff", b'{"humanApproval":false,"humanApproval":true}']:
            with self.subTest(contents=contents):
                self.review_path.write_bytes(contents)
                with self.assertRaises(ValueError):
                    review_module.apply_review(self.segments, self.review_path, self.audio, self.asr)


if __name__ == "__main__":
    unittest.main()
