import copy
import hashlib
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from scripts import machine_quality_release_basis as basis
from scripts import machine_quality_waiver as waiver
from scripts import prepare_target_language_speech_job as speech
from scripts import sermon_sentence_interpretation as interpretation
from scripts import sermon_unified_reviews as reviews
from scripts import stage_formal_multilingual_dev as stage
# Reuse the speech-job fixture without collecting its tests a second time here.
from tests import test_prepare_target_language_speech_job as speech_fixture

write_json = speech_fixture.write_json

IMPLEMENTATION = waiver.implementation_sha256()
SEMANTIC_SHA = "9" * 64
PRIMARY_ASR = {"model": "qwen3-asr-0.6b", "modelRevision": "r1"}
SECONDARY_ASR = {"model": "gpt-transcribe", "modelRevision": None}


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def calibration(locale="ko", **overrides):
    value = {"schemaVersion": waiver.CALIBRATION_SCHEMA, "locale": locale,
             "implementationSha256": IMPLEMENTATION, "semanticChecksIncluded": True,
             "overallDetectionRate": 1.0, "cleanFalsePositiveRate": 0.0, "audioIncluded": True,
             "semanticIdentitySha256": SEMANTIC_SHA,
             "asrIdentity": {"primary": PRIMARY_ASR, "secondary": SECONDARY_ASR},
             "kinds": {f"{prefix}.{kind}": {"trials": 10, "detected": 10, "rate": 1.0}
                       for prefix, kinds in (("text", waiver.TEXT_KINDS), ("audio", waiver.AUDIO_KINDS))
                       for kind in kinds}}
    value.update(overrides)
    return value


def text_qc(candidate):
    return {"schemaVersion": "sermon-target-text-auto-qc-v1", "locale": candidate["targetLocale"],
            "status": "pass", "humanApproval": False, "mutatesText": False,
            "repairGroupIds": [], "sourceTextFallbackGroupIds": [], "semanticIdentitySha256": SEMANTIC_SHA,
            "results": [{"groupId": group["translationGroupId"], "status": "pass", "problems": [],
                         "backTranslation": {"status": "pass", "issues": []}, "failedAttempts": 0,
                         "nextAction": "keep", "targetTextSha256": sha(group["targetText"])}
                        for group in candidate["groups"]]}


