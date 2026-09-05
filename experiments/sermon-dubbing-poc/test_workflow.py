import copy
import json
from pathlib import Path
import tempfile
import unittest

from align_weekly_source import match_blocks
from poc import sha256, write_json
from run_qwen_training_smoke import validate_inputs
from weekly_dubbing import validate_frozen, validate_review
from spoken_text import cardinal, spoken_text
from check_weekly_timing import budgets


class SpeakerIsolationTests(unittest.TestCase):
    def fixture(self, work):
        (work / "sample.wav").write_bytes(b"speaker audio fixture")
        digest = sha256(work / "sample.wav")
        write_json(work / "protection.json", {"protectedIds": ["test-source"], "protectedDates": ["20260906"]})
        sources = [{"sourceId": f"source-{i}", "speaker": "Christine Caine", "date": f"2026010{i + 1}", "split": "train", "sha256": digest} for i in range(3)]
        write_json(work / "authorization.json", {"status": "confirmed_by_user", "purposes": ["voice_training", "chinese_dubbing"], "sources": sources})
        return {"schemaVersion": "sermon-voice-multisource-training-v2", "purpose": "engineering_multisermon_training", "productionTrainingAdmission": False,
            "speaker": "Christine Caine", "speakerKey": "christine_caine", "sourceId": "source-0", "sourceSha256": digest,
            "protectedEvaluationOverlap": False, "sources": sources, "samples": [{"file": "sample.wav", "sha256": digest, "text": "An English sentence.", "language": "English", "speaker": "Christine Caine", "split": "train", "sourceId": "source-0", "sourceSha256": digest, "durationSeconds": 6}],
            "sampleSeconds": 6, "reference": {"file": "sample.wav", "sha256": digest}, "protectionSha256": sha256(work / "protection.json")}

    def test_separate_speaker_slot_and_wrong_speaker_rejection(self):
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp)
            manifest = self.fixture(work)
            write_json(work / "research-inputs.json", manifest)
            self.assertEqual(validate_inputs(work)["speakerKey"], "christine_caine")
            for mutate in [lambda m: m["samples"][0].update(speaker="Eric Geiger"), lambda m: m["sources"][1].update(speaker="Doug Fields"), lambda m: m.update(speakerKey="../../voice")]:
                bad = copy.deepcopy(manifest)
                mutate(bad)
                write_json(work / "research-inputs.json", bad)
                with self.assertRaises(ValueError):
                    validate_inputs(work)

    def test_reserved_sermon_alias_date_and_reference_fail_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp)
            manifest = self.fixture(work)
            for mutate in [lambda m: m["sources"][1].update(date="20260906"), lambda m: m["sources"][1].update(split="dev"), lambda m: m.update(sourceId="another-speaker-source"), lambda m: m["reference"].update(file="../outside.wav")]:
                bad = copy.deepcopy(manifest)
                mutate(bad)
                write_json(work / "research-inputs.json", bad)
                with self.assertRaises((ValueError, FileNotFoundError)):
                    validate_inputs(work)


class SaturdayExtensionTests(unittest.TestCase):
    def test_reading_change_invalidates_audio_job(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "reading.json"
            path.write_text("reviewed text")
            job = {"inputs": {"reading": {"path": str(path), "sha256": sha256(path)}}}
            validate_frozen(job)
            path.write_text("new translation")
            with self.assertRaisesRegex(ValueError, "Saturday / voice input changed"):
                validate_frozen(job)

    def review_fixture(self, work):
        (work / "audio").mkdir()
        (work / "audio/zh-natural.mp3").write_bytes(b"audio candidate")
        write_json(work / "job.json", {"inputs": {}, "voice": {"checkpointSha256": "checkpoint"}, "units": [{"text": "中文"}], "inheritedReview": {"generationComplete": False}})
        return {"jobSha256": sha256(work / "job.json"), "mp3Sha256": sha256(work / "audio/zh-natural.mp3"), "checkpointSha256": "checkpoint",
            "humanApproval": False, "reviewedBy": None, "reviewedAt": None, "checks": {k: "pending" for k in ["speakerIdentity", "voiceSimilarity", "chineseFluency", "pronunciation", "noOmissionOrRepetition", "sameVideoSynchronization"]}}

    def test_sample_acceptance_does_not_approve_new_weekly_audio(self):
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp)
            review = self.review_fixture(work)
            review.update(sampleAccepted=True)
            write_json(work / "audio-review.json", review)
            with self.assertRaisesRegex(ValueError, "Human audio review"):
                validate_review(work)

    def test_audio_review_cannot_bypass_failed_saturday_completion(self):
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp)
            review = self.review_fixture(work)
            review.update(humanApproval=True, reviewedBy="fixture reviewer", reviewedAt="2026-09-05T00:00:00Z")
            review["checks"] = dict.fromkeys(review["checks"], "pass")
            write_json(work / "audio-review.json", review)
            write_json(work / "audio/asr-screening.json", {"jobSha256": sha256(work / "job.json"), "results": [{"sha256": review["mp3Sha256"], "fullDecode": "pass", "screenedUnits": 1}]})
            with self.assertRaisesRegex(ValueError, "Saturday generation"):
                validate_review(work)

    def test_modified_mp3_invalidates_earlier_review(self):
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp)
            review = self.review_fixture(work)
            write_json(work / "audio-review.json", review)
            (work / "audio/zh-natural.mp3").write_bytes(b"new audio")
            with self.assertRaisesRegex(ValueError, "Review is stale"):
                validate_review(work)


