import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from jsonschema import Draft202012Validator

from scripts import build_sep27_page_audio_extension as subject


class DualTextBindingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source_hash = "a" * 64
        self.locale = "ko"
        self.full = "完整显示译文。"
        self.spoken_text = "口播短稿。"
        self.group_id = "g1"
        self.display = self.candidate(self.full)
        self.spoken = self.candidate(self.spoken_text)
        self.content = {
            "schemaVersion": "sermon-full-video-text-content-v1",
            "pageId": subject.PAGE_ID, "targetLocale": self.locale,
            "status": "human_reviewed",
            "englishSourcePackageJsonSha256": self.source_hash,
            "targetLanguageCandidateJsonSha256": subject.stage.canonical_sha(self.display),
            "cues": [{"textGroupId": self.group_id, "sourceUnitIds": ["u1"],
                      "start": 0, "end": 1, "text": self.full}],
        }
        self.track = self.root / "ko.mp3"
        self.track.write_bytes(b"mp3 fixture")
        self.captions = self.root / "captions.json"
        self.captions.write_text(json.dumps({"cues": [{"textGroupId": self.group_id,
            "text": self.spoken_text, "start": 0, "end": 1}]}))
        self.schedule = self.root / "schedule.json"
        self.schedule.write_text(json.dumps({"status": "pass", "issues": [],
            "targetLocale": self.locale, "entries": [{"textGroupId": self.group_id,
            "sourceUnitIds": ["u1"], "plannedStart": 0, "plannedEnd": 1}]}))
        self.audio = {
            "status": "human_reviewed", "targetLocale": self.locale,
            "englishSourcePackageJsonSha256": self.source_hash,
            "targetLanguageCandidateJsonSha256": subject.stage.canonical_sha(self.spoken),
            "humanReview": {"humanApproval": True, "fullPlayback": "approved",
                            "reviewedBy": "human", "reviewedAt": "2026-09-27T08:00:00Z"},
            "track": self.artifact(self.track),
            "captions": self.artifact(self.captions),
            "schedule": self.artifact(self.schedule),
            "units": [{"textGroupId": self.group_id,
                       "targetTextSha256": hashlib.sha256(self.spoken_text.encode()).hexdigest()}],
        }
        self.review = {
            "schemaVersion": "sermon-target-language-audio-human-review-receipt-v2",
            "targetLocale": self.locale,
            "englishSourcePackageJsonSha256": self.source_hash,
            "targetLanguageCandidateJsonSha256": subject.stage.canonical_sha(self.spoken),
            "targetLanguageAudioPackageJsonSha256": subject.stage.canonical_sha(self.audio),
            "trackSha256": self.audio["track"]["sha256"],
            "decision": "approved", "fullPlayback": "approved", "videoSync1x": "approved",
            "reviewedUnitIds": [self.group_id], "reviewedBy": "human",
            "reviewedAt": "2026-09-27T08:00:00Z", "issues": [],
            "checks": {name: "approved" for name in (
                "pronunciation", "naturalness", "completeness", "scripture",
                "voiceIdentity", "synchronization")},
        }

    def candidate(self, text):
        return {"targetLocale": self.locale,
                "englishSourcePackageJsonSha256": self.source_hash,
                "groups": [{"translationGroupId": self.group_id,
                            "sourceUnitIds": ["u1"], "targetText": text}]}

    def artifact(self, path):
        return {"path": str(path), "sha256": subject.stage.file_sha(path)}

    def checked(self):
        with mock.patch.object(subject.stage, "reviewed_candidate", return_value=True), \
             mock.patch.object(subject.stage, "validate_audio_screening_review"), \
             mock.patch.object(subject.stage, "decode_audio", return_value=1):
            return subject.checked_locale(
                locale=self.locale, source_hash=self.source_hash, source_duration=1,
                content=self.content, display=self.display, spoken=self.spoken,
                audio=self.audio, review=self.review, screening={},
                audio_path=self.track, audio_package_path=self.root / "audio.json")

    def test_full_display_and_short_spoken_text_keep_distinct_hashes(self):
        row, track, captions = self.checked()
        self.assertNotEqual(row["displayCandidateJsonSha256"],
                            row["spokenCandidateJsonSha256"])
        self.assertEqual(track, self.track)
        self.assertEqual(captions, self.captions)
        self.assertEqual(self.content["cues"][0]["text"], self.full)

    def test_rejects_full_content_rewrite_or_audio_bound_to_full_candidate(self):
        self.content["cues"][0]["text"] = self.spoken_text
        with self.assertRaisesRegex(ValueError, "published cues"):
            self.checked()
        self.content["cues"][0]["text"] = self.full
        self.audio["targetLanguageCandidateJsonSha256"] = subject.stage.canonical_sha(self.display)
        with self.assertRaisesRegex(ValueError, "spoken script"):
            self.checked()

    def test_rejects_missing_source_coverage_and_wrong_spoken_caption(self):
        self.spoken["groups"][0]["sourceUnitIds"] = ["u2"]
        with self.assertRaisesRegex(ValueError, "same complete source"):
            self.checked()
        self.spoken["groups"][0]["sourceUnitIds"] = ["u1"]
        self.captions.write_text(json.dumps({"cues": [{"textGroupId": self.group_id,
            "text": self.full, "start": 0, "end": 1}]}))
        self.audio["captions"] = self.artifact(self.captions)
        self.review["targetLanguageAudioPackageJsonSha256"] = subject.stage.canonical_sha(self.audio)
        with self.assertRaisesRegex(ValueError, "captions do not follow"):
            self.checked()

    def test_manifest_schema_separates_display_and_spoken_identity(self):
        row, _, _ = self.checked()
        row.update({"displayContentSha256": "b" * 64,
                    "audioHumanReviewReceiptJsonSha256": "c" * 64,
                    "machineScreeningReceiptJsonSha256": "d" * 64,
                    "audio": {"path": "/media/ko.mp3", "sha256": "e" * 64},
                    "captions": {"path": "/captions/ko.json", "sha256": "f" * 64}})
        manifest = {"schemaVersion": "sermon-full-video-audio-extension-v1",
                    "pageId": subject.PAGE_ID,
                    "englishSourcePackageJsonSha256": self.source_hash,
                    "sourceMediaSha256": "1" * 64,
                    "pageDataSha256": subject.PAGE_DATA_SHA256,
                    "status": "three_locale_audio_human_reviewed_candidate",
                    "locales": {locale: row for locale in subject.LOCALES}}
        schema = subject.read(subject.ROOT / "schemas" / subject.SCHEMA)
        self.assertEqual(list(Draft202012Validator(schema).iter_errors(manifest)), [])
        manifest["locales"]["ko"]["spokenCandidateJsonSha256"] = "invalid"
        self.assertTrue(list(Draft202012Validator(schema).iter_errors(manifest)))

    def test_staging_keeps_all_published_full_text_bytes(self):
        base = self.root / "base"
        page = base / "pages" / subject.PAGE_ID
        page.mkdir(parents=True)
        page_data = page / "page-data.js"
        page_data.write_text("const DATA={};\n")
        html = ("<html><body>三语正式配音尚在制作和同步审核中。"
                "三语配音完成同步和听审后另行补充。"
                '<script src="page-data.js"></script><script src="page.js"></script>'
                "</body></html>")
        (page / "index.html").write_text(html)
        anchor_file = self.root / "anchor.json"
        anchor_file.write_text(json.dumps({"sourceUnits": [{"sourceUnitId": "u1"}]}))
        source_file = self.root / "source.json"
        source_file.write_text(json.dumps({"status": "ready_for_translation",
            "source": {"media": {"durationSeconds": 1, "sha256": "3" * 64},
                       "approvedWindow": {"startSeconds": 0, "endSeconds": 1}},
            "anchors": {"artifact": {"path": str(anchor_file),
                "sha256": subject.stage.file_sha(anchor_file),
                "jsonSha256": subject.stage.canonical_sha(subject.read(anchor_file))}}}))
        self.source_hash = subject.stage.canonical_sha(subject.read(source_file))
        inputs = {name: [] for name in ("display_candidate", "spoken_candidate",
                                         "audio_package", "audio_review_receipt",
                                         "screening_receipt")}
        original_content = {}
        for locale in subject.LOCALES:
            display, spoken = self.candidate(self.full), self.candidate(self.spoken_text)
            display["targetLocale"] = spoken["targetLocale"] = locale
            content = copy.deepcopy(self.content)
            content["targetLocale"] = locale
            content["englishSourcePackageJsonSha256"] = self.source_hash
            content["sourceMediaSha256"] = "3" * 64
            content["targetLanguageCandidateJsonSha256"] = subject.stage.canonical_sha(display)
            content_file = base / "content" / subject.PAGE_ID / f"{locale}.json"
            content_file.parent.mkdir(parents=True, exist_ok=True)
            content_file.write_text(json.dumps(content))
            original_content[locale] = content_file.read_bytes()
            audio = copy.deepcopy(self.audio)
            audio["targetLocale"] = locale
            audio["englishSourcePackageJsonSha256"] = self.source_hash
            audio["targetLanguageCandidateJsonSha256"] = subject.stage.canonical_sha(spoken)
            schedule_file = self.root / f"{locale}-schedule.json"
            schedule_value = json.loads(self.schedule.read_text())
            schedule_value["targetLocale"] = locale
            schedule_file.write_text(json.dumps(schedule_value))
            audio["schedule"] = self.artifact(schedule_file)
            review = copy.deepcopy(self.review)
            review["targetLocale"] = locale
            review["englishSourcePackageJsonSha256"] = self.source_hash
            review["targetLanguageCandidateJsonSha256"] = subject.stage.canonical_sha(spoken)
            review["targetLanguageAudioPackageJsonSha256"] = subject.stage.canonical_sha(audio)
            release = {"schemaVersion": "sermon-target-language-release-package-v1",
                       "status": "published_http_verified", "audioStatus": "unavailable",
                       "targetLanguageCandidateJsonSha256": subject.stage.canonical_sha(display),
                       "assets": [{"role": "page", "path": "/page", "sha256": "1" * 64},
                                  {"role": "content", "path": "/content",
                                   "sha256": subject.stage.file_sha(content_file)}],
                       "httpVerification": {"status": "pass", "evidenceSha256": "2" * 64}}
            release_file = base / "releases" / subject.PAGE_ID / f"{locale}.json"
            release_file.parent.mkdir(parents=True, exist_ok=True)
            release_file.write_text(json.dumps(release))
            values = {"display_candidate": display, "spoken_candidate": spoken,
                      "audio_package": audio, "audio_review_receipt": review,
                      "screening_receipt": {"status": "pass"}}
            for name, value in values.items():
                path = self.root / f"{locale}-{name}.json"
                path.write_text(json.dumps(value))
                inputs[name].append(f"{locale}={path}")
        args = argparse.Namespace(base_public=base, source=source_file,
                                  out=self.root / "candidate", **inputs)
        with mock.patch.object(subject, "PAGE_DATA_SHA256", subject.stage.file_sha(page_data)), \
             mock.patch.object(subject.stage, "read_package", side_effect=lambda path, _: subject.read(path)), \
             mock.patch.object(subject.stage, "reviewed_candidate", return_value=True), \
             mock.patch.object(subject.stage, "validate_audio_screening_review"), \
             mock.patch.object(subject.stage, "decode_audio", return_value=1):
            subject.build(args)
        output = args.out
        staged_html = (output / "pages" / subject.PAGE_ID / "index.html").read_text()
        self.assertNotIn("<script>window.fullVideoPageData", staged_html)
        self.assertIn('type="module" src="sep27-page-audio-extension.mjs"', staged_html)
        self.assertEqual((output / "pages" / subject.PAGE_ID / "page-data.js").read_bytes(),
                         page_data.read_bytes())
        for locale in subject.LOCALES:
            self.assertEqual((output / "content" / subject.PAGE_ID / f"{locale}.json").read_bytes(),
                             original_content[locale])
            release = subject.read(output / "releases" / subject.PAGE_ID / f"{locale}.json")
            self.assertEqual(release["audioStatus"], "unavailable")
            self.assertEqual(release["status"], "candidate")
        manifest = subject.read(output / "pages" / subject.PAGE_ID / "audio-extension.json")
        self.assertNotEqual(manifest["locales"]["ko"]["displayCandidateJsonSha256"],
                            manifest["locales"]["ko"]["spokenCandidateJsonSha256"])


if __name__ == "__main__":
    unittest.main()
import argparse
import copy