class TextWaiverTests(unittest.TestCase):
    group = staticmethod(speech_fixture.TargetLanguageSpeechJobTests.group)
    validate_schema = speech_fixture.TargetLanguageSpeechJobTests.validate_schema

    def setUp(self):
        speech_fixture.TargetLanguageSpeechJobTests.setUp(self)
        # The weekly machine path: model-reviewed, no human decision yet.
        self.candidate["status"] = basis.MACHINE_PENDING_CANDIDATE
        self.candidate["humanReview"] = {"translation": "pending", "reviewer": None,
                                         "reviewedAt": None, "reviewedGroupIds": []}
        write_json(self.candidate_path, self.candidate)
        self.waiver = basis.build_text_waiver(self.source_package, self.anchor, self.candidate,
                                              text_qc(self.candidate), calibration(),
                                              created_at="2026-10-07T01:00:00+00:00")
        self.waiver_path = self.root / "text-waiver.json"
        write_json(self.waiver_path, self.waiver)

    def prepare(self, name="speech-job", receipt_path=None):
        return speech.prepare_job(self.source_package_path, self.anchor_path, self.candidate_path,
                                  self.policy_path, receipt_path or self.waiver_path, self.adapter_path,
                                  self.registry_path, self.root / name)

    def test_waiver_is_disclosed_and_never_human(self):
        self.assertFalse(self.waiver["humanApproval"])
        self.assertEqual(self.waiver["reviewKind"], "machine_quality_waiver")
        self.assertEqual(self.waiver["disclosure"]["text"], waiver.DISCLOSURE["ko"])
        self.assertEqual(self.waiver["candidateJsonSha256"], interpretation.json_sha256(self.candidate))
        basis.validate_text_waiver(self.waiver, candidate=self.candidate)

    def test_waiver_admits_candidate_to_layer3_as_speech_job_v3(self):
        job = self.prepare()
        self.assertEqual(job["schemaVersion"], speech.MACHINE_SPEECH_JOB_SCHEMA)
        self.assertEqual(job["renderContract"]["textPolicy"], speech.MACHINE_TEXT_POLICY)
        self.assertEqual(job["renderContract"]["humanListeningReview"], "pending")
        self.assertNotIn("humanReviewReceipt", job["inputs"])
        bound = job["inputs"]["textReleaseBasis"]
        self.assertEqual((bound["kind"], bound["jsonSha256"]),
                         ("machine_quality_waiver", interpretation.json_sha256(self.waiver)))
        self.assertEqual(speech.text_basis_input_key(job), "textReleaseBasis")
        self.assertEqual(self.validate_schema("sermon-target-language-speech-job-v3.schema.json", job), [])
        # The candidate itself is untouched: no human approval appears anywhere.
        self.assertEqual(json.loads(self.candidate_path.read_text())["humanReview"]["translation"], "pending")

    def test_human_receipt_still_writes_unchanged_v2_job(self):
        self.candidate["status"] = "human_translation_approved"
        self.candidate["humanReview"] = {"translation": "approved", "reviewer": "Korean reviewer",
                                         "reviewedAt": "2026-09-20T12:00:00Z", "reviewedGroupIds": ["g1", "g2"]}
        write_json(self.candidate_path, self.candidate)
        self.human_review_receipt["candidateJsonSha256"] = interpretation.json_sha256(self.candidate)
        write_json(self.human_review_receipt_path, self.human_review_receipt)
        job = self.prepare("human-job", self.human_review_receipt_path)
        self.assertEqual(job["schemaVersion"], speech.SPEECH_JOB_SCHEMA)
        self.assertEqual(job["renderContract"]["textPolicy"], speech.HUMAN_TEXT_POLICY)
        self.assertEqual(set(job["inputs"]["humanReviewReceipt"]), {"path", "sha256", "jsonSha256"})

    def test_waiver_cannot_release_changed_or_human_decided_candidate(self):
        changed = copy.deepcopy(self.candidate)
        changed["groups"][0]["targetText"] = changed["groups"][0]["targetUtterances"][0] = "다른 문장입니다."
        changed["groups"][0]["coverage"][0]["targetText"] = "다른 문장입니다."
        with self.assertRaisesRegex(ValueError, "does not bind"):
            basis.validate_text_waiver(self.waiver, candidate=changed)
        rejected = copy.deepcopy(self.candidate)
        rejected["humanReview"]["translation"] = "rejected"
        with self.assertRaisesRegex(ValueError, "still pending"):
            basis.validate_text_waiver(self.waiver, candidate=rejected)
        forged = dict(self.waiver, humanApproval=True)
        with self.assertRaisesRegex(ValueError, "Invalid"):
            basis.validate_text_waiver(forged, candidate=self.candidate)
        weak = copy.deepcopy(self.waiver)
        weak["calibration"]["overallDetectionRate"] = 0.9
        with self.assertRaisesRegex(ValueError, "minimums"):
            basis.validate_text_waiver(weak, candidate=self.candidate)

    def test_waiver_refuses_failing_or_unrelated_qc(self):
        failing = text_qc(self.candidate)
        failing["status"] = "requires_repair"
        failing["results"][1].update(status="fail", nextAction="revise_translation")
        unscreened = text_qc(self.candidate)
        unscreened["results"][0]["backTranslation"] = None
        other_text = text_qc(self.candidate)
        other_text["results"][0]["targetTextSha256"] = sha("unrelated")
        for qc, message in ((failing, "must pass"), (unscreened, "must pass"), (other_text, "different text")):
            with self.assertRaisesRegex(ValueError, message):
                basis.build_text_waiver(self.source_package, self.anchor, self.candidate, qc, calibration())
        for cal, message in ((calibration(implementationSha256="0" * 64), "changed since calibration"),
                             (calibration(semanticChecksIncluded=False), "back-translation"),
                             (calibration(cleanFalsePositiveRate=0.2), "false-positive"),
                             (calibration(semanticIdentitySha256="0" * 64), "runtime differs")):
            with self.assertRaisesRegex(ValueError, message):
                basis.build_text_waiver(self.source_package, self.anchor, self.candidate,
                                        text_qc(self.candidate), cal)

    def test_layer3_rejects_pending_candidate_without_any_basis(self):
        write_json(self.human_review_receipt_path, self.human_review_receipt)
        with self.assertRaisesRegex(ValueError, "Human translation approval is required"):
            self.prepare("unreleased", self.human_review_receipt_path)
        self.assertFalse((self.root / "unreleased").exists())

    def test_unified_translation_review_reports_machine_kind(self):
        # The fixture source package is minimal; only the release basis is under test.
        with patch.object(reviews, "schema"):
            result = reviews.validate_review("translation", self.waiver_path, inputs={
                "source": self.source_package_path, "anchor": self.anchor_path,
                "candidate": self.candidate_path})
        self.assertEqual((result["status"], result["reviewKind"]), ("validated", "machine_quality_waiver"))