class AcousticAnchorTests(unittest.TestCase):
    def test_measured_anchors_ignore_synthetic_reading_timestamps(self):
        words = [{"text": word, "start": 10 + i, "end": 10.8 + i} for i, word in enumerate("we can bring our questions to God today".split())]
        anchors, issues = match_blocks([{"id": 4, "en": "We can bring our questions to God today.", "start": 0, "end": 999}], words)
        self.assertEqual(issues, [])
        self.assertEqual(anchors[0]["start"], 10)
        self.assertEqual(anchors[0]["end"], 17.8)

    def test_unmatched_source_boundary_requires_review(self):
        words = [{"text": word, "start": i, "end": i + .5} for i, word in enumerate("we can bring our questions".split())]
        _, issues = match_blocks([{"id": 0, "en": "We can bring our questions and our fears to God today."}], words)
        self.assertIn("unmatched_boundary_words", [i["reason"] for i in issues])


class SpeechAndTimingTests(unittest.TestCase):
    def test_numerals_and_divine_pronouns_have_explicit_spoken_forms(self):
        source = "2025年，600名学生读诗篇137篇，向祢祷告，信靠祂。"
        self.assertEqual(spoken_text(source), "二零二五年，六百名学生读诗篇一百三十七篇，向你祷告，信靠他。")
        self.assertEqual(source, "2025年，600名学生读诗篇137篇，向祢祷告，信靠祂。")
        self.assertEqual([cardinal(n) for n in [0, 10, 11, 101, 1010]], ["零", "十", "十一", "一百零一", "一千零一十"])

    def test_unhandled_decimal_and_identifiers_are_not_corrupted(self):
        self.assertEqual(spoken_text("3.14 与 A123"), "3.14 与 A123")

    def test_overflow_is_a_repair_item_not_speech_trimming(self):
        blocks = [{"id": 0, "en": "one", "zh": "一"}, {"id": 1, "en": "two", "zh": "二"}]
        anchors = [{"blockId": 0, "start": 0, "end": 4, "issues": []}, {"blockId": 1, "start": 5, "end": 9, "issues": []}]
        cues = [{"blockId": 0, "start": 0, "end": 6}, {"blockId": 1, "start": 6.45, "end": 9.45}]
        rows, failures = budgets(blocks, anchors, cues, 10)
        self.assertEqual(rows[0]["naturalSeconds"], 6)
        self.assertEqual(rows[0]["overflowSeconds"], 1)
        self.assertEqual(failures, [{"blockId": 0, "reason": "natural_chinese_exceeds_video_slot", "overflowSeconds": 1}])

    def test_short_speech_fits_without_altering_its_duration(self):
        rows, failures = budgets([{"id": 0, "en": "source", "zh": "中文"}], [{"blockId": 0, "start": 2, "end": 7, "issues": []}], [{"blockId": 0, "start": 0, "end": 4}], 10)
        self.assertEqual(failures, [])
        self.assertEqual(rows[0]["naturalSeconds"], 4)
        self.assertEqual(rows[0]["availableSeconds"], 8)


if __name__ == "__main__":
    unittest.main()
