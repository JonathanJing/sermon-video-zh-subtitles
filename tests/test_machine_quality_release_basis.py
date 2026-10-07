import copy
import hashlib
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from scripts import machine_quality_release_basis as basis
from scripts import machine_quality_waiver as waiver
from scripts import target_text_auto_qc as text_screen
from scripts.target_audio_auto_qc import THRESHOLDS, TRACK_ENVELOPE
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
# The primary runtime is the one the bound screening receipt records.
SCREENING_ASR_SETTINGS = basis.json_sha256({"source": "sermon-target-language-audio-screening-v1",
                                            "model": "qwen3-asr-0.6b", "modelRevision": "r1",
                                            "minSimilarity": 0.88, "transcriptionBatchSize": 1})
SECONDARY_ASR_SETTINGS = basis.json_sha256({"backend": "openai", "language": "ko", "scoring": "token-ratio-v1"})


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def calibration(locale="ko", **overrides):
    value = {"schemaVersion": waiver.CALIBRATION_SCHEMA, "locale": locale,
             "implementationSha256": IMPLEMENTATION, "semanticChecksIncluded": True,
             "trials": 10 * (len(waiver.TEXT_KINDS) + len(waiver.AUDIO_KINDS)),
             "detected": 10 * (len(waiver.TEXT_KINDS) + len(waiver.AUDIO_KINDS)),
             "cleanChecked": 10, "cleanFalsePositives": 0,
             "overallDetectionRate": 1.0, "cleanFalsePositiveRate": 0.0, "audioIncluded": True,
             "semanticIdentitySha256": SEMANTIC_SHA,
             "asrIdentity": {"primary": PRIMARY_ASR, "secondary": SECONDARY_ASR},
             "asrSettingsSha256": {"primary": SCREENING_ASR_SETTINGS, "secondary": SECONDARY_ASR_SETTINGS},
             "kinds": {f"{prefix}.{kind}": {"trials": 10, "detected": 10, "rate": 1.0}
                       for prefix, kinds in (("text", waiver.TEXT_KINDS), ("audio", waiver.AUDIO_KINDS))
                       for kind in kinds}}
    value.update(overrides)
    return value