def audio_fixture(flagged=False):
    texts = ["두려워하지 마십시오.", "내가 당신과 함께 있습니다."]
    units = [{"textGroupId": f"g{index}", "targetTextSha256": sha(text),
              "audio": {"path": f"audio/unit-{index}.wav", "sha256": sha(f"wav-{index}")},
              "durationSeconds": 1.5} for index, text in enumerate(texts, 1)]
    package = {"schemaVersion": "sermon-target-language-audio-package-v1", "targetLocale": "ko",
               "englishSourcePackageJsonSha256": "1" * 64, "targetLanguageCandidateJsonSha256": "2" * 64,
               "targetLanguageSpeechJobJsonSha256": "3" * 64,
               "status": "candidate" if flagged else "machine_screened", "units": units,
               "track": {"path": "track.mp3", "sha256": "4" * 64},
               "captions": {"path": "captions.json", "sha256": "5" * 64},
               "machineScreening": {"status": "requires_review" if flagged else "pass",
                                    "model": "qwen3-asr-0.6b", "coverage": 1.0},
               "humanReview": {"status": "pending", "humanApproval": False, "reviewedBy": None,
                               "reviewedAt": None, "fullPlayback": "pending"},
               "issues": []}
    similarities = [0.97, 0.71 if flagged else 0.95]
    screening = {"schemaVersion": "sermon-target-language-audio-screening-v1", "targetLocale": "ko",
                 "targetLanguageSpeechJobJsonSha256": "3" * 64, "trackSha256": "4" * 64,
                 "status": package["machineScreening"]["status"], "model": "qwen3-asr-0.6b",
                 "modelRevision": "r1", "minSimilarity": 0.88, "coverage": 1,
                 "reviewedGroupIds": ["g1", "g2"], "unitAudioSha256s": [u["audio"]["sha256"] for u in units],
                 "results": [{"textGroupId": unit["textGroupId"], "targetTextSha256": unit["targetTextSha256"],
                              "audioSha256": unit["audio"]["sha256"], "recognized": "", "similarity": value,
                              "differences": [], "status": "requires_review" if value < 0.88 else "pass"}
                             for unit, value in zip(units, similarities)],
                 "humanListeningStatus": "pending"}
    qc = {"schemaVersion": "sermon-target-audio-auto-qc-v1", "locale": "ko", "status": "pass",
          "humanApproval": False, "mutatesAudio": False, "subtitleOnlyGroupIds": [], "repairGroupIds": [],
          "results": [{"groupId": unit["textGroupId"], "status": "pass", "issues": [], "asrDecision": "pass",
                       "asrPrimary": value, "asrSecondary": 0.96 if value < 0.88 else None,
                       "asrPrimaryModel": PRIMARY_ASR, "asrSecondaryModel": SECONDARY_ASR if value < 0.88 else None,
                       "audioSha256": unit["audio"]["sha256"], "failedAttempts": 0, "nextAction": "keep",
                       "metrics": {}} for unit, value in zip(units, similarities)]}
    text = {"schemaVersion": basis.TEXT_WAIVER_SCHEMA, "reviewKind": "machine_quality_waiver",
            "humanApproval": False, "decision": "machine_quality_waived", "targetLocale": "ko",
            "englishSourcePackageJsonSha256": "1" * 64, "anchorManifestJsonSha256": "6" * 64,
            "translationPolicySha256": "7" * 64, "candidateJsonSha256": "2" * 64,
            "reviewedGroupIds": ["g1", "g2"],
            "groupResults": [{"translationGroupId": unit["textGroupId"], "status": "pass",
                              "targetTextSha256": unit["targetTextSha256"], "failedAttempts": 0} for unit in units],
            "textQcJsonSha256": "8" * 64,
            "calibration": basis.calibration_summary(calibration(), "ko", IMPLEMENTATION),
            "implementationSha256": IMPLEMENTATION, "rules": basis.RULES, "disclosure": basis.disclosure("ko"),
            "createdAt": "2026-10-07T01:00:00+00:00", "postPublicationSpotCheck": "owner_spot_check_after_release"}
    return package, screening, qc, text


