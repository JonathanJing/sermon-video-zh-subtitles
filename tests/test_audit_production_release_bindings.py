"""Regression tests for private Layer 3 → public Production release bindings."""

from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from scripts import audit_production_release_bindings as binding


PAGE = "2026-09-27-test"
LOCALE = "ko"
SOURCE = "a" * 64
FULL = "b" * 64


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")


class ProductionReleaseBindingAuditTest(unittest.TestCase):
    def setUp(self) -> None:
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        self.public = root / "public"
        self.private = root / "private"
        self.public.mkdir()
        self.private.mkdir()
        self.spoken_path = self.private / "spoken-candidate.approved.json"
        self.spoken_receipt_path = self.private / "spoken-human-review-receipt.json"
        self.spoken = {
            "schemaVersion": "sermon-target-language-candidate-v2",
            "sourceLocale": "en", "targetLocale": LOCALE,
            "englishSourcePackageJsonSha256": SOURCE,
            "status": "human_translation_approved",
            "humanReview": {"translation": "approved"},
            "groups": [{"translationGroupId": "u001"}],
        }
        write_json(self.spoken_path, self.spoken)
        self.spoken_hash = binding.canonical_hash(self.spoken)
        self.spoken_receipt = {
            "schemaVersion": "sermon-target-language-human-review-receipt-v1",
            "decision": "approved", "targetLocale": LOCALE,
            "englishSourcePackageJsonSha256": SOURCE,
            "candidateJsonSha256": self.spoken_hash,
            "reviewedGroupIds": ["u001"], "reviewer": "test reviewer",
        }
        write_json(self.spoken_receipt_path, self.spoken_receipt)
        track = self.private / "track.mp3"
        track.write_bytes(b"reviewed speech")
        captions = self.private / "captions.json"
        captions.write_bytes(b'{"cues":[]}\n')
        self.package = {
            "schemaVersion": "sermon-target-language-audio-package-v1",
            "targetLocale": LOCALE,
            "englishSourcePackageJsonSha256": SOURCE,
            "targetLanguageCandidateJsonSha256": self.spoken_hash,
            "status": "human_reviewed",
            "humanReview": {"status": "approved", "humanApproval": True,
                            "fullPlayback": "approved"},
            "machineScreening": {"status": "pass"},
            "units": [{"textGroupId": "u001"}],
            "track": {"path": str(track), "sha256": binding.file_hash(track, "track")},
            "captions": {"path": str(captions),
                         "sha256": binding.file_hash(captions, "captions")},
            "issues": [],
        }
        self.package_path = self.private / "audio-package.human-reviewed.json"
        self.receipt_path = self.private / "audio-human-review-receipt.json"
        self.release_path = self.public / "releases-v2" / PAGE / f"{LOCALE}.json"
        self.catalog_path = self.public / "multilingual-v3.json"
        self.assets = {
            "page": self.public / "pages" / PAGE / LOCALE / "index.html",
            "content": self.public / "content" / PAGE / f"{LOCALE}.json",
            "audio": self.public / "media" / PAGE / f"{LOCALE}.mp3",
            "captions": self.public / "captions" / PAGE / f"{LOCALE}.json",
        }
        for path in self.assets.values():
            path.parent.mkdir(parents=True, exist_ok=True)
        self.assets["page"].write_text("<html></html>", encoding="utf-8")
        write_json(self.assets["content"], {
            "englishSourcePackageJsonSha256": SOURCE,
            "targetLanguageCandidateJsonSha256": FULL,
        })
        self.assets["audio"].write_bytes(track.read_bytes())
        self.assets["captions"].write_bytes(captions.read_bytes())
        self.save_package()
        self.receipt = {
            "schemaVersion": "sermon-target-language-audio-human-review-receipt-v2",
            "targetLocale": LOCALE,
            "englishSourcePackageJsonSha256": SOURCE,
            "targetLanguageCandidateJsonSha256": self.spoken_hash,
            "targetLanguageAudioPackageJsonSha256": binding.canonical_hash(self.package),
            "trackSha256": self.package["track"]["sha256"],
            "machineScreeningStatus": "pass",
            "decision": "approved", "fullPlayback": "approved",
            "videoSync1x": "approved", "reviewedUnitIds": ["u001"],
            "reviewedBy": "test reviewer", "reviewedAt": "2026-09-27T13:12:00Z",
            "checks": {check: "approved" for check in binding.APPROVAL_CHECKS},
            "asrAdjudications": [], "issues": [],
        }
        write_json(self.receipt_path, self.receipt)
        self.release = {
            "schemaVersion": "sermon-target-language-release-package-v2",
            "pageId": PAGE, "sourceLocale": "en", "targetLocale": LOCALE,
            "interfaceLocale": LOCALE, "contentLocale": LOCALE,
            "audioLocale": LOCALE, "status": "published_http_verified",
            "httpVerification": {"status": "pass"},
            "contentStatus": "human_reviewed", "audioStatus": "human_reviewed",
            "targetLanguageCandidateJsonSha256": FULL,
            "spokenTargetLanguageCandidateJsonSha256": self.spoken_hash,
            "targetLanguageAudioPackageJsonSha256": binding.canonical_hash(self.package),
            "issues": [],
            "assets": [
                {"role": role, "path": "/" + str(path.relative_to(self.public)),
                 "sha256": binding.file_hash(path, role)}
                for role, path in self.assets.items()
            ],
        }
        self.catalog = {
            "schemaVersion": "sermon-multilingual-catalog-v3",
            "defaultPageId": PAGE,
            "pages": [{
                "id": PAGE, "sourceLocale": "en",
                "sourceIdentitySha256": SOURCE,
                "targets": {LOCALE: {
                    "releasePackageUrl": f"/releases-v2/{PAGE}/{LOCALE}.json",
                    "releasePackageJsonSha256": "",
                    "contentStatus": "human_reviewed",
                    "audioStatus": "human_reviewed",
                    "capabilities": ["text", "captions", "audio"],
                }},
            }],
        }
        self.save_release()

    def save_package(self) -> None:
        write_json(self.package_path, self.package)

    def save_release(self) -> None:
        write_json(self.release_path, self.release)
        self.catalog["pages"][0]["targets"][LOCALE]["releasePackageJsonSha256"] = (
            binding.file_hash(self.release_path, "release"))
        write_json(self.catalog_path, self.catalog)

    def run_audit(self) -> dict:
        return binding.audit(self.public, {LOCALE: self.package_path},
                             {LOCALE: self.receipt_path},
                             {LOCALE: self.spoken_path},
                             {LOCALE: self.spoken_receipt_path})

    def test_valid_reviewed_release_has_private_path_free_report(self) -> None:
        report = self.run_audit()
        self.assertEqual(report["status"], "pass")
        self.assertEqual(report["locales"][0]["reviewedUnits"], 1)
        self.assertNotIn(str(self.private), json.dumps(report))
        self.assertNotIn("audio-package.human-reviewed.json", json.dumps(report))

    def test_changed_layer3_hash_is_rejected_even_when_catalog_is_resealed(self) -> None:
        self.release["targetLanguageAudioPackageJsonSha256"] = "d" * 64
        self.save_release()
        with self.assertRaisesRegex(binding.BindingAuditError,
                                    "reviewed Layer 3 package differs"):
            self.run_audit()

    def test_wrong_layer3_locale_is_rejected_even_when_hashes_are_resealed(self) -> None:
        self.package["targetLocale"] = "es"
        self.save_package()
        changed_hash = binding.canonical_hash(self.package)
        self.receipt["targetLanguageAudioPackageJsonSha256"] = changed_hash
        write_json(self.receipt_path, self.receipt)
        self.release["targetLanguageAudioPackageJsonSha256"] = changed_hash
        self.save_release()
        with self.assertRaisesRegex(binding.BindingAuditError,
                                    "reviewed Layer 3 package differs"):
            self.run_audit()

    def test_public_audio_byte_change_is_rejected(self) -> None:
        self.assets["audio"].write_bytes(b"different audio")
        with self.assertRaisesRegex(binding.BindingAuditError,
                                    "published audio hash differs"):
            self.run_audit()

    def test_audio_receipt_locale_change_is_rejected(self) -> None:
        self.receipt["targetLocale"] = "es"
        write_json(self.receipt_path, self.receipt)
        with self.assertRaisesRegex(binding.BindingAuditError,
                                    "human audio review receipt differs"):
            self.run_audit()

    def test_unapproved_spoken_script_is_rejected(self) -> None:
        self.spoken_receipt["decision"] = "pending"
        write_json(self.spoken_receipt_path, self.spoken_receipt)
        with self.assertRaisesRegex(binding.BindingAuditError,
                                    "spoken human review receipt differs"):
            self.run_audit()


if __name__ == "__main__":
    unittest.main()
