"""Formal Dev staging must fail before writing when any locale is incomplete."""

import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from scripts import build_formal_dev_release_assets as assets_builder


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("stage_formal_multilingual_dev", ROOT / "scripts/stage_formal_multilingual_dev.py")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class FormalDevStageTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.assets = self.root / "assets"
        self.source_path = self.root / "source.json"
        self.anchor_path = self.write_json(self.root / "anchors.json",
                                           {"sourceUnits": [{"sourceUnitId": "unit-1"}]})
        self.anchor_hash = MODULE.canonical_sha(json.loads(self.anchor_path.read_text()))
        self.source = {
            "status": "ready_for_translation", "translationEligible": True,
            "source": {"serviceDate": "2026-09-20", "approvedWindow": {"humanApproval": True}},
            "review": {"humanApproval": True}, "issues": [],
            "anchors": {"artifact": {"path": str(self.anchor_path),
                                      "sha256": MODULE.file_sha(self.anchor_path),
                                      "jsonSha256": self.anchor_hash}},
        }
        self.source_hash = MODULE.canonical_sha(self.source)
        self.page_id = "formal-page-1"
        self.paths = {name: {} for name in ("candidate", "receipt", "audio", "audio_receipt", "content_receipt", "release")}
        self.audio_file = self.root / "tone.wav"
        subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-f", "lavfi", "-i",
                        "sine=frequency=440:duration=0.5", "-ac", "1", "-ar", "16000",
                        "-acodec", "pcm_s16le", "-y",
                        str(self.audio_file)], check=True)
        self.audio_hash = MODULE.file_sha(self.audio_file)
        for locale in MODULE.LOCALES:
            self.make_locale(locale)

    def tearDown(self):
        self.temporary.cleanup()

    def write_json(self, path, value):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n")
        return path

    def make_locale(self, locale):
        text = f"{locale} approved text"
        group_id = f"{locale}-group-1"
        candidate = {
            "schemaVersion": "sermon-target-language-candidate-v2", "sourceLocale": "en",
            "targetLocale": locale, "englishSourcePackageJsonSha256": self.source_hash,
            "anchorManifestSha256": self.anchor_hash, "translationPolicySha256": "b" * 64,
            "status": "human_translation_approved", "releaseEligible": False,
            "generation": {
                "translator": {"model": "fixture", "promptVersion": "v1", "requestIds": ["t"]},
                "reviewer": {"model": "fixture", "promptVersion": "v1", "requestIds": ["r"]}},
            "groups": [{"translationGroupId": group_id, "sourceUnitIds": ["unit-1"],
                        "targetUtterances": [text], "targetText": text,
                        "coverage": [{"sourceUnitId": "unit-1", "targetText": text}],
                        "semanticReview": {"status": "pass", "checks": {
                            "completeMeaning": "pass", "negationsNumbersNames": "pass",
                            "quotationAttribution": "pass", "noAddedMeaning": "pass"},
                            "evidence": "fixture", "uncertainty": [], "issues": []},
                        "languageReview": {"status": "pass", "pluginId": f"fixture-{locale}",
                                           "policySha256": "b" * 64,
                                           "checks": [{"checkId": "fixture", "status": "pass", "evidence": "fixture"}]}}],
            "modelReview": {"status": "pass", "reviewedGroupIds": [group_id]},
            "humanReview": {"translation": "approved", "reviewer": "fixture-reviewer",
                            "reviewedAt": "2026-09-23T00:00:00Z", "reviewedGroupIds": [group_id]},
        }
        candidate_path = self.write_json(self.root / f"{locale}-candidate.json", candidate)
        candidate_hash = MODULE.canonical_sha(candidate)
        receipt = {"schemaVersion": "sermon-target-language-human-review-receipt-v1",
                   "decision": "approved", "targetLocale": locale,
                   "englishSourcePackageJsonSha256": self.source_hash,
                   "anchorManifestJsonSha256": self.anchor_hash,
                   "translationPolicySha256": "b" * 64,
                   "candidateJsonSha256": candidate_hash,
                   "reviewer": "fixture-reviewer", "reviewedAt": "2026-09-23T00:00:00Z",
                   "reviewedGroupIds": [group_id],
                   "groupReviews": [{"translationGroupId": group_id, "decision": "approved",
                                     "evidence": "fixture"}]}
        receipt_path = self.write_json(self.root / f"{locale}-receipt.json", receipt)
        captions = self.root / f"{locale}-captions.json"
        self.write_json(captions, {"cues": [{"textGroupId": group_id, "text": text,
                                             "start": 0.0, "end": 0.5}]})
        caption_hash = MODULE.file_sha(captions)
        schedule = {"targetLocale": locale, "timingKind": "measured_target_audio",
                    "status": "pass", "issues": [], "trackDurationSeconds": 0.5,
                    "entries": [{"textGroupId": group_id, "sourceUnitIds": ["unit-1"],
                                 "plannedStart": 0.0, "plannedEnd": 0.5}]}
        schedule_path = self.write_json(self.root / f"{locale}-schedule.json", schedule)
        audio = {
            "schemaVersion": "sermon-target-language-audio-package-v1", "packageId": f"{locale}-audio",
            "englishSourcePackageJsonSha256": self.source_hash,
            "targetLanguageCandidateJsonSha256": candidate_hash,
            "targetLanguageSpeechJobJsonSha256": "c" * 64, "targetLocale": locale,
            "status": "human_reviewed", "ratePolicy": "natural_no_time_stretch",
            "voice": {"provider": "fixture", "model": "fixture", "checkpointSha256": "d" * 64,
                      "targetLocaleCapability": "reviewed", "authorizationStatus": "authorized"},
            "units": [{"textGroupId": group_id, "targetTextSha256": hashlib.sha256(text.encode()).hexdigest(),
                       "audio": {"path": str(self.audio_file), "sha256": self.audio_hash},
                       "durationSeconds": 0.5}],
            "track": {"path": str(self.audio_file), "sha256": self.audio_hash},
            "captions": {"path": str(captions), "sha256": caption_hash},
            "schedule": {"path": str(schedule_path), "sha256": MODULE.file_sha(schedule_path),
                         "jsonSha256": MODULE.canonical_sha(schedule)},
            "machineScreening": {"status": "pass", "model": "fixture", "coverage": 1},
            "humanReview": {"status": "approved", "humanApproval": True,
                            "reviewedBy": "fixture-reviewer", "reviewedAt": "2026-09-23T00:00:00Z",
                            "fullPlayback": "approved"},
            "issues": [], "downstreamInvalidationKey": "e" * 64,
        }
        audio_path = self.write_json(self.root / f"{locale}-audio.json", audio)
        audio_hash = MODULE.canonical_sha(audio)
        audio_receipt = {
            "schemaVersion": "sermon-target-language-audio-human-review-receipt-v1",
            "targetLocale": locale, "englishSourcePackageJsonSha256": self.source_hash,
            "targetLanguageCandidateJsonSha256": candidate_hash,
            "targetLanguageAudioPackageJsonSha256": audio_hash,
            "trackSha256": self.audio_hash, "decision": "approved",
            "reviewedBy": "fixture-reviewer", "reviewedAt": "2026-09-23T00:00:00Z",
            "fullPlayback": "approved", "videoSync1x": "approved",
            "reviewedUnitIds": [group_id],
            "checks": {key: "approved" for key in ("pronunciation", "naturalness", "completeness",
                                                    "scripture", "voiceIdentity", "synchronization")},
            "issues": []}
        audio_receipt_path = self.write_json(self.root / f"{locale}-audio-receipt.json", audio_receipt)
        content = {"schemaVersion": "sermon-formal-dev-content-v1", "pageId": self.page_id,
                   "sourceLocale": "en", "locale": locale,
                   "englishSourcePackageJsonSha256": self.source_hash,
                   "targetLanguageCandidateJsonSha256": candidate_hash,
                   "targetLanguageAudioPackageJsonSha256": audio_hash,
                   "contentStatus": "human_reviewed", "audioStatus": "human_reviewed",
                   "series": "Approved series", "title": "Approved title", "speaker": "Speaker",
                   "scripture": "Revelation", "date": "2026-09-20", "summary": "Approved summary",
                   "durationSeconds": 0.5,
                   "cues": [{"textGroupId": group_id, "sourceUnitIds": ["unit-1"],
                             "start": 0.0, "end": 0.5, "text": text}],
                   "outline": []}
        content_path = self.write_json(self.assets / "content" / self.page_id / f"{locale}.json", content)
        content_receipt = {
            "schemaVersion": "sermon-formal-dev-content-review-receipt-v1",
            "pageId": self.page_id, "targetLocale": locale,
            "englishSourcePackageJsonSha256": self.source_hash,
            "targetLanguageCandidateJsonSha256": candidate_hash,
            "targetLanguageAudioPackageJsonSha256": audio_hash,
            "contentJsonSha256": MODULE.canonical_sha(content), "decision": "approved",
            "reviewer": "fixture-reviewer", "reviewedAt": "2026-09-23T00:00:00Z",
            "reviewedFields": ["series", "title", "speaker", "scripture", "date", "summary", "outline"]}
        content_receipt_path = self.write_json(self.root / f"{locale}-content-receipt.json", content_receipt)
        media_path = self.assets / "media" / self.page_id / f"{locale}.wav"
        media_path.parent.mkdir(parents=True, exist_ok=True)
        media_path.write_bytes(self.audio_file.read_bytes())
        captions_path = self.assets / "captions" / self.page_id / f"{locale}.json"
        captions_path.parent.mkdir(parents=True, exist_ok=True)
        captions_path.write_bytes(captions.read_bytes())
        release = {"schemaVersion": "sermon-target-language-release-package-v1",
                   "packageId": f"{self.page_id}-{locale}", "pageId": self.page_id,
                   "sourceLocale": "en", "targetLocale": locale,
                   "targetLanguageCandidateJsonSha256": candidate_hash,
                   "targetLanguageAudioPackageJsonSha256": audio_hash,
                   "status": "candidate", "contentStatus": "human_reviewed", "audioStatus": "human_reviewed",
                   "interfaceLocale": locale, "contentLocale": locale, "audioLocale": locale,
                   "assets": [{"role": role, "path": f"/{role_path}/{self.page_id}/{locale}.{suffix}",
                               "sha256": MODULE.file_sha(path)} for role, role_path, suffix, path in (
                                   ("content", "content", "json", content_path),
                                   ("audio", "media", "wav", media_path),
                                   ("captions", "captions", "json", captions_path))],
                   "httpVerification": {"status": "not_run", "evidenceSha256": None},
                   "deviceAcceptance": {"status": "not_run", "evidenceSha256": None},
                   "venueAcceptance": {"status": "not_run", "evidenceSha256": None}, "issues": []}
        release_path = self.write_json(self.root / f"{locale}-release.json", release)
        self.paths["candidate"][locale] = candidate_path
        self.paths["receipt"][locale] = receipt_path
        self.paths["audio"][locale] = audio_path
        self.paths["audio_receipt"][locale] = audio_receipt_path
        self.paths["content_receipt"][locale] = content_receipt_path
        self.paths["release"][locale] = release_path

    def args(self):
        return MODULE.parse_args(["--source", str(self.source_path), "--asset-root", str(self.assets),
                                  "--page-id", self.page_id, "--page-date", "2026-09-20",
                                  "--generated-at", "2026-09-23T00:00:00Z",
                                  "--out", str(self.root / "staged"),
                                  *sum((["--candidate", f"{locale}={self.paths['candidate'][locale]}"]
                                        for locale in MODULE.LOCALES), []),
                                  *sum((["--human-review-receipt", f"{locale}={self.paths['receipt'][locale]}"]
                                        for locale in MODULE.LOCALES), []),
                                  *sum((["--audio-package", f"{locale}={self.paths['audio'][locale]}"]
                                        for locale in MODULE.LOCALES), []),
                                  *sum((["--audio-human-review-receipt", f"{locale}={self.paths['audio_receipt'][locale]}"]
                                        for locale in MODULE.LOCALES), []),
                                  *sum((["--content-review-receipt", f"{locale}={self.paths['content_receipt'][locale]}"]
                                        for locale in MODULE.LOCALES), []),
                                  *sum((["--release", f"{locale}={self.paths['release'][locale]}"]
                                        for locale in MODULE.LOCALES), [])])

    def stage_with_fixture_source(self, args):
        real = MODULE.read_package
        with patch.object(MODULE, "read_package", side_effect=lambda path, schema:
                          self.source if path == self.source_path else real(path, schema)):
            return MODULE.stage(args)

    def test_stages_three_locale_catalog_with_no_poc_or_publication_upgrade(self):
        receipt = self.stage_with_fixture_source(self.args())
        output = self.root / "staged"
        self.assertEqual(receipt["targetLocales"], list(MODULE.LOCALES))
        self.assertEqual(receipt["deploymentStatus"], "not_deployed")
        self.assertFalse((output / "multilingual.json").exists())
        catalog = json.loads((output / "multilingual-v2.json").read_text())
        self.assertEqual(catalog["schemaVersion"], "sermon-multilingual-catalog-v2")
        self.assertEqual(set(catalog["pages"][0]["targets"]), set(MODULE.LOCALES))
        self.assertEqual(json.loads((output / "releases" / self.page_id / "ko.json").read_text())["status"], "candidate")

    def test_stages_reviewed_compressed_track_without_relabeling_audio(self):
        locale = "ko"
        mp3 = self.root / "tone.mp3"
        subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-i", str(self.audio_file),
                        "-ac", "1", "-b:a", "64k", "-y", str(mp3)], check=True)
        mp3_hash = MODULE.file_sha(mp3)
        media = self.assets / "media" / self.page_id / f"{locale}.mp3"
        media.write_bytes(mp3.read_bytes())
        (self.assets / "media" / self.page_id / f"{locale}.wav").unlink()
        audio_path = self.paths["audio"][locale]
        audio = json.loads(audio_path.read_text())
        audio["track"] = {"path": str(mp3), "sha256": mp3_hash}
        self.write_json(audio_path, audio)
        audio_hash = MODULE.canonical_sha(audio)
        review_path = self.paths["audio_receipt"][locale]
        review = json.loads(review_path.read_text())
        review["trackSha256"] = mp3_hash
        review["targetLanguageAudioPackageJsonSha256"] = audio_hash
        self.write_json(review_path, review)
        content_path = self.assets / "content" / self.page_id / f"{locale}.json"
        content = json.loads(content_path.read_text())
        content["targetLanguageAudioPackageJsonSha256"] = audio_hash
        self.write_json(content_path, content)
        receipt_path = self.paths["content_receipt"][locale]
        receipt = json.loads(receipt_path.read_text())
        receipt["targetLanguageAudioPackageJsonSha256"] = audio_hash
        receipt["contentJsonSha256"] = MODULE.canonical_sha(content)
        self.write_json(receipt_path, receipt)
        release_path = self.paths["release"][locale]
        release = json.loads(release_path.read_text())
        release["targetLanguageAudioPackageJsonSha256"] = audio_hash
        release["assets"][0]["sha256"] = MODULE.file_sha(content_path)
        release["assets"][1]["path"] = f"/media/{self.page_id}/{locale}.mp3"
        release["assets"][1]["sha256"] = mp3_hash
        self.write_json(release_path, release)
        result = self.stage_with_fixture_source(self.args())
        self.assertEqual(result["targetLocales"], list(MODULE.LOCALES))
        self.assertTrue((self.root / "staged" / "media" / self.page_id / "ko.mp3").is_file())

    def test_rejects_missing_locale_without_output(self):
        args = self.args()
        args.audio_package = args.audio_package[:-1]
        with self.assertRaisesRegex(MODULE.StageError, "all three locales"):
            self.stage_with_fixture_source(args)
        self.assertFalse(args.out.exists())

    def test_rejects_audio_binding_mismatch_without_output(self):
        path = self.paths["audio"]["es"]
        value = json.loads(path.read_text())
        value["targetLanguageCandidateJsonSha256"] = "f" * 64
        self.write_json(path, value)
        with self.assertRaisesRegex(MODULE.StageError, "Layer 3 package"):
            self.stage_with_fixture_source(self.args())
        self.assertFalse((self.root / "staged").exists())

    def test_rejects_content_that_changes_measured_cue(self):
        path = self.assets / "content" / self.page_id / "ko.json"
        content = json.loads(path.read_text())
        content["cues"][0]["text"] = "wrong caption"
        self.write_json(path, content)
        content_receipt_path = self.paths["content_receipt"]["ko"]
        content_receipt = json.loads(content_receipt_path.read_text())
        content_receipt["contentJsonSha256"] = MODULE.canonical_sha(content)
        self.write_json(content_receipt_path, content_receipt)
        release_path = self.paths["release"]["ko"]
        release = json.loads(release_path.read_text())
        release["assets"][0]["sha256"] = MODULE.file_sha(path)
        self.write_json(release_path, release)
        with self.assertRaisesRegex(MODULE.StageError, "content cues differ"):
            self.stage_with_fixture_source(self.args())
        self.assertFalse((self.root / "staged").exists())

    def test_rejects_unbound_human_review_receipt(self):
        path = self.paths["receipt"]["zh-Hans"]
        receipt = json.loads(path.read_text())
        receipt["candidateJsonSha256"] = "f" * 64
        self.write_json(path, receipt)
        with self.assertRaisesRegex(MODULE.StageError, "human review receipt"):
            self.stage_with_fixture_source(self.args())
        self.assertFalse((self.root / "staged").exists())

    def test_rejects_missing_full_video_sync_approval(self):
        path = self.paths["audio_receipt"]["es"]
        receipt = json.loads(path.read_text())
        receipt["videoSync1x"] = "pending"
        self.write_json(path, receipt)
        with self.assertRaisesRegex(MODULE.StageError, "approved"):
            self.stage_with_fixture_source(self.args())
        self.assertFalse((self.root / "staged").exists())

    def test_rejects_unbound_display_metadata_review(self):
        path = self.paths["content_receipt"]["zh-Hans"]
        receipt = json.loads(path.read_text())
        receipt["contentJsonSha256"] = "f" * 64
        self.write_json(path, receipt)
        with self.assertRaisesRegex(MODULE.StageError, "metadata review"):
            self.stage_with_fixture_source(self.args())
        self.assertFalse((self.root / "staged").exists())

    def test_rejects_displayed_outline_without_review(self):
        path = self.paths["content_receipt"]["zh-Hans"]
        receipt = json.loads(path.read_text())
        receipt["reviewedFields"].remove("outline")
        self.write_json(path, receipt)
        with self.assertRaises(MODULE.StageError):
            self.stage_with_fixture_source(self.args())
        self.assertFalse((self.root / "staged").exists())

    def test_rejects_audio_that_has_correct_hash_but_cannot_decode(self):
        broken = self.root / "broken.mp3"
        broken.write_bytes(b"not an mp3")
        digest = MODULE.file_sha(broken)
        path = self.paths["audio"]["ko"]
        audio = json.loads(path.read_text())
        audio["track"] = {"path": str(broken), "sha256": digest}
        self.write_json(path, audio)
        package_hash = MODULE.canonical_sha(audio)
        audio_receipt_path = self.paths["audio_receipt"]["ko"]
        audio_receipt = json.loads(audio_receipt_path.read_text())
        audio_receipt["targetLanguageAudioPackageJsonSha256"] = package_hash
        audio_receipt["trackSha256"] = digest
        self.write_json(audio_receipt_path, audio_receipt)
        release_path = self.paths["release"]["ko"]
        release = json.loads(release_path.read_text())
        release["targetLanguageAudioPackageJsonSha256"] = package_hash
        self.write_json(release_path, release)
        content_path = self.assets / "content" / self.page_id / "ko.json"
        content = json.loads(content_path.read_text())
        content["targetLanguageAudioPackageJsonSha256"] = package_hash
        self.write_json(content_path, content)
        content_receipt_path = self.paths["content_receipt"]["ko"]
        content_receipt = json.loads(content_receipt_path.read_text())
        content_receipt["targetLanguageAudioPackageJsonSha256"] = package_hash
        content_receipt["contentJsonSha256"] = MODULE.canonical_sha(content)
        self.write_json(content_receipt_path, content_receipt)
        release["assets"][0]["sha256"] = MODULE.file_sha(content_path)
        self.write_json(release_path, release)
        with self.assertRaisesRegex(MODULE.StageError, "readable audio stream"):
            self.stage_with_fixture_source(self.args())
        self.assertFalse((self.root / "staged").exists())

    def test_v2_human_adjudication_can_stage_original_asr_review_status(self):
        locale = "ko"
        audio_path = self.paths["audio"][locale]
        audio = json.loads(audio_path.read_text())
        audio["machineScreening"]["status"] = "requires_review"
        self.write_json(audio_path, audio)
        audio_hash = MODULE.canonical_sha(audio)
        unit = audio["units"][0]
        screening = {
            "schemaVersion": "sermon-target-language-audio-screening-v1",
            "targetLocale": locale,
            "targetLanguageSpeechJobJsonSha256": audio["targetLanguageSpeechJobJsonSha256"],
            "trackSha256": self.audio_hash, "status": "requires_review",
            "model": "fixture", "modelRevision": "weights:sha256:" + "a" * 64,
            "minSimilarity": 0.88, "coverage": 1.0,
            "reviewedGroupIds": [unit["textGroupId"]],
            "unitAudioSha256s": [self.audio_hash],
            "results": [{"textGroupId": unit["textGroupId"],
                         "targetTextSha256": unit["targetTextSha256"],
                         "audioSha256": self.audio_hash, "recognized": "fixture variant",
                         "similarity": 0.8, "differences": [],
                         "status": "requires_review"}],
            "humanListeningStatus": "pending",
        }
        screening_path = self.write_json(self.root / "ko-screening.json", screening)
        receipt_path = self.paths["audio_receipt"][locale]
        receipt = json.loads(receipt_path.read_text())
        receipt.update(schemaVersion="sermon-target-language-audio-human-review-receipt-v2",
                       targetLanguageAudioPackageJsonSha256=audio_hash,
                       machineScreeningStatus="requires_review",
                       machineScreeningReceiptJsonSha256=MODULE.canonical_sha(screening),
                       asrAdjudications=[{"textGroupId": unit["textGroupId"],
                                          "decision": "approved",
                                          "evidence": "Heard the approved words in the full 1x track."}])
        self.write_json(receipt_path, receipt)
        content_path = self.assets / "content" / self.page_id / "ko.json"
        content = json.loads(content_path.read_text())
        content["targetLanguageAudioPackageJsonSha256"] = audio_hash
        self.write_json(content_path, content)
        content_receipt_path = self.paths["content_receipt"][locale]
        content_receipt = json.loads(content_receipt_path.read_text())
        content_receipt["targetLanguageAudioPackageJsonSha256"] = audio_hash
        content_receipt["contentJsonSha256"] = MODULE.canonical_sha(content)
        self.write_json(content_receipt_path, content_receipt)
        release_path = self.paths["release"][locale]
        release = json.loads(release_path.read_text())
        release["targetLanguageAudioPackageJsonSha256"] = audio_hash
        release["assets"][0]["sha256"] = MODULE.file_sha(content_path)
        self.write_json(release_path, release)
        args = self.args()
        args.audio_screening_receipt = [f"{locale}={screening_path}"]
        for other in ("zh-Hans", "es"):
            other_audio = json.loads(self.paths["audio"][other].read_text())
            other_unit = other_audio["units"][0]
            other_screening = dict(screening,
                targetLocale=other,
                targetLanguageSpeechJobJsonSha256=other_audio["targetLanguageSpeechJobJsonSha256"],
                status="pass", reviewedGroupIds=[other_unit["textGroupId"]],
                results=[dict(screening["results"][0],
                              textGroupId=other_unit["textGroupId"],
                              targetTextSha256=other_unit["targetTextSha256"],
                              similarity=1.0, status="pass")])
            other_path = self.write_json(self.root / f"{other}-screening.json", other_screening)
            args.audio_screening_receipt.append(f"{other}={other_path}")
        self.assertEqual(self.stage_with_fixture_source(args)["deploymentStatus"], "not_deployed")

        receipt["asrAdjudications"] = []
        self.write_json(receipt_path, receipt)
        args.out = self.root / "staged-bad"
        with self.assertRaisesRegex(MODULE.StageError, "ASR review queue"):
            self.stage_with_fixture_source(args)
        self.assertFalse(args.out.exists())

    def test_reviewed_metadata_and_audio_prepare_assets_for_staging(self):
        proposal = self.root / "metadata-proposal.md"
        proposal.write_text("Approved series. Approved title. Speaker. Revelation. "
                            "Approved summary. Approved outline.")
        metadata = {
            "schemaVersion": "sermon-formal-dev-metadata-approval-v1",
            "pageId": self.page_id, "date": "2026-09-20",
            "proposalFileSha256": MODULE.file_sha(proposal),
            "decision": "approved_all_three_locales", "approvalText": "三语全部批准",
            "reviewer": "user", "recordedAt": "2026-09-23T12:00:00-07:00",
            "locales": {locale: {"series": "Approved series", "title": "Approved title",
                                "speaker": "Speaker", "scripture": "Revelation",
                                "summary": "Approved summary", "outline": ["Approved outline"]}
                        for locale in MODULE.LOCALES},
        }
        metadata_path = self.write_json(self.root / "metadata-approved.json", metadata)
        self.write_json(self.source_path, self.source)
        prepared = self.root / "prepared"
        args = assets_builder.argparse.Namespace(
            source=self.source_path, metadata=metadata_path, metadata_proposal=proposal,
            page_id=self.page_id, date="2026-09-20", out=prepared,
            candidate=[f"{locale}={self.paths['candidate'][locale]}" for locale in MODULE.LOCALES],
            audio_package=[f"{locale}={self.paths['audio'][locale]}" for locale in MODULE.LOCALES])
        real = assets_builder.stage.read_package
        with patch.object(assets_builder.stage, "read_package", side_effect=lambda path, schema:
                          self.source if path == self.source_path else real(path, schema)):
            receipt = assets_builder.build(args)
        self.assertEqual(receipt["status"], "candidate_not_deployed")
        self.assets = prepared / "assets"
        for locale in MODULE.LOCALES:
            self.paths["content_receipt"][locale] = prepared / "review/content" / f"{locale}.json"
            self.paths["release"][locale] = prepared / "releases" / f"{locale}.json"
        staged = self.stage_with_fixture_source(self.args())
        self.assertEqual(staged["deploymentStatus"], "not_deployed")
        with self.assertRaisesRegex(ValueError, "immutable"):
            assets_builder.build(args)


if __name__ == "__main__":
    unittest.main()