class AudioWaiverTests(unittest.TestCase):
    def build(self, package, screening, qc, text, **kwargs):
        return basis.build_audio_waiver(package, screening, qc, text, calibration(),
                                        created_at="2026-10-07T02:00:00+00:00", **kwargs)

    def test_clean_package_waives_listening_without_human_approval(self):
        package, screening, qc, text = audio_fixture()
        receipt = self.build(package, screening, qc, text)
        self.assertFalse(receipt["humanApproval"])
        self.assertEqual([row["asr"] for row in receipt["unitResults"]], ["primary_pass", "primary_pass"])
        self.assertIsNone(receipt["secondaryAsrModel"])
        stage.validate_audio_screening_review(package, receipt, screening)
        self.assertEqual(package["humanReview"]["humanApproval"], False)

    def test_audio_waiver_needs_audio_calibration(self):
        package, screening, qc, text = audio_fixture()
        text_only = calibration(audioIncluded=False)
        text_only["kinds"] = {kind: row for kind, row in text_only["kinds"].items() if kind.startswith("text.")}
        with self.assertRaisesRegex(ValueError, "audio checks"):
            basis.build_audio_waiver(package, screening, qc, text, text_only,
                                     created_at="2026-10-07T02:00:00+00:00")
        # The same calibration is enough for the text waiver.
        self.assertTrue(basis.calibration_summary(text_only, "ko", IMPLEMENTATION)["semanticChecksIncluded"])

    def test_flagged_unit_needs_secondary_asr(self):
        package, screening, qc, text = audio_fixture(flagged=True)
        with self.assertRaisesRegex(ValueError, "secondary ASR"):
            self.build(package, screening, qc, text)
        receipt = self.build(package, screening, qc, text, secondary_asr_model="gpt-transcribe")
        self.assertEqual(receipt["unitResults"][1]["asr"], "secondary_pass")
        basis.validate_audio_waiver(package, receipt, screening)
        tampered = copy.deepcopy(receipt)
        tampered["unitResults"][1]["secondarySimilarity"] = 0.5
        with self.assertRaisesRegex(ValueError, "secondary ASR"):
            basis.validate_audio_waiver(package, tampered, screening)

    def test_waiver_refuses_subtitle_only_units_and_reviewed_packages(self):
        package, screening, qc, text = audio_fixture()
        partial = copy.deepcopy(qc)
        partial["subtitleOnlyGroupIds"] = ["g2"]
        with self.assertRaisesRegex(ValueError, "subtitle-only"):
            self.build(package, screening, partial, text)
        reviewed = copy.deepcopy(package)
        reviewed["status"] = "human_reviewed"
        with self.assertRaisesRegex(ValueError, "no human decision"):
            self.build(reviewed, screening, qc, text)
        other_script = dict(text, candidateJsonSha256="9" * 64)
        with self.assertRaisesRegex(ValueError, "spoken script"):
            self.build(package, screening, qc, other_script)

    def test_waiver_is_bound_to_exact_package_and_audio(self):
        package, screening, qc, text = audio_fixture()
        receipt = self.build(package, screening, qc, text)
        changed = copy.deepcopy(package)
        changed["units"][0]["audio"]["sha256"] = "a" * 64
        with self.assertRaises(ValueError):
            basis.validate_audio_waiver(changed, receipt, screening)
        swapped = copy.deepcopy(qc)
        swapped["results"][0]["audioSha256"] = "b" * 64
        with self.assertRaisesRegex(ValueError, "different audio"):
            self.build(package, screening, swapped, text)
        with self.assertRaisesRegex(ValueError, "screening"):
            basis.validate_audio_waiver(package, receipt, None)

    def test_waiver_needs_the_calibrated_and_screened_asr_models(self):
        package, screening, qc, text = audio_fixture(flagged=True)
        other_secondary = copy.deepcopy(qc)
        other_secondary["results"][1]["asrSecondaryModel"] = {"model": "tiny-asr", "modelRevision": None}
        with self.assertRaisesRegex(ValueError, "secondary ASR model differs"):
            self.build(package, screening, other_secondary, text, secondary_asr_model="gpt-transcribe")
        unscreened_model = copy.deepcopy(qc)
        unscreened_model["results"][0]["asrPrimaryModel"] = {"model": "qwen3-asr-0.6b", "modelRevision": "r0"}
        with self.assertRaisesRegex(ValueError, "primary ASR model differs"):
            self.build(package, screening, unscreened_model, text, secondary_asr_model="gpt-transcribe")

    def test_unified_audio_review_reports_machine_kind(self):
        import tempfile
        package, screening, qc, text = audio_fixture()
        receipt = self.build(package, screening, qc, text)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            package["packageId"] = "target-audio-ko-test"
            package["ratePolicy"] = "natural_no_time_stretch"
            package["voice"] = {"provider": "local", "model": "tts", "checkpointSha256": "e" * 64,
                                "targetLocaleCapability": "reviewed", "authorizationStatus": "authorized"}
            package["schedule"] = {"path": "schedule.json", "sha256": "c" * 64, "jsonSha256": "c" * 64}
            package["downstreamInvalidationKey"] = "d" * 64
            receipt = self.build(package, screening, qc, text)
            for name, value in (("package", package), ("screening", screening), ("receipt", receipt)):
                write_json(root / f"{name}.json", value)
            try:
                result = reviews.validate_review("audio", root / "receipt.json", inputs={
                    "package": root / "package.json", "screening": root / "screening.json"})
            except Exception as error:  # Surface schema drift in the synthetic package clearly.
                self.fail(f"audio waiver review failed: {error}")
        self.assertEqual(result["reviewKind"], "machine_quality_waiver")


