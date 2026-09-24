import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from scripts import multilingual_dev_preview as preview
from scripts import stage_voice_demo_dev as demo


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


class VoiceDemoStagingTest(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.base = root / "base"
        self.delivery = root / "delivery"
        self.receipt = root / "http.json"
        self.out = root / "candidate"
        public = self.base / "public"
        (public / "media").mkdir(parents=True)
        for name in demo.PAGES:
            (public / name).write_text(
                '<html><head></head><body><section id="moreOptions"></section></body></html>',
                encoding="utf-8")
        speakers = []
        refs = []
        tracks = []
        registered = []
        for n in range(6):
            speaker = f"speaker_{n}"
            original = public / "media" / f"original-{n}.mp3"
            original.write_bytes(f"original {n}".encode())
            original_hash = demo.hosting.digest(original)
            original.rename(public / "media" / f"{original_hash[:16]}-original-{n}.mp3")
            refs.append({"speakerId": speaker, "sha256": original_hash,
                         "text": f"Original English speaker {n}."})
            speakers.append({"id": speaker, "name": f"Speaker {n}",
                             "referenceSourceUrl": f"https://example.com/sermon/{n}"})
            registered.append({"speakerId": speaker, "displayName": f"Speaker {n}",
                               "authorization": {"status": "authorized",
                                                 "purposes": ["multilingual_voice_demo"]},
                               "localeCapabilities": [{"targetLocale": "vi",
                                                       "adapterOverride": {"conditioningRef":
                                                            f"speaker-reference://{speaker}/{original_hash}"}}]})
            for locale in demo.LOCALE_ORDER:
                file = self.delivery / "mp3" / speaker / f"{locale}.mp3"
                file.parent.mkdir(parents=True, exist_ok=True)
                file.write_bytes(f"{speaker} {locale}".encode())
                tracks.append({"speakerId": speaker, "targetLocale": locale,
                               "humanListeningStatus": "pending",
                               "mp3": {"path": str(file.relative_to(self.delivery)),
                                       "sha256": demo.hosting.digest(file),
                                       "fullDecode": "pass"}})
        write_json(public / "weekly.json", {"voiceBank": {"speakers": speakers}})
        write_json(self.base / "firebase.json", {"hosting": {
            "site": preview.DEV_SITE, "public": "public", "cleanUrls": False,
            "rewrites": [{"source": "/pages/**", "destination": "/index.html"}]}})
        report = {"schemaVersion": "sermon-multilingual-dev-preview-v1",
                  "status": "validated_not_deployed", "projectId": preview.DEV_PROJECT,
                  "siteId": preview.DEV_SITE, "origin": preview.DEV_ORIGIN,
                  "pageId": "test-page", "preservedPocAliases": preview.ALIAS,
                  "firebaseConfigSha256": demo.hosting.digest(self.base / "firebase.json"),
                  "files": preview.inventory(public)}
        write_json(self.base / "build-report.json", report)
        write_json(self.receipt, {"schemaVersion": "sermon-multilingual-dev-preview-http-v1",
                                  "status": "pass", "origin": preview.DEV_ORIGIN,
                                  "buildReportSha256": demo.hosting.digest(self.base / "build-report.json"),
                                  "checkedFiles": len(report["files"])})
        self.registry = {"speakers": registered}
        write_json(self.delivery / "registry.json", self.registry)
        self.source = {
            "schemaVersion": "sermon-multilingual-voice-demo-delivery-v1",
            "status": "encoded_and_fully_decoded",
            "scope": "voice_capability_audition_not_sermon_translation",
            "speakerCount": 6, "trackCount": 24,
            "humanListeningStatus": "pending", "tracks": tracks}
        write_json(self.delivery / "delivery-manifest.json", self.source)
        write_json(self.delivery / "references.json", {
            "schemaVersion": "sermon-multilingual-voice-demo-references-v1",
            "textEvidenceStatus": "machine_screening_only", "references": refs})
        self.script = {
            "schemaVersion": "sermon-multilingual-voice-demo-script-v1",
            "scope": "voice_capability_audition_not_sermon_translation",
            "locales": [{"targetLocale": locale, "text": f"Sample {locale}."}
                        for locale in demo.LOCALE_ORDER]}
        write_json(self.delivery / "demo-script.json", self.script)

    def stage_fixture(self):
        validated = (self.source, self.script, self.registry,
                     self.delivery / "demo-script.json", self.delivery / "registry.json",
                     ["a" * 64, "b" * 64])
        with patch.object(demo.voice_preview, "validate", return_value=validated) as check:
            report = demo.stage(self.base, self.delivery, self.receipt, self.out, {})
        check.assert_called_once_with(self.delivery, decode=True)
        return report

    def test_stages_originals_before_samples_without_promoting_review(self):
        report = self.stage_fixture()
        self.assertEqual(report["addedFileCount"], 33)
        self.assertEqual(len(preview.candidate_report(self.out)["files"]),
                         len(report["devBaseFiles"]) + 33)
        catalog = demo.public_catalog(self.out / "public")
        self.assertEqual(catalog["humanListeningStatus"], "pending")
        for speaker in catalog["speakers"]:
            self.assertEqual([sample["locale"] for sample in speaker["samples"]],
                             list(demo.LOCALE_ORDER))
            self.assertIn("en-original", speaker["original"]["path"])
        self.assertEqual((self.out / "public/weekly.json").read_bytes(),
                         (self.base / "public/weekly.json").read_bytes())

    def test_rejects_changed_audio_or_review_status(self):
        self.stage_fixture()
        catalog_path = self.out / "public" / demo.PREFIX / "catalog.json"
        catalog = json.loads(catalog_path.read_text())
        audio = self.out / "public" / catalog["speakers"][0]["samples"][0]["path"].lstrip("/")
        audio.write_bytes(b"changed")
        with self.assertRaisesRegex(ValueError, "file changed|audio differs"):
            preview.candidate_report(self.out)
        audio.write_bytes(b"speaker_0 zh-Hans")
        catalog["humanListeningStatus"] = "approved"
        write_json(catalog_path, catalog)
        with self.assertRaisesRegex(ValueError, "file changed|approved sermon content"):
            preview.candidate_report(self.out)

    def test_rejects_failed_source_identity_validation(self):
        with patch.object(demo.voice_preview, "validate",
                          side_effect=ValueError("Voice identity differs")):
            with self.assertRaisesRegex(ValueError, "Voice identity differs"):
                demo.stage(self.base, self.delivery, self.receipt, self.out, {})
        self.assertFalse(self.out.exists())


if __name__ == "__main__":
    unittest.main()
