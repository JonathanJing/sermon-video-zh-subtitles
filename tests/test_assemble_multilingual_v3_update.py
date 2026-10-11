import copy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from scripts import assemble_multilingual_v3_update as update


SHA = "a" * 64


def write(path: Path, value: dict | bytes) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(value, dict):
        path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n")
    else:
        path.write_bytes(value)
    return update.digest(path)


def page_fixture(public: Path, page_id: str, date: str) -> dict:
    video_sha = write(public / f"pages/{page_id}/full-video-browser.mp4", b"complete sermon video")
    targets = {}
    english_targets = {}
    alignment_targets = {}
    for locale in ("zh-Hans", "ko", "es"):
        page_sha = write(public / f"pages/{page_id}/{locale}/index.html",
                         f"<html>{locale} reviewed sermon</html>".encode())
        content_sha = write(public / f"content/{page_id}/{locale}.json", {
            "pageId": page_id, "targetLocale": locale, "series": "启示录",
            "title": "耶稣配得", "browserVideoSha256": video_sha,
            "sourceVideoUrl": f"/pages/{page_id}/full-video-browser.mp4",
        })
        captions_sha = write(public / f"captions/{page_id}/{locale}.json", {"cues": []})
        audio_sha = write(public / f"media/{page_id}/{locale}.mp3",
                          f"{locale} reviewed audio".encode())
        index = {
            "schemaVersion": "sermon-landmark-index-v1", "pageId": page_id,
            "sourceSha256": SHA, "trackSha256": audio_sha,
        }
        temporary_index = public / f"fingerprints/{locale}-tmp.json"
        index_sha = write(temporary_index, index)
        index_name = f"fingerprints/{index_sha[:16]}-landmarks.json"
        temporary_index.rename(public / index_name)
        binding = {
            "schemaVersion": "sermon-audio-fingerprint-binding-v1",
            "pageId": page_id, "sourceSha256": SHA, "trackSha256": audio_sha,
            "sourceStartSeconds": 0, "sourceEndSeconds": 60,
            "algorithmVersion": "spectral-landmarks-v1", "captureSeconds": 10,
            "indexSha256": index_sha, "indexUrl": "/" + index_name,
        }
        release = {
            "schemaVersion": "sermon-target-language-release-package-v2",
            "packageId": f"{page_id}-{locale}", "pageId": page_id,
            "sourceLocale": "en", "targetLocale": locale,
            "targetLanguageCandidateJsonSha256": SHA,
            "spokenTargetLanguageCandidateJsonSha256": SHA,
            "targetLanguageAudioPackageJsonSha256": SHA,
            "status": "published_http_verified", "contentStatus": "human_reviewed",
            "audioStatus": "human_reviewed", "interfaceLocale": locale,
            "contentLocale": locale, "audioLocale": locale,
            "assets": [
                {"role": "page", "path": f"/pages/{page_id}/{locale}/index.html",
                 "sha256": page_sha},
                {"role": "content", "path": f"/content/{page_id}/{locale}.json",
                 "sha256": content_sha},
                {"role": "captions", "path": f"/captions/{page_id}/{locale}.json",
                 "sha256": captions_sha},
                {"role": "audio", "path": f"/media/{page_id}/{locale}.mp3",
                 "sha256": audio_sha},
            ],
            "httpVerification": {"status": "pass", "evidenceSha256": SHA},
            "deviceAcceptance": {"status": "not_run", "evidenceSha256": None},
            "venueAcceptance": {"status": "not_run", "evidenceSha256": None},
            "issues": [],
        }
        release_sha = write(public / f"releases-v2/{page_id}/{locale}.json", release)
        targets[locale] = {
            "releasePackageUrl": f"/releases-v2/{page_id}/{locale}.json",
            "releasePackageJsonSha256": release_sha,
            "contentStatus": "human_reviewed", "audioStatus": "human_reviewed",
            "capabilities": ["text", "captions", "audio", "alignment"],
            "audioFingerprint": binding,
        }
        english_targets[locale] = {"releasePackageJsonSha256": release_sha,
                                   "contentSha256": content_sha,
                                   "captionsSha256": captions_sha}
        alignment_targets[locale] = {"releasePackageJsonSha256": release_sha,
                                     "audioFingerprint": binding}
    write(public / f"english-reference/{page_id}.json", {
        "schemaVersion": "sermon-published-english-reference-v1",
        "pageId": page_id, "sourceIdentitySha256": SHA,
        "sourceMediaSha256": SHA, "reviewState": "human_approved",
        "targets": english_targets,
    })
    write(public / f"alignment/{page_id}.json", {
        "schemaVersion": "sermon-published-alignment-v1",
        "pageId": page_id, "sourceIdentitySha256": SHA,
        "targets": alignment_targets,
    })
    return {
        "id": page_id, "date": date, "sourceLocale": "en",
        "sourceIdentitySha256": SHA, "sourceMediaSha256": SHA,
        "title": "启示录 · 耶稣配得", "defaultTargetLocale": "zh-Hans",
        "targets": targets,
    }