class UnifiedScopeTests(unittest.TestCase):
    def state(self, translation_review, listen_review="waived", study_review="approved"):
        steps = [("media", "media_verify", "media.verify", None, None),
                 ("english", "english_source", "canonical.inspect", None, None),
                 ("l2", "layer2_group", "layer2.group", "ko", None),
                 ("text-review", "translation_review", "review.gate", "ko", "translation"),
                 ("l3", "layer3_screen", "layer3.screen", "ko", None),
                 ("listen", "listen_review", "review.gate", "ko", "audio"),
                 ("outline", "study_product", "review.gate", "ko", "outline"),
                 ("reflection", "study_product", "review.gate", "ko", "reflection")]
        manifest = {"transport": "production", "locales": ["ko"], "steps": [
            {"id": ident, "stageId": stage, "adapter": adapter, "locale": locale, "reviewKind": kind}
            for ident, stage, adapter, locale, kind in steps]}
        reviews_by_step = {"text-review": translation_review, "listen": listen_review,
                           "outline": study_review, "reflection": study_review}
        return {"manifest": manifest, "steps": {
            ident: {"process": "succeeded", "artifact": "verified", "review": reviews_by_step.get(ident, "not_required")}
            for ident, *_ in steps}}

    def satisfied(self, scope, **reviews_):
        from scripts.sermon_unified import runtime
        state = self.state(**reviews_)
        state["manifest"]["activeScope"] = scope
        return runtime.scope_satisfied(state)

    def test_machine_waiver_satisfies_translation_and_listening_gates(self):
        self.assertTrue(self.satisfied("translation_approved", translation_review="waived"))
        self.assertTrue(self.satisfied("listen_approved", translation_review="waived"))
        self.assertFalse(self.satisfied("translation_approved", translation_review="human_pending"))
        self.assertFalse(self.satisfied("listen_approved", translation_review="waived", listen_review="machine_pending"))

    def test_waiver_does_not_cover_study_approvals(self):
        self.assertTrue(self.satisfied("study_approved", translation_review="waived"))
        self.assertFalse(self.satisfied("study_approved", translation_review="waived", study_review="waived"))


if __name__ == "__main__":
    unittest.main()