def text_qc(candidate, anchor):
    english_units = {unit["sourceUnitId"]: unit["english"] for unit in anchor["sourceUnits"]}
    return {"schemaVersion": "sermon-target-text-auto-qc-v1", "locale": candidate["targetLocale"],
            "status": "pass", "humanApproval": False, "mutatesText": False,
            "repairGroupIds": [], "sourceTextFallbackGroupIds": [], "semanticIdentitySha256": SEMANTIC_SHA,
            "policyJsonSha256": candidate["translationPolicySha256"],
            "implementationSha256": IMPLEMENTATION,
            "results": [{"groupId": group["translationGroupId"], "status": "pass", "problems": [],
                         "backTranslation": {"status": "pass", "issues": []}, "failedAttempts": 0,
                         "nextAction": "keep", "targetTextSha256": sha(group["targetText"]),
                         "englishSha256": sha(" ".join(english_units[unit_id] for unit_id in group["sourceUnitIds"])),
                         "sourceUnitIdsSha256": basis.json_sha256(group["sourceUnitIds"])}
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
                                              text_qc(self.candidate, self.anchor), calibration(),
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
        failing = text_qc(self.candidate, self.anchor)
        failing["status"] = "requires_repair"
        failing["results"][1].update(status="fail", nextAction="revise_translation")
        unscreened = text_qc(self.candidate, self.anchor)
        unscreened["results"][0]["backTranslation"] = None
        other_text = text_qc(self.candidate, self.anchor)
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
                                        text_qc(self.candidate, self.anchor), cal)
        # A cached text QC from older QC code cannot ride on a newer calibration.
        stale = text_qc(self.candidate, self.anchor)
        stale["implementationSha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "implementation other than the calibrated one"):
            basis.build_text_waiver(self.source_package, self.anchor, self.candidate, stale, calibration())

    def test_text_qc_binds_actual_frozen_english_and_source_units(self):
        english = {unit["sourceUnitId"]: unit["english"] for unit in self.anchor["sourceUnits"]}
        groups = [{"groupId": group["translationGroupId"], "targetText": group["targetText"],
                   "sourceUnitIds": group["sourceUnitIds"],
                   "english": " ".join(english[unit_id] for unit_id in group["sourceUnitIds"])}
                  for group in self.candidate["groups"]]
        identity = {"backend": "fixture", "model": "judge", "modelRevision": "r1",
                    "cacheNamespace": "fixture", "settings": {"temperature": 0}}

        def call(role, system, user, schema):
            return {"english": "Do not be afraid."} if role == "back_translator" else {"status": "pass", "issues": []}

        def screen(values):
            return text_screen.screen(values, "ko", policy=self.policy, call=call, identity=identity)

        clean = screen(groups)
        self.assertEqual(clean["status"], "pass")
        cal = calibration(semanticIdentitySha256=clean["semanticIdentitySha256"])
        basis.build_text_waiver(self.source_package, self.anchor, self.candidate, clean, cal)
        stale = copy.deepcopy(groups)
        stale[0]["english"] = "You may be afraid."
        wrong_units = copy.deepcopy(groups)
        wrong_units[0]["sourceUnitIds"] = groups[1]["sourceUnitIds"]
        for qc in (screen(stale), screen(wrong_units)):
            self.assertEqual(qc["status"], "pass")
            with self.assertRaisesRegex(ValueError, "different frozen English/source units"):
                basis.build_text_waiver(self.source_package, self.anchor, self.candidate, qc, cal)
        # QC without the candidate's policy skipped the terminology checks.
        for policy in (None, {**self.policy, "terminology": {"properNames": [], "seriesNames": []}}):
            unbound = text_screen.screen(groups, "ko", policy=policy, call=call, identity=identity)
            self.assertEqual(unbound["status"], "pass")
            with self.assertRaisesRegex(ValueError, "candidate's translation policy"):
                basis.build_text_waiver(self.source_package, self.anchor, self.candidate, unbound, cal)
        for key in ("englishSha256", "sourceUnitIdsSha256"):
            missing = copy.deepcopy(clean)
            del missing["results"][0][key]
            with self.assertRaisesRegex(ValueError, "different frozen English/source units"):
                basis.build_text_waiver(self.source_package, self.anchor, self.candidate, missing, cal)

    def test_waiver_requires_every_frozen_source_unit(self):
        # Dropping the last group leaves no row to screen, so the waiver checks coverage itself.
        shortened = copy.deepcopy(self.candidate)
        shortened["groups"].pop()
        shortened["modelReview"]["reviewedGroupIds"].pop()
        with self.assertRaisesRegex(ValueError, "cover every frozen source unit"):
            basis.build_text_waiver(self.source_package, self.anchor, shortened,
                                    text_qc(shortened, self.anchor), calibration())

    def test_condensed_spoken_groups_need_their_binding_and_spoken_calibration(self):
        group = self.candidate["groups"][0]
        qc = text_qc(self.candidate, self.anchor)
        qc["results"][0]["mode"] = "spoken_condensed"
        qc["condensedGroupIds"] = [group["translationGroupId"]]
        binding = {"schemaVersion": basis.CONDENSATION_BINDING_SCHEMA, "status": "pass", "issues": [],
                   "humanApproval": False, "targetLocale": "ko",
                   "spokenCandidateJsonSha256": interpretation.json_sha256(self.candidate),
                   "groups": [{"translationGroupId": group["translationGroupId"],
                               "finalSpokenTextSha256": sha(group["targetText"])}]}
        kinds = {**calibration()["kinds"], **{f"spoken.{kind}": {"trials": 4, "detected": 4, "rate": 1.0}
                                              for kind in waiver.SPOKEN_KINDS}}
        base = calibration()
        added = 4 * len(waiver.SPOKEN_KINDS)
        spoken = calibration(spokenIncluded=True, kinds=kinds, trials=base["trials"] + added,
                             detected=base["detected"] + added)

        def build(qc=qc, cal=spoken, binding=binding):
            return basis.build_text_waiver(self.source_package, self.anchor, self.candidate, qc, cal,
                                           condensation_binding=binding, created_at="2026-10-07T01:00:00+00:00")
        receipt = build()
        self.assertEqual((receipt["condensedGroupIds"], receipt["condensationBindingJsonSha256"]),
                         ([group["translationGroupId"]], basis.json_sha256(binding)))
        self.assertEqual((self.waiver["condensedGroupIds"], self.waiver["condensationBindingJsonSha256"]), ([], None))
        basis.validate_text_waiver(receipt, candidate=self.candidate)
        # The condensed script may be dubbed, but Layer 4 never takes it as the full text.
        write_json(self.waiver_path, receipt)
        self.prepare("condensed-job", self.waiver_path)
        from scripts import build_full_video_app_release as builder
        with self.assertRaisesRegex(ValueError, "condensed for dubbing cannot be the full text"):
            builder.admitted_text(self.candidate_path, self.waiver_path,
                                  basis.json_sha256(self.source_package), "ko")
        _, _, admitted = builder.admitted_text(self.candidate_path, self.waiver_path,
                                               basis.json_sha256(self.source_package), "ko", spoken=True)
        self.assertEqual(admitted["kind"], "machine_quality_waiver")
        other = copy.deepcopy(self.candidate)
        other["groups"][1]["targetText"] = "다른 문장입니다."
        unlisted = copy.deepcopy(qc)
        unlisted["condensedGroupIds"] = []
        cases = [
            (dict(binding=None), "need their condensation binding"),
            (dict(cal=calibration()), "did not include condensed spoken groups"),
            (dict(binding=dict(binding, status="fail")), "did not pass"),
            (dict(binding=dict(binding, spokenCandidateJsonSha256=interpretation.json_sha256(other))),
             "another spoken candidate"),
            (dict(binding=dict(binding, groups=[])), "differ from the binding"),
            (dict(binding=dict(binding, groups=[dict(binding["groups"][0], finalSpokenTextSha256=sha("x"))])),
             "other spoken text"),
            (dict(qc=unlisted), "condensed-group list differs"),
            (dict(qc=text_qc(self.candidate, self.anchor)), "no group was judged condensed"),
        ]
        for kwargs, message in cases:
            with self.subTest(message=message), self.assertRaisesRegex(ValueError, message):
                build(**kwargs)

    def test_text_waiver_stores_the_rate_of_the_kinds_it_needs(self):
        # Weak audio trials lower the aggregate, but a text waiver never needs them.
        kinds = {**calibration()["kinds"],
                 **{f"audio.{kind}": {"trials": 10, "detected": 0, "rate": 0.0} for kind in waiver.AUDIO_KINDS}}
        base = calibration()
        detected = base["detected"] - 10 * len(waiver.AUDIO_KINDS)
        cal = calibration(kinds=kinds, detected=detected,
                          overallDetectionRate=round(detected / base["trials"], 6))
        self.assertLess(cal["overallDetectionRate"], waiver.CALIBRATION_MINIMUMS["overallDetectionRate"])
        receipt = basis.build_text_waiver(self.source_package, self.anchor, self.candidate,
                                          text_qc(self.candidate, self.anchor), cal,
                                          created_at="2026-10-07T01:00:00+00:00")
        self.assertEqual(receipt["calibration"]["overallDetectionRate"], 1.0)
        basis.validate_text_waiver(receipt, candidate=self.candidate)

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


def audio_sources():
    """The frozen anchor and spoken candidate whose spans audio QC must use (u1: 2 s, u2+u3: 3.5 s)."""
    anchor = {"sourceUnits": [{"sourceUnitId": "u1", "start": 10.0, "end": 12.0},
                              {"sourceUnitId": "u2", "start": 12.5, "end": 14.0},
                              {"sourceUnitId": "u3", "start": 14.0, "end": 16.0}]}
    candidate = {"groups": [{"translationGroupId": "g1", "sourceUnitIds": ["u1"]},
                            {"translationGroupId": "g2", "sourceUnitIds": ["u2", "u3"]}]}
    return anchor, candidate


def audio_fixture(flagged=False):
    anchor, candidate = audio_sources()
    texts = ["두려워하지 마십시오.", "내가 당신과 함께 있습니다."]
    units = [{"textGroupId": f"g{index}", "targetTextSha256": sha(text),
              "audio": {"path": f"audio/unit-{index}.wav", "sha256": sha(f"wav-{index}")},
              "durationSeconds": 1.5} for index, text in enumerate(texts, 1)]
    package = {"schemaVersion": "sermon-target-language-audio-package-v1", "targetLocale": "ko",
               "englishSourcePackageJsonSha256": "1" * 64,
               "targetLanguageCandidateJsonSha256": basis.json_sha256(candidate),
               "targetLanguageSpeechJobJsonSha256": "3" * 64,
               "status": "candidate" if flagged else "machine_screened", "units": units,
               "track": {"path": "track.mp3", "sha256": "4" * 64},
               "captions": {"path": "captions.json", "sha256": "5" * 64},
               "schedule": {"path": "schedule.json", "sha256": "c" * 64, "jsonSha256": "c" * 64},
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
          "implementationSha256": IMPLEMENTATION, "thresholds": dict(THRESHOLDS),
          "humanApproval": False, "mutatesAudio": False, "subtitleOnlyGroupIds": [], "repairGroupIds": [],
          "results": [{"groupId": unit["textGroupId"], "status": "pass", "issues": [], "asrDecision": "pass",
                       "asrPrimary": value, "asrSecondary": 0.96 if value < 0.88 else None,
                       "asrPrimaryModel": PRIMARY_ASR, "asrSecondaryModel": SECONDARY_ASR if value < 0.88 else None,
                       "asrPrimarySettingsSha256": SCREENING_ASR_SETTINGS,
                       "asrSecondarySettingsSha256": SECONDARY_ASR_SETTINGS if value < 0.88 else None,
                       "audioSha256": unit["audio"]["sha256"], "textSha256": unit["targetTextSha256"],
                       "sourceSeconds": span, "failedAttempts": 0, "nextAction": "keep",
                       "metrics": {}} for unit, value, span in zip(units, similarities, (2.0, 3.5))]}
    text = {"schemaVersion": basis.TEXT_WAIVER_SCHEMA, "reviewKind": "machine_quality_waiver",
            "humanApproval": False, "decision": "machine_quality_waived", "targetLocale": "ko",
            "englishSourcePackageJsonSha256": "1" * 64, "anchorManifestJsonSha256": basis.json_sha256(anchor),
            "translationPolicySha256": "7" * 64, "candidateJsonSha256": basis.json_sha256(candidate),
            "reviewedGroupIds": ["g1", "g2"],
            "groupResults": [{"translationGroupId": unit["textGroupId"], "status": "pass",
                              "targetTextSha256": unit["targetTextSha256"], "failedAttempts": 0} for unit in units],
            "textQcJsonSha256": "8" * 64, "condensedGroupIds": [], "condensationBindingJsonSha256": None,
            "calibration": basis.calibration_summary(calibration(), "ko", IMPLEMENTATION),
            "implementationSha256": IMPLEMENTATION, "rules": basis.RULES, "disclosure": basis.disclosure("ko"),
            "createdAt": "2026-10-07T01:00:00+00:00", "postPublicationSpotCheck": "owner_spot_check_after_release"}
    return package, screening, qc, text


def track_check(package, **overrides):
    """A passing assembled-track check bound to ``package`` (see test_machine_quality_waiver for the real check)."""
    value = {"schemaVersion": "sermon-target-audio-track-check-v1", "status": "pass", "issues": [],
             "humanApproval": False, "targetLocale": package["targetLocale"],
             "targetLanguageAudioPackageJsonSha256": basis.json_sha256(package),
             "trackSha256": package["track"]["sha256"], "pcmMasterSha256": "e" * 64,
             "scheduleJsonSha256": package["schedule"]["jsonSha256"],
             "unitAudioSha256s": [unit["audio"]["sha256"] for unit in package["units"]],
             "implementationSha256": IMPLEMENTATION, "settings": dict(TRACK_ENVELOPE)}
    if Path(package["track"]["path"]).suffix.lower() == ".wav":
        value.update(method={"pcm": "sample_exact_scheduled_placement", "compressed": None},
                     envelope=None, waveform=None)
    else:
        value.update(method={"pcm": "sample_exact_scheduled_placement", "compressed": "decoded_waveform"},
                     envelope={"windows": 200, "deviantWindows": 0, "maxDeltaDb": 0.5, "lengthDeltaSeconds": 0.0},
                     waveform={"audibleWindows": 180, "deviantWindows": 0})
    value.update(overrides)
    return value


class AudioWaiverTests(unittest.TestCase):
    def build(self, package, screening, qc, text, **kwargs):
        kwargs.setdefault("track_check", track_check(package))
        anchor, candidate = audio_sources()
        kwargs.setdefault("anchor", anchor)
        kwargs.setdefault("candidate", candidate)
        return basis.build_audio_waiver(package, screening, qc, text, calibration(),
                                        created_at="2026-10-07T02:00:00+00:00", **kwargs)

    def test_waiver_needs_a_passing_track_check_of_this_package(self):
        package, screening, qc, text = audio_fixture()
        receipt = self.build(package, screening, qc, text)
        self.assertEqual(receipt["trackCheckJsonSha256"], basis.json_sha256(track_check(package)))
        other = copy.deepcopy(package)
        other["track"]["sha256"] = "f" * 64
        for check, message in ((None, "track check missing"),
                               (track_check(package, status="fail", issues=["pcm_track_differs_from_scheduled_units"]),
                                "status differs"),
                               (track_check(other), "trackSha256 differs"),
                               (track_check(package, unitAudioSha256s=["a" * 64, "b" * 64]), "unitAudioSha256s"),
                               (track_check(package, implementationSha256="0" * 64), "implementationSha256"),
                               # A permissive comparison cannot authorize a waiver.
                               (track_check(package, settings={**TRACK_ENVELOPE, "minWaveformCorrelation": 0.1}),
                                "settings differ"),
                               (track_check(package, settings=None), "settings differ"),
                               (track_check(package, method={"pcm": "sample_exact_scheduled_placement",
                                                             "compressed": None}), "method differs"),
                               (track_check(package, waveform={"audibleWindows": 0, "deviantWindows": 0}),
                                "compressed-waveform evidence"),
                               (track_check(package, waveform={"audibleWindows": 180, "deviantWindows": 3}),
                                "compressed-waveform evidence")):
            with self.assertRaisesRegex(ValueError, message):
                self.build(package, screening, qc, text, track_check=check)

    def test_asr_runtime_settings_must_match_screening_and_calibration(self):
        package, screening, qc, text = audio_fixture(flagged=True)
        self.build(package, screening, qc, text)
        # A primary score the screening receipt produced under other settings.
        other_screening = {**screening, "transcriptionBatchSize": 8}
        with self.assertRaisesRegex(ValueError, "primary ASR runtime differs from the bound screening"):
            self.build(package, other_screening, qc, text)
        # A secondary ASR run another way than the calibration measured.
        other = copy.deepcopy(qc)
        other["results"][1]["asrSecondarySettingsSha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "secondary ASR runtime settings differ from calibration"):
            self.build(package, screening, other, text)

    def test_audio_qc_source_spans_must_be_the_frozen_ones(self):
        # A zero, negative or inflated span would disable the source-ratio check.
        anchor, candidate = audio_sources()
        for span in (0, -1.0, 9.0, None, True):
            package, screening, qc, text = audio_fixture()
            qc["results"][1]["sourceSeconds"] = span
            with self.subTest(span=span), self.assertRaisesRegex(ValueError, "source spans are not the frozen"):
                self.build(package, screening, qc, text)
        package, screening, qc, text = audio_fixture()
        other_anchor = copy.deepcopy(anchor)
        other_anchor["sourceUnits"][0]["end"] = 20.0
        for kwargs in ({"anchor": other_anchor}, {"candidate": {"groups": candidate["groups"][:1]}}):
            with self.assertRaisesRegex(ValueError, "differs from the waived text"):
                self.build(package, screening, qc, text, **kwargs)

    def test_audio_waiver_binds_a_condensed_text_waiver(self):
        # Layer 4 checks the condensation binding before captions show the full text.
        package, screening, qc, text = audio_fixture()
        text["condensedGroupIds"] = [text["reviewedGroupIds"][0]]
        text["condensationBindingJsonSha256"] = "a" * 64
        receipt = self.build(package, screening, qc, text)
        self.assertEqual(receipt["textWaiverJsonSha256"], basis.json_sha256(text))

    def test_audio_qc_must_use_calibrated_release_thresholds(self):
        package, screening, qc, text = audio_fixture()
        permissive = copy.deepcopy(qc)
        permissive["thresholds"]["maxLeadingSilenceSeconds"] = 10
        missing = copy.deepcopy(qc)
        del missing["thresholds"]
        changed = copy.deepcopy(qc)
        changed["thresholds"]["asrMinSimilarity"] = 0.01
        for receipt in (permissive, missing, changed):
            with self.assertRaisesRegex(ValueError, "thresholds differ"):
                self.build(package, screening, receipt, text)
        self.build(package, screening, qc, text)

    def test_audio_qc_from_older_qc_code_is_refused(self):
        package, screening, qc, text = audio_fixture()
        qc["implementationSha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "implementation other than the calibrated one"):
            self.build(package, screening, qc, text)

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
        text_only["trials"] = text_only["detected"] = sum(row["trials"] for row in text_only["kinds"].values())
        with self.assertRaisesRegex(ValueError, "audio checks"):
            basis.build_audio_waiver(package, screening, qc, text, text_only, track_check=track_check(package),
                                     anchor=audio_sources()[0], candidate=audio_sources()[1],
                                     created_at="2026-10-07T02:00:00+00:00")
        # The same calibration is enough for the text waiver.
        self.assertTrue(basis.calibration_summary(text_only, "ko", IMPLEMENTATION)["semanticChecksIncluded"])

    def test_flagged_unit_needs_secondary_asr(self):
        package, screening, qc, text = audio_fixture(flagged=True)
        with self.assertRaisesRegex(ValueError, "CLI label differs"):
            self.build(package, screening, qc, text, secondary_asr_model="tiny-asr")
        receipt = self.build(package, screening, qc, text)
        self.assertEqual(receipt["secondaryAsrModel"], SECONDARY_ASR)
        self.assertEqual(receipt["unitResults"][1]["secondaryAsrModel"], SECONDARY_ASR)
        self.assertEqual(receipt["unitResults"][1]["asr"], "secondary_pass")
        basis.validate_audio_waiver(package, receipt, screening)
        tampered = copy.deepcopy(receipt)
        tampered["unitResults"][1]["secondarySimilarity"] = 0.5
        with self.assertRaisesRegex(ValueError, "secondary ASR"):
            basis.validate_audio_waiver(package, tampered, screening)

    def test_secondary_identity_keeps_the_calibrated_revision_and_checks_unit_binding(self):
        package, screening, qc, text = audio_fixture(flagged=True)
        identity = {"model": "gpt-transcribe", "modelRevision": "release-r2"}
        qc["results"][1]["asrSecondaryModel"] = identity
        cal = calibration(asrIdentity={"primary": PRIMARY_ASR, "secondary": identity})
        receipt = basis.build_audio_waiver(package, screening, qc, text, cal,
                                          track_check=track_check(package),
                                          anchor=audio_sources()[0], candidate=audio_sources()[1])
        self.assertEqual(receipt["secondaryAsrModel"], identity)
        basis.validate_audio_waiver(package, receipt, screening)
        for key, value in (("model", "tiny-asr"), ("modelRevision", "release-r1")):
            tampered = copy.deepcopy(receipt)
            tampered["secondaryAsrModel"][key] = value
            with self.assertRaisesRegex(ValueError, "identity differs"):
                basis.validate_audio_waiver(package, tampered, screening)

    def test_legacy_audio_waivers_are_supported_only_without_secondary_evidence(self):
        for flagged in (False, True):
            package, screening, qc, text = audio_fixture(flagged=flagged)
            legacy = self.build(package, screening, qc, text)
            legacy["schemaVersion"] = basis.LEGACY_AUDIO_WAIVER_SCHEMA
            legacy["secondaryAsrModel"] = "gpt-transcribe" if flagged else None
            for row in legacy["unitResults"]:
                row.pop("secondaryAsrModel")
            if flagged:
                with self.assertRaisesRegex(ValueError, "Legacy flagged audio waiver needs reissuance"):
                    basis.validate_audio_waiver(package, legacy, screening)
            else:
                stage.validate_audio_screening_review(package, legacy, screening)

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
        # Same bytes, but the (secondary) ASR compared them with another script.
        retexted = copy.deepcopy(qc)
        retexted["results"][0]["textSha256"] = sha("other script")
        with self.assertRaisesRegex(ValueError, "against different text"):
            self.build(package, screening, retexted, text)
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