def catalog(page: dict) -> dict:
    return {
        "schemaVersion": "sermon-multilingual-catalog-v3",
        "generatedAt": "2026-09-27T20:00:00Z", "defaultPageId": page["id"],
        "pages": [page],
    }


class AssembleMultilingualV3UpdateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.base = self.root / "base"
        self.stage = self.root / "stage"
        self.base.mkdir()
        self.stage.mkdir()
        self.old_page = page_fixture(self.base, "old-week", "2026-09-20")
        self.new_page = page_fixture(self.stage, "new-week", "2026-09-27")
        write(self.base / update.CATALOG, catalog(self.old_page))
        write(self.stage / update.CATALOG, catalog(self.new_page))
        write(self.base / "weekly.json", {"schemaVersion": "sermon-weekly-catalog-v1"})
        write(self.base / "app.mjs", b"current reader")
        self.manifest = self.root / "stage-manifest.json"
        self.write_manifest()

    def write_manifest(self) -> None:
        write(self.manifest, {
            "schemaVersion": update.STAGE_SCHEMA,
            "profile": update.PUBLICATION_PROFILE,
            "pageId": "new-week",
            "files": [
                {"path": "/" + name, "sha256": update.digest(path)}
                for name, path in sorted(update.regular_files(self.stage).items())
                if name != update.CATALOG
            ],
        })

    def test_adds_new_week_and_preserves_prior_site_bytes(self) -> None:
        out = self.root / "candidate"
        report = update.assemble(self.base, self.stage, self.manifest, out)
        self.assertEqual(report["status"], "validated_not_deployed")
        self.assertEqual(report["schemaVersion"], "sermon-multilingual-v3-update-candidate-v2")
        self.assertEqual(report["addedFileCount"], 21)
        self.assertEqual(report["catalogUpdateFileCount"], 1)
        self.assertEqual(report["weeklyFileCount"], 22)
        self.assertEqual(report["oldCatalogSha256"],
                         update.digest(out / f"rollback-{update.CATALOG}"))
        self.assertEqual((out / "public/app.mjs").read_bytes(), b"current reader")
        self.assertEqual((out / "public/weekly.json").read_bytes(),
                         (self.base / "weekly.json").read_bytes())
        merged = update.load(out / "public" / update.CATALOG)
        self.assertEqual(merged["defaultPageId"], "new-week")
        self.assertEqual({page["id"] for page in merged["pages"]}, {"old-week", "new-week"})

    def test_rejects_base_that_carries_the_v4_catalog(self) -> None:
        (self.base / "multilingual-v4.json").write_text("{}")
        with self.assertRaisesRegex(ValueError, "four-layer seal"):
            update.assemble(self.base, self.stage, self.manifest, self.root / "candidate")
        self.assertFalse((self.root / "candidate").exists())

    def test_rejects_stage_mutation_after_manifest_validation(self):
        original = update.tempfile.mkdtemp
        changed = self.stage / "english-reference/new-week.json"

        def change_after_admission(*args, **kwargs):
            value = update.load(changed)
            value["fixtureNote"] = "not present in admitted manifest"
            write(changed, value)
            return original(*args, **kwargs)

        out = self.root / "changed-stage-candidate"
        with patch.object(update.tempfile, "mkdtemp", side_effect=change_after_admission):
            with self.assertRaises(ValueError):
                update.assemble(self.base, self.stage, self.manifest, out)
        self.assertFalse(out.exists())
        self.assertFalse(list(self.root.glob(".changed-stage-candidate-*")))

    def test_rejects_changed_baseline_bytes_after_admission(self):
        original = update.tempfile.mkdtemp

        def change_after_admission(*args, **kwargs):
            write(self.base / "app.mjs", b"concurrently replaced reader")
            return original(*args, **kwargs)

        out = self.root / "changed-base-candidate"
        with patch.object(update.tempfile, "mkdtemp", side_effect=change_after_admission):
            with self.assertRaises(ValueError):
                update.assemble(self.base, self.stage, self.manifest, out)
        self.assertFalse(out.exists())

    def test_rejects_new_baseline_file_after_admission(self):
        original = update.tempfile.mkdtemp

        def change_after_admission(*args, **kwargs):
            write(self.base / "unadmitted-fixture.json", {"synthetic": True})
            return original(*args, **kwargs)

        out = self.root / "changed-file-set-candidate"
        with patch.object(update.tempfile, "mkdtemp", side_effect=change_after_admission):
            with self.assertRaises(ValueError):
                update.assemble(self.base, self.stage, self.manifest, out)
        self.assertFalse(out.exists())

    def test_rejects_baseline_symlink_introduced_after_admission(self):
        original = update.tempfile.mkdtemp
        outside = self.root / "outside-synthetic.txt"
        outside.write_bytes(b"synthetic local evidence")

        def change_after_admission(*args, **kwargs):
            reader = self.base / "app.mjs"
            reader.unlink()
            reader.symlink_to(outside)
            return original(*args, **kwargs)

        out = self.root / "changed-link-candidate"
        with patch.object(update.tempfile, "mkdtemp", side_effect=change_after_admission):
            with self.assertRaisesRegex(ValueError, "Symlink"):
                update.assemble(self.base, self.stage, self.manifest, out)
        self.assertFalse(out.exists())
        self.assertFalse(list(self.root.glob(".changed-link-candidate-*")))

    def test_rejects_changed_asset_and_keeps_output_absent(self) -> None:
        write(self.stage / "media/new-week/zh-Hans.mp3", b"different audio")
        out = self.root / "candidate"
        with self.assertRaisesRegex(ValueError, "changed asset"):
            update.assemble(self.base, self.stage, self.manifest, out)
        self.assertFalse(out.exists())

    def test_rejects_existing_page_identity(self) -> None:
        changed = catalog(copy.deepcopy(self.old_page))
        write(self.stage / update.CATALOG, changed)
        with self.assertRaisesRegex(ValueError, "Existing page ID"):
            update.assemble(self.base, self.stage, self.manifest, self.root / "candidate")

    def test_rejects_missing_english_reference(self) -> None:
        (self.stage / "english-reference/new-week.json").unlink()
        self.write_manifest()
        with self.assertRaises((FileNotFoundError, ValueError)):
            update.assemble(self.base, self.stage, self.manifest, self.root / "candidate")

    def test_rejects_unlisted_extra_file(self) -> None:
        write(self.stage / "pages/new-week/private.json", b"secret")
        with self.assertRaisesRegex(ValueError, "manifest differs"):
            update.assemble(self.base, self.stage, self.manifest, self.root / "candidate")

    def test_rejects_listed_duplicate_audio_alias(self) -> None:
        write(self.stage / "media/new-week/spoken/zh-Hans-copy.mp3",
              (self.stage / "media/new-week/zh-Hans.mp3").read_bytes())
        self.write_manifest()
        with self.assertRaisesRegex(ValueError, "exactly 21 assets"):
            update.assemble(self.base, self.stage, self.manifest, self.root / "candidate")

    def test_rejects_missing_fingerprint(self) -> None:
        index = self.new_page["targets"]["ko"]["audioFingerprint"]["indexUrl"]
        (self.stage / index.lstrip("/")).unlink()
        self.write_manifest()
        with self.assertRaisesRegex(ValueError, "exactly 21 assets"):
            update.assemble(self.base, self.stage, self.manifest, self.root / "candidate")

    def test_rejects_v1_stage_manifest(self) -> None:
        manifest = update.load(self.manifest)
        manifest["schemaVersion"] = "sermon-multilingual-v3-stage-manifest-v1"
        write(self.manifest, manifest)
        with self.assertRaisesRegex(ValueError, "supported three-locale file contract"):
            update.assemble(self.base, self.stage, self.manifest, self.root / "candidate")

    def test_single_chinese_profile_preserves_all_prior_languages(self) -> None:
        for locale in ("ko", "es"):
            binding = self.new_page["targets"].pop(locale)["audioFingerprint"]
            for name in (f"pages/new-week/{locale}/index.html",
                         f"content/new-week/{locale}.json", f"captions/new-week/{locale}.json",
                         f"media/new-week/{locale}.mp3", f"releases-v2/new-week/{locale}.json",
                         binding["indexUrl"].lstrip("/")):
                (self.stage / name).unlink()
        for folder in ("english-reference", "alignment"):
            path = self.stage / f"{folder}/new-week.json"
            sidecar = update.load(path)
            sidecar["targets"] = {"zh-Hans": sidecar["targets"]["zh-Hans"]}
            write(path, sidecar)
        write(self.stage / update.CATALOG, catalog(self.new_page))
        self.write_manifest()
        manifest = update.load(self.manifest)
        manifest["schemaVersion"] = update.SINGLE_STAGE_SCHEMA
        manifest["profile"] = update.SINGLE_PROFILE
        write(self.manifest, manifest)
        out = self.root / "single-candidate"
        report = update.assemble(self.base, self.stage, self.manifest, out)
        self.assertEqual(report["addedFileCount"], 9)
        self.assertEqual(report["publicationProfile"], update.SINGLE_PROFILE)
        pages = update.load(out / "public" / update.CATALOG)["pages"]
        self.assertEqual(set(pages[0]["targets"]), {"zh-Hans"})
        self.assertEqual(set(pages[1]["targets"]), {"zh-Hans", "ko", "es"})
        for name, path in update.regular_files(self.base).items():
            if name != update.CATALOG:
                self.assertEqual(update.digest(out / "public" / name), update.digest(path))
        video = self.stage / "pages/new-week/full-video-browser.mp4"
        delivery = {
            "schemaVersion": "sermon-video-delivery-v1",
            "canonicalUrl": "/pages/new-week/full-video-browser.mp4",
            "storageUrl": f"https://storage.googleapis.com/ai-for-god-sermon-media-prod/weekly/new-week/{update.digest(video)}.mp4",
            "sha256": update.digest(video), "bytes": video.stat().st_size,
        }
        video_copy = self.root / "single-video.mp4"
        video.rename(video_copy)
        self.new_page["videoDelivery"] = delivery
        write(self.stage / update.CATALOG, catalog(self.new_page))
        manifest["profile"] = update.SINGLE_BUCKET_PROFILE
        manifest["videoDelivery"] = delivery
        manifest["files"] = [entry for entry in manifest["files"]
                             if entry["path"] != delivery["canonicalUrl"]]
        write(self.manifest, manifest)
        config = self.root / "single-firebase.json"
        write(config, {"hosting": {"public": "public", "site": "prod",
                              "headers": [{"source": "**", "headers": [{
                                  "key": "Content-Security-Policy",
                                  "value": "default-src 'none'; media-src 'self' blob:;"
                              }]}]}})
        bucket_report = update.assemble(self.base, self.stage, self.manifest,
                                        self.root / "single-bucket", video_copy, config)
        self.assertEqual(bucket_report["addedFileCount"], 8)
        self.assertEqual(bucket_report["weeklyFirebaseObjectCount"], 10)
        manifest["profile"] = update.PUBLICATION_PROFILE
        manifest["schemaVersion"] = update.STAGE_SCHEMA
        write(self.manifest, manifest)
        with self.assertRaisesRegex(ValueError, "exact locales"):
            update.assemble(self.base, self.stage, self.manifest, self.root / "rejected")

    def test_bucket_profile_keeps_video_out_of_hosting(self) -> None:
        video = self.stage / "pages/new-week/full-video-browser.mp4"
        delivery = {
            "schemaVersion": "sermon-video-delivery-v1",
            "canonicalUrl": "/pages/new-week/full-video-browser.mp4",
            "storageUrl": f"https://storage.googleapis.com/ai-for-god-sermon-media-prod/weekly/new-week/{update.digest(video)}.mp4",
            "sha256": update.digest(video), "bytes": video.stat().st_size,
        }
        self.new_page["videoDelivery"] = delivery
        write(self.stage / update.CATALOG, catalog(self.new_page))
        for locale in ("zh-Hans", "ko", "es"):
            content_path = self.stage / f"content/new-week/{locale}.json"
            content = update.load(content_path)
            content["sourceVideoUrl"] = delivery["canonicalUrl"]
            new_sha = write(content_path, content)
            release_path = self.stage / f"releases-v2/new-week/{locale}.json"
            release = update.load(release_path)
            next(asset for asset in release["assets"] if asset["role"] == "content")["sha256"] = new_sha
            release_sha = write(release_path, release)
            self.new_page["targets"][locale]["releasePackageJsonSha256"] = release_sha
            for folder in ("english-reference", "alignment"):
                sidecar_path = self.stage / f"{folder}/new-week.json"
                sidecar = update.load(sidecar_path)
                sidecar["targets"][locale]["releasePackageJsonSha256"] = release_sha
                if folder == "english-reference":
                    sidecar["targets"][locale]["contentSha256"] = new_sha
                write(sidecar_path, sidecar)
        write(self.stage / update.CATALOG, catalog(self.new_page))
        video_copy = self.root / "video.mp4"
        video.rename(video_copy)
        write(self.manifest, {
            "schemaVersion": update.BUCKET_STAGE_SCHEMA,
            "profile": update.BUCKET_PROFILE,
            "pageId": "new-week", "videoDelivery": delivery,
            "files": [{"path": "/" + name, "sha256": update.digest(path)}
                      for name, path in sorted(update.regular_files(self.stage).items())
                      if name != update.CATALOG],
        })
        config = self.root / "firebase.json"
        write(config, {"hosting": {"public": "public", "site": "prod",
                              "headers": [{"source": "**", "headers": [{
                                  "key": "Content-Security-Policy",
                                  "value": "default-src 'none'; media-src 'self' blob:;"
                              }]}]}})
        out = self.root / "bucket-candidate"
        report = update.assemble(self.base, self.stage, self.manifest, out, video_copy,
                                 config)
        self.assertEqual(report["addedFileCount"], 20)
        self.assertEqual(report["weeklyFileCount"], 21)
        self.assertEqual(report["bucketObjectCount"], 1)
        self.assertEqual(report["weeklyFirebaseObjectCount"], 22)
        self.assertFalse((out / "public/pages/new-week/full-video-browser.mp4").exists())
        self.assertEqual(update.load(out / "firebase.json")["hosting"]["redirects"], [{
            "source": delivery["canonicalUrl"],
            "destination": delivery["storageUrl"], "type": 302,
        }])
        with self.assertRaisesRegex(ValueError, "Bucket video file missing or changed"):
            update.assemble(self.base, self.stage, self.manifest,
                            self.root / "missing-video", self.root / "wrong.mp4", config)

    def test_rejects_client_unsupported_locale(self) -> None:
        candidate = catalog(copy.deepcopy(self.new_page))
        candidate["pages"][0]["targets"]["vi"] = candidate["pages"][0]["targets"].pop("zh-Hans")
        candidate["pages"][0]["defaultTargetLocale"] = "vi"
        write(self.stage / update.CATALOG, candidate)
        with self.assertRaisesRegex(ValueError, "Current Production weekly profile requires"):
            update.assemble(self.base, self.stage, self.manifest, self.root / "candidate")


if __name__ == "__main__":
    unittest.main()
