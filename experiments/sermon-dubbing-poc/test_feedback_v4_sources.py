"""Feedback sources for four-layer (v4) pages, bound to a sealed snapshot's bytes."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import deploy_feedback as deploy
from poc import sha256, write_json
from test_feedback_rollout import release_fixture

PAGE = "resi-20261011-54475d42"


def v4_snapshot_fixture(root, name="sealed", audio=b"dubbed audio", locales=("zh-Hans", "ko")):
    snapshot = root / name
    public = snapshot / "public"
    targets = {}
    for locale in locales:
        digest = hashlib.sha256(audio + locale.encode()).hexdigest()
        paths = {"page": f"/pages/{PAGE}/{locale}/index.html", "content": f"/content/{PAGE}/{locale}.json",
                 "audio": f"/media/{PAGE}/{locale}.mp3", "captions": f"/captions/{PAGE}/{locale}.json"}
        (public / paths["audio"].lstrip("/")).parent.mkdir(parents=True, exist_ok=True)
        (public / paths["audio"].lstrip("/")).write_bytes(audio + locale.encode())
        (public / paths["page"].lstrip("/")).parent.mkdir(parents=True, exist_ok=True)
        (public / paths["page"].lstrip("/")).write_text("<p>page</p>")
        write_json(public / paths["content"].lstrip("/"), {"pageId": PAGE, "targetLocale": locale,
                   "durationSeconds": 2131.0, "audioDurationSeconds": 2165.5})
        write_json(public / paths["captions"].lstrip("/"), {"cues": [
            {"textGroupId": "translation-chunk-0000-u001", "text": "first", "start": 5.47, "end": 8.38},
            {"textGroupId": "translation-chunk-0000-u002", "text": "second", "start": 8.38, "end": 11.66}]})
        assets = [{"role": role, "path": path, "sha256": sha256(public / path.lstrip("/"))} for role, path in paths.items()]
        release = {"schemaVersion": "sermon-target-language-release-package-v4", "pageId": PAGE, "targetLocale": locale,
                   "audioLocale": locale, "contentStatus": "machine_checked", "audioStatus": "machine_checked", "assets": assets}
        release_path = public / f"releases-v4/{PAGE}/{locale}.json"
        write_json(release_path, release)
        targets[locale] = {"capabilities": ["text", "captions", "audio"], "contentStatus": "machine_checked",
                           "audioStatus": "machine_checked", "releasePackageUrl": f"/releases-v4/{PAGE}/{locale}.json",
                           "releasePackageJsonSha256": sha256(release_path)}
    targets["en"] = {"capabilities": ["text"], "releasePackageUrl": "/releases-v4/x/en.json", "releasePackageJsonSha256": "0" * 64}
    write_json(public / "multilingual-v4.json", {"schemaVersion": "sermon-multilingual-catalog-v4", "defaultPageId": PAGE,
               "pages": [{"id": PAGE, "date": "2026-10-11", "defaultTargetLocale": "zh-Hans", "targets": targets}]})
    write_json(snapshot / "seal-report.json", {"schemaVersion": "sermon-seal-report-fixture", "catalogSha256": "f" * 64})
    return snapshot


class V4FeedbackSourceTests(unittest.TestCase):
    def test_sources_follow_the_reader_track_identity_and_caption_cues(self):
        with tempfile.TemporaryDirectory() as directory:
            snapshot = v4_snapshot_fixture(Path(directory))
            sources = deploy.v4_feedback_sources(snapshot / "public")
            self.assertEqual([source["audioLocale"] for source in sources], ["ko", "zh-Hans"])  # text-only en is skipped
            source = next(item for item in sources if item["audioLocale"] == "zh-Hans")
            digest = sha256(snapshot / "public/media" / PAGE / "zh-Hans.mp3")
            self.assertEqual(source["trackId"], f"{PAGE}-zh-Hans-{digest[:12]}")
            self.assertEqual((source["week"], source["audioSha256"], source["pageId"]), ("2026-10-11", digest, PAGE))
            self.assertEqual(source["durationSeconds"], 2165.5)  # the dub clock, not the source window
            self.assertEqual(source["cueIds"], ["0", "1"])
            self.assertEqual(source["blockIds"], ["translation-chunk-0000-u001", "translation-chunk-0000-u002"])
            self.assertEqual(source["cues"][1], {"id": "1", "start": 8.38, "end": 11.66, "blockId": "translation-chunk-0000-u002"})

    def test_changed_public_bytes_or_identity_are_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            snapshot = v4_snapshot_fixture(Path(directory))
            public = snapshot / "public"
            audio = public / "media" / PAGE / "zh-Hans.mp3"
            original = audio.read_bytes()
            audio.write_bytes(original + b"!")
            with self.assertRaisesRegex(ValueError, "not a verified public release file"):
                deploy.v4_feedback_sources(public)
            audio.write_bytes(original)
            release_path = public / f"releases-v4/{PAGE}/zh-Hans.json"
            release = json.loads(release_path.read_text())
            release["audioLocale"] = "ko"
            write_json(release_path, release)
            catalog = json.loads((public / "multilingual-v4.json").read_text())
            catalog["pages"][0]["targets"]["zh-Hans"]["releasePackageJsonSha256"] = sha256(release_path)
            with self.assertRaisesRegex(ValueError, "identity differs"):
                deploy.v4_feedback_sources(public, catalog)
            captions = public / f"captions/{PAGE}/ko.json"
            write_json(captions, {"cues": [{"textGroupId": "g", "text": "x", "start": 0, "end": 99999}]})
            with self.assertRaisesRegex(ValueError, "not a verified public release file"):
                deploy.v4_feedback_sources(public)

    def test_merge_adds_v4_sources_beside_the_legacy_release(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            legacy = release_fixture(root, "legacy")
            snapshot = v4_snapshot_fixture(root)
            with patch.object(deploy, "validate_catalog_snapshot", lambda path: None):
                catalog, current, compatible, snapshots, runtimes = deploy.merge_catalogs(legacy, [], [snapshot])
            self.assertEqual(len(catalog["sources"]), 3)
            self.assertEqual((compatible, runtimes), ([], []))
            self.assertEqual(snapshots[0]["addedSourceCount"], 2)
            self.assertEqual(snapshots[0]["sealReportSha256"], sha256(snapshot / "seal-report.json"))
            self.assertEqual(snapshots[0]["catalogV4Sha256"], sha256(snapshot / "public/multilingual-v4.json"))
            # The legacy catalog carries no usage allowlists, so none are invented.
            self.assertNotIn("weekIds", catalog)
            # Prepare writes the merged runtime catalog and records the snapshot.
            with patch.object(deploy, "validate_catalog_snapshot", lambda path: None):
                manifest = deploy.prepare(legacy, root / "api", [], [snapshot])
            runtime = json.loads((root / "api/catalog.json").read_text())
            self.assertEqual(len(runtime["sources"]), 3)
            self.assertEqual(manifest["fourLayerSnapshots"][0]["addedSourceCount"], 2)
            self.assertEqual(manifest["runtimeSourceCount"], 3)

    def test_previous_runtime_keeps_deployed_sources_without_a_legacy_release(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            legacy = release_fixture(root, "legacy")
            snapshot = v4_snapshot_fixture(root)
            with patch.object(deploy, "validate_catalog_snapshot", lambda path: None):
                first = deploy.prepare(legacy, root / "api-1", [], [snapshot])
                # Next week: the old listening release may no longer verify with
                # today's verifier, so the deployed runtime carries its sources on.
                manifest = deploy.prepare(None, root / "api-2", [], [snapshot], [root / "api-1"])
            self.assertIsNone(manifest["releaseBuildSha256"])
            self.assertEqual(manifest["currentSourceCount"], 0)
            self.assertEqual(manifest["runtimeSourceCount"], 3)
            self.assertEqual(manifest["previousRuntimes"][0]["runtimeCatalogSha256"], first["runtimeCatalogSha256"])
            self.assertEqual(manifest["previousRuntimes"][0]["addedSourceCount"], 3)
            self.assertEqual(manifest["fourLayerSnapshots"][0]["addedSourceCount"], 0)  # already present
            catalog_path = root / "api-1/catalog.json"
            catalog_path.write_text(catalog_path.read_text() + " ")
            with self.assertRaisesRegex(ValueError, "differs from its source manifest"):
                deploy.verified_runtime_catalog(root / "api-1")
            with self.assertRaisesRegex(ValueError, "would be empty"):
                deploy.merge_catalogs(None)

    def test_v4_snapshot_is_validated_as_a_sealed_snapshot(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            legacy = release_fixture(root, "legacy")
            snapshot = v4_snapshot_fixture(root)
            # The fixture is not a real sealed snapshot, so the contract check must refuse it.
            with self.assertRaises(Exception):
                deploy.merge_catalogs(legacy, [], [snapshot])


if __name__ == "__main__":
    unittest.main()
