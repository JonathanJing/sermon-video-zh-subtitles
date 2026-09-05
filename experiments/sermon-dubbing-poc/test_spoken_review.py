"""Spoken-review contracts and cache provenance; fake media, no model calls."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from align_weekly_source import match_blocks
from apply_spoken_review import CHECKS, SCHEMA, derive, make_units, reviewed_blocks, text_hash, validate_job_review
from check_weekly_timing import anchor_review_type, budgets, load_anchors
from poc import sha256, write_json
from run_weekly_dubbing import validate_cached_stages, validate_timing
from test_resume_integrity import candidate_fixture, modify, snapshot
from weekly_dubbing import read, validate_frozen, validate_review


def review_fixture(parent, path, chinese="更适合口播的第一句。", correction=None):
    job = read(parent / "job.json")
    block = job["blocks"][0]
    change = {"blockId": block["id"], "originalEnglishSha256": text_hash(block["en"]),
        "originalChineseSha256": text_hash(block["zh"]), "approvedChinese": chinese, "reason": "Fixture preserves the reviewed meaning"}
    if correction:
        change["sourceCorrection"] = {"english": correction, "reviewType": "model", "reason": "Fixture source risk review",
            "evidenceSha256": sha256(parent / "source.wav")}
    review = {"schemaVersion": SCHEMA, "parentJobSha256": sha256(parent / "job.json"), "reviewType": "model", "model": "gpt-6-astra",
        "humanApproval": False, "status": "approved_for_synthesis", "reviewedAt": "2026-09-06T00:00:00Z", "reviewedBy": "fixture model reviewer",
        "authority": "user_directed_conversation_review", "reviewedBlockIds": [b["id"] for b in job["blocks"]],
        "checks": dict.fromkeys(CHECKS, "pass"), "unresolvedTextIssues": [],
        "evidence": [{"path": str(parent / "source.wav"), "sha256": sha256(parent / "source.wav"), "kind": "machine_asr_evidence"}], "blocks": [change]}
    write_json(path, review)
    return review


def acoustic_words(parent, first="First corrected English sentence for everyone."):
    second = read(parent / "job.json")["blocks"][1]["en"]
    words = [{"text": word, "start": i * .5, "end": i * .5 + .4} for i, word in enumerate((first + " " + second).split())]
    write_json(parent / "source-alignment/words.json", words)
    return words


class SpokenReviewTests(unittest.TestCase):
    def fixture(self, root, **kwargs):
        parent = root / "parent"
        parent.mkdir()
        candidate_fixture(parent)
        review = root / "review.json"
        review_fixture(parent, review, **kwargs)
        return parent, root / "derived", review

    def test_full_review_coverage_and_original_text_hashes_are_required(self):
        changes = [lambda d: d.update(reviewedBlockIds=[0]), lambda d: d.update(reviewedBlockIds=[0, 0]),
            lambda d: d.update(reviewedBlockIds=[1, 0]), lambda d: d.update(parentJobSha256="old-job"),
            lambda d: d["blocks"][0].update(blockId=99), lambda d: d["blocks"].append(copy.deepcopy(d["blocks"][0])),
            lambda d: d["blocks"][0].update(originalEnglishSha256="other-English"),
            lambda d: d["blocks"][0].update(originalChineseSha256="other-Chinese"),
            lambda d: d["blocks"][0].update(approvedChinese=" ")]
        for i, change in enumerate(changes):
            with self.subTest(case=i), tempfile.TemporaryDirectory() as tmp:
                parent, _, review = self.fixture(Path(tmp))
                data = read(review)
                change(data)
                write_json(review, data)
                before = snapshot(parent)
                with self.assertRaises(ValueError):
                    reviewed_blocks(parent, review)
                self.assertEqual(snapshot(parent), before)

    def test_model_approval_never_becomes_human_approval_or_skips_review_checks(self):
        changes = [{"humanApproval": True}, {"reviewType": "human"}, {"model": "different-model"}, {"authority": ""},
            {"status": "pending"}, {"reviewedAt": None}, {"reviewedBy": None}, {"checks": {}},
            {"unresolvedTextIssues": ["source wording uncertain"]}]
        for change in changes:
            with self.subTest(change=change), tempfile.TemporaryDirectory() as tmp:
                parent, out, review = self.fixture(Path(tmp))
                data = read(review)
                data.update(change)
                write_json(review, data)
                with self.assertRaises(ValueError):
                    derive(parent, out, review)
                self.assertFalse(out.exists())

    def test_english_correction_requires_hash_bound_evidence(self):
        for field, value in [("evidenceSha256", "not-in-evidence"), ("evidenceSha256", None), ("reviewType", "human"), ("reason", ""), ("english", " ")]:
            with self.subTest(field=field, value=value), tempfile.TemporaryDirectory() as tmp:
                parent, _, review = self.fixture(Path(tmp), correction="Corrected English.")
                data = read(review)
                data["blocks"][0]["sourceCorrection"][field] = value
                write_json(review, data)
                with self.assertRaisesRegex(ValueError, "English corrections require"):
                    reviewed_blocks(parent, review)
        with tempfile.TemporaryDirectory() as tmp:
            parent, _, review = self.fixture(Path(tmp), correction="Corrected English.")
            blocks = reviewed_blocks(parent, review)
            self.assertEqual(blocks[0]["en"], "Corrected English.")
            self.assertEqual(read(parent / "job.json")["blocks"][0]["en"], "First English sentence.")
            (parent / "source.wav").write_bytes(b"changed source evidence")
            with self.assertRaisesRegex(ValueError, "evidence changed"):
                reviewed_blocks(parent, review)

    def test_renumbered_wav_and_asr_reuse_preserves_original_provenance(self):
        long_chinese = "甲" * 60 + "。" + "乙" * 60 + "。"
        with tempfile.TemporaryDirectory() as tmp:
            parent, out, review = self.fixture(Path(tmp), chinese=long_chinese)
            before = snapshot(parent)
            old = read(parent / "render/unit-0001.json")
            with patch("subprocess.run", side_effect=AssertionError("No model/SSH calls")):
                result = derive(parent, out, review)
                job = read(out / "job.json")
                validate_frozen(job)
                validate_cached_stages(out, job)
            self.assertEqual(result["regenerateUnitIds"], [0, 1])
            self.assertEqual(result["reusedUnits"], [{"unitId": 2, "parentUnitId": 1}])
            self.assertEqual((out / "render/unit-0002.wav").read_bytes(), (parent / "render/unit-0001.wav").read_bytes())
            reused = read(out / "render/unit-0002.json")
            self.assertEqual(reused["identity"]["jobSha256"], sha256(out / "job.json"))
            self.assertEqual(reused["unit"]["id"], 2)
            self.assertEqual(reused["reusedFrom"]["unitId"], 1)
            self.assertEqual(reused["reusedFrom"]["generationIdentity"], old["identity"])
            self.assertEqual(reused["reusedFrom"]["receiptSha256"], sha256(parent / "render/unit-0001.json"))
            screened = read(out / "audio/unit-screening/unit-0002.json")
            self.assertEqual(screened["unitId"], 2)
            self.assertEqual(screened["blockId"], 1)
            self.assertEqual(screened["identity"], read(parent / "audio/unit-screening/unit-0001.json")["identity"])
            self.assertEqual(screened["reusedFrom"]["sha256"], sha256(parent / "audio/unit-screening/unit-0001.json"))
            self.assertFalse(job["spokenReview"]["humanApproval"])
            self.assertEqual(job["humanAudioReview"], "pending")
            self.assertFalse((out / "audio-review.json").exists())
            self.assertEqual(snapshot(parent), before)

    def test_changed_reused_wav_receipts_fail_before_creating_output(self):
        changes = [lambda p: (p / "render/unit-0001.wav").write_bytes(b"replaced unit"),
            lambda p: (p / "render/unit-0001.json").unlink(),
            lambda p: modify(p, "render/unit-0001.json", lambda d: d["unit"].update(text="other text")),
            lambda p: modify(p, "render/unit-0001.json", lambda d: d["identity"].update(jobSha256="other-job")),
            lambda p: modify(p, "render/unit-0001.json", lambda d: d["identity"].update(checkpointSha256="other-speaker"))]
        for i, change in enumerate(changes):
            with self.subTest(case=i), tempfile.TemporaryDirectory() as tmp:
                parent, out, review = self.fixture(Path(tmp))
                change(parent)
                with self.assertRaises((ValueError, OSError)):
                    derive(parent, out, review)
                self.assertFalse(out.exists())

    def test_stale_reused_asr_cannot_reach_rendering_and_missing_asr_can_resume(self):
        for field in ["audioSha256", "expected", "revision", "missing"]:
            with self.subTest(field=field), tempfile.TemporaryDirectory() as tmp:
                parent, out, review = self.fixture(Path(tmp))
                if field == "missing":
                    (parent / "audio/unit-screening/unit-0001.json").unlink()
                    derive(parent, out, review)
                    self.assertFalse((out / "audio/unit-screening/unit-0001.json").exists())
                    validate_cached_stages(out, read(out / "job.json"))
                else:
                    modify(parent, "audio/unit-screening/unit-0001.json", lambda d: d["identity"].update({field: "stale"}))
                    with patch("subprocess.run", side_effect=AssertionError("No model/SSH calls")), self.assertRaises(ValueError):
                        derive(parent, out, review)
                        validate_cached_stages(out, read(out / "job.json"))

    def test_revised_english_is_rematched_to_existing_words_without_new_asr(self):
        correction = "First corrected English sentence for everyone."
        with tempfile.TemporaryDirectory() as tmp:
            parent, out, review = self.fixture(Path(tmp), correction=correction)
            words = acoustic_words(parent, correction)
            before = snapshot(parent)
            with patch("subprocess.run", side_effect=AssertionError("No new acoustic/model work")), patch("align_weekly_source.match_blocks", wraps=match_blocks) as rematch:
                result = derive(parent, out, review)
            job = read(out / "job.json")
            rematch.assert_called_once_with(job["blocks"], words)
            report = read(out / "source-alignment/report.json")
            self.assertEqual((report["blocks"], report["issues"]), match_blocks(job["blocks"], words))
            self.assertEqual(report["wordEvidence"]["sha256"], sha256(parent / "source-alignment/words.json"))
            self.assertEqual(report["englishBlocksSha256"], text_hash(json.dumps([{"id": b["id"], "en": b["en"]} for b in job["blocks"]], ensure_ascii=False, sort_keys=True)))
            self.assertEqual(result["sourceAlignment"], "recomputed_from_existing_words")
            self.assertEqual(snapshot(parent), before)

    def test_source_word_reuse_chain_is_hash_bound(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            parent, out, review = self.fixture(root)
            archive = root / "archive"
            archive.mkdir()
            words = [{"text": "English", "start": 0, "end": 1}]
            write_json(archive / "words.json", words)
            write_json(archive / "report.json", {"sourceAudioSha256": sha256(parent / "source.wav")})
            modify(parent, "source-alignment/report.json", lambda d: d.update(reusedFrom={"path": str(archive / "report.json"), "sha256": sha256(archive / "report.json")}))
            result = derive(parent, out, review)
            self.assertEqual(result["sourceAlignment"], "recomputed_from_existing_words")
            self.assertEqual(read(out / "source-alignment/report.json")["wordEvidence"]["path"], str((archive / "words.json").resolve()))
            write_json(archive / "report.json", {"sourceAudioSha256": "changed"})
            with self.assertRaisesRegex(ValueError, "reuse evidence changed"):
                derive(parent, root / "second", review)

    def test_spoken_extension_cannot_be_removed_to_bypass_review(self):
        with tempfile.TemporaryDirectory() as tmp:
            parent, out, review = self.fixture(Path(tmp))
            derive(parent, out, review)
            job = read(out / "job.json")
            del job["spokenReview"]
            job["blocks"][0]["zh"] = "Unreviewed replacement"
            job["units"] = make_units(job["blocks"])
            with self.assertRaises(ValueError):
                validate_frozen(job)

    def test_derivative_cannot_switch_parent_audio_voice_window_or_inputs(self):
        mutations = ["audio", "voice", "start", "duration", "dropped_input", "changed_text", "changed_units", "human_label"]
        for mode in mutations:
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                parent, out, review = self.fixture(root)
                derive(parent, out, review)
                job = read(out / "job.json")
                if mode == "audio":
                    other = root / "other-source.wav"
                    other.write_bytes(b"another source")
                    job["inputs"]["sourceAudio"] = {"path": str(other), "sha256": sha256(other)}
                elif mode == "voice":
                    job["voice"]["checkpointSha256"] = "other-checkpoint"
                elif mode == "start":
                    job["sourceStartSeconds"] = 200
                elif mode == "duration":
                    job["sourceDurationSeconds"] = 20
                elif mode == "dropped_input":
                    del job["inputs"]["sourceAudio"]
                elif mode == "changed_text":
                    job["blocks"][0]["zh"] = "Unreviewed words"
                elif mode == "changed_units":
                    job["units"][0]["text"] = "Unreviewed words"
                else:
                    job["spokenReview"]["humanApproval"] = True
                with self.assertRaises(ValueError):
                    validate_frozen(job)

    def test_previous_review_evidence_remains_frozen_after_another_revision(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            parent, first, review = self.fixture(root)
            derive(parent, first, review)
            second_review = root / "second-review.json"
            prior = read(first / "job.json")
            newer = read(review)
            newer.update(parentJobSha256=sha256(first / "job.json"), blocks=[])
            write_json(second_review, newer)
            job = {**prior, "inputs": {**prior["inputs"], "spokenScriptReview": {"path": str(second_review), "sha256": sha256(second_review)}},
                "revisionOf": {"path": str(first), "jobSha256": sha256(first / "job.json")}}
            validate_frozen(job)
            data = read(review)
            data["reviewedBy"] = "changed first reviewer"
            write_json(review, data)
            with self.assertRaises(ValueError):
                validate_frozen(job)

    def test_reused_word_evidence_changes_invalidate_anchor_consumption(self):
        with tempfile.TemporaryDirectory() as tmp:
            parent, out, review = self.fixture(Path(tmp))
            acoustic_words(parent)
            derive(parent, out, review)
            job = read(out / "job.json")
            load_anchors(out, job, sha256(out / "job.json"))
            write_json(parent / "source-alignment/words.json", [{"text": "replaced evidence", "start": 0, "end": 1}])
            with self.assertRaises(ValueError):
                load_anchors(out, job, sha256(out / "job.json"))

    def test_reused_word_contract_requires_both_fields_and_matching_anchors(self):
        changes = [lambda d: d.pop("wordEvidence"), lambda d: d.pop("englishBlocksSha256"),
            lambda d: d.update(englishBlocksSha256="different English"),
            lambda d: d["wordEvidence"].update(path="/missing/acoustic-words.json"),
            lambda d: d["blocks"][0].update(start=.1), lambda d: d.update(issues=[{"reason": "invented"}])]
        for i, change in enumerate(changes):
            with self.subTest(case=i), tempfile.TemporaryDirectory() as tmp:
                parent, out, review = self.fixture(Path(tmp))
                acoustic_words(parent)
                derive(parent, out, review)
                modify(out, "source-alignment/report.json", change)
                with self.assertRaises(ValueError):
                    load_anchors(out, read(out / "job.json"), sha256(out / "job.json"))

    def test_legacy_jobs_without_spoken_extension_still_validate(self):
        with tempfile.TemporaryDirectory() as tmp:
            parent = candidate_fixture(Path(tmp))
            job = read(parent / "job.json")
            before = snapshot(parent)
            validate_job_review(job)
            validate_frozen(job)
            self.assertEqual(snapshot(parent), before)


class ModelAnchorReviewTests(unittest.TestCase):
    def fixture(self, work):
        candidate_fixture(work)
        modify(work, "source-alignment/report.json", lambda d: d["blocks"][0].update(issues=["weak_boundary_anchor"]))
        job = read(work / "job.json")
        path = work / "source-alignment/anchor-model-review.json"
        write_json(path, {"schemaVersion": "sermon-anchor-model-review-v1", "reviewType": "model", "model": "gpt-6-astra",
            "humanApproval": False, "status": "approved_for_candidate_alignment", "reviewedBy": "fixture model reviewer", "reviewedAt": "2026-09-06T00:00:00Z",
            "jobSha256": sha256(work / "job.json"), "sourceAudioSha256": job["inputs"]["sourceAudio"]["sha256"],
            "alignmentSha256": sha256(work / "source-alignment/report.json"), "unresolvedBoundaryIssues": [],
            "evidence": [{"path": str(work / "source.wav"), "sha256": sha256(work / "source.wav")}],
            "blocks": [{"blockId": 0, "start": 0, "end": 4, "status": "model_supported", "reason": "Fixture acoustic boundary review"}]})
        anchors, approval_hash = load_anchors(work, job, sha256(work / "job.json"))
        rows, failures = budgets(job["blocks"], anchors, read(work / "render/report.json")["cues"], job["sourceDurationSeconds"])
        modify(work, "synchronization/report.json", lambda d: d.update(alignmentSha256=sha256(work / "source-alignment/report.json"),
            anchorReviewSha256=approval_hash, anchorReviewType="model", blocks=rows, failures=failures))
        return job, path

    def test_model_anchors_clear_candidate_issues_without_granting_human_approval(self):
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp)
            job, path = self.fixture(work)
            before = snapshot(work)
            anchors, digest = load_anchors(work, job, sha256(work / "job.json"))
            self.assertEqual(digest, sha256(path))
            self.assertEqual(anchors[0]["issues"], [])
            self.assertEqual(anchor_review_type(work), "model")
            self.assertFalse(read(path)["humanApproval"])
            self.assertFalse((work / "source-alignment/anchor-review.json").exists())
            with self.assertRaisesRegex(ValueError, "Human audio review"):
                validate_review(work)
            self.assertEqual(snapshot(work), before)

    def test_model_anchor_identity_status_and_evidence_are_required(self):
        changes = [{"schemaVersion": "other-schema"}, {"reviewType": "human"}, {"model": "other-model"}, {"humanApproval": True},
            {"status": "pending"}, {"reviewedBy": None}, {"reviewedAt": None}, {"jobSha256": "other-job"},
            {"sourceAudioSha256": "other-source"}, {"alignmentSha256": "other-alignment"}, {"unresolvedBoundaryIssues": ["uncertain"]}, {"evidence": []}]
        for change in changes:
            with self.subTest(change=change), tempfile.TemporaryDirectory() as tmp:
                work = Path(tmp)
                job, path = self.fixture(work)
                data = read(path)
                data.update(change)
                write_json(path, data)
                with self.assertRaises(ValueError):
                    load_anchors(work, job, sha256(work / "job.json"))

    def test_each_uncertain_boundary_needs_a_distinct_supported_decision(self):
        changes = [lambda d: d.update(blocks=[]), lambda d: d["blocks"][0].update(reason=""),
            lambda d: d["blocks"][0].update(status="pending"), lambda d: d["blocks"][0].update(blockId=999),
            lambda d: d["blocks"].append(copy.deepcopy(d["blocks"][0])),
            lambda d: d["blocks"][0].update(end=99), lambda d: d["evidence"].append(copy.deepcopy(d["evidence"][0]))]
        for i, change in enumerate(changes):
            with self.subTest(case=i), tempfile.TemporaryDirectory() as tmp:
                work = Path(tmp)
                job, path = self.fixture(work)
                data = read(path)
                change(data)
                write_json(path, data)
                with self.assertRaises(ValueError):
                    load_anchors(work, job, sha256(work / "job.json"))

    def test_changed_acoustic_evidence_invalidates_model_anchor_review(self):
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp)
            job, _ = self.fixture(work)
            (work / "source.wav").write_bytes(b"changed acoustic review evidence")
            with self.assertRaisesRegex(ValueError, "Model anchor evidence changed"):
                load_anchors(work, job, sha256(work / "job.json"))

    def test_removed_changed_or_revoked_model_review_invalidates_timing_cache(self):
        for mode in ["removed", "changed", "revoked"]:
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as tmp:
                work = Path(tmp)
                job, path = self.fixture(work)
                if mode == "removed":
                    path.unlink()
                else:
                    data = read(path)
                    data.update({"reviewedAt": "2026-09-07T00:00:00Z"} if mode == "changed" else {"status": "revoked"})
                    write_json(path, data)
                with self.assertRaises(ValueError):
                    validate_timing(work, job, read(work / "render/report.json"))

    def test_human_and_model_reviews_cannot_be_merged_or_relabelled(self):
        for mode in ["both", "relabeled"]:
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as tmp:
                work = Path(tmp)
                job, path = self.fixture(work)
                data = read(path)
                data["humanApproval"] = True
                write_json(work / "source-alignment/anchor-review.json", data)
                if mode == "relabeled":
                    path.unlink()
                with self.assertRaises(ValueError):
                    load_anchors(work, job, sha256(work / "job.json"))


if __name__ == "__main__":
    unittest.main()
