"""Local release/registry regressions; fixture MP3s are inert bytes, never audio."""
import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import weekly_release as release


ORIGIN = "https://fixture.example"


def write_json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def week(date, source, *, title=None, legacy=False, media_version="v1"):
    content = f"inert-fixture:{date}:{source}:{media_version}".encode()
    digest = hashlib.sha256(content).hexdigest()
    filename = digest[:16] + "-zh-natural.mp3"
    page = {
        "id": date if legacy else f"{date}-archive_caption-{source}",
        "date": date, "sourceId": source, "sourceRoute": "archive_caption",
        "title": title or f"Fixture {source}", "speaker": "Fixture speaker", "outline": ["Fixture outline"],
        "audioStatus": "full_reviewed",
        "tracks": [{"id": f"track-{source}", "file": filename, "audioUrl": "/media/" + filename,
                    "sha256": digest, "durationSeconds": 2,
                    "cues": [{"start": 0, "end": 2, "text": "Fixture subtitle", "blockId": "b1"}]}],
    }
    return page, {"media/" + filename: content}


def release_fixture(path, pages, *, ui="registered UI", feedback=False):
    path = Path(path)
    public = path / "public"
    public.mkdir(parents=True)
    catalog = {"schemaVersion": "sermon-weekly-catalog-v1", "defaultWeekId": pages[0][0]["id"],
               "weeks": [copy.deepcopy(item[0]) for item in pages], "fixtureSetting": "preserve-base"}
    (public / "index.html").write_text(ui)
    (public / "app.mjs").write_text("export const fixture = " + json.dumps(ui) + ";\n")
    write_json(public / "engagement.json", {"enabled": feedback, "fixtureSetting": ui})
    write_json(public / "weekly.json", catalog)
    for _, media in pages:
        for name, content in media.items():
            target = public / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
    report = {"schemaVersion": "sermon-weekly-build-v1", "builtAt": "2026-09-01T12:00:00Z",
              "weeks": len(pages), "playableWeeks": len(pages), "trainingDataPublished": False,
              "feedbackEnabled": feedback, "sources": [], "reviewPreview": False,
              "syncPreview": False, "includeHistory": False, "appVersion": ui,
              "originalAudioPublished": False}
    write_json(path / "build-report.json", report)
    refresh_manifest(path)
    return path


def refresh_manifest(path):
    path = Path(path)
    report = json.loads((path / "build-report.json").read_text())
    catalog = json.loads((path / "public/weekly.json").read_text())
    report.update(weeks=len(catalog["weeks"]), playableWeeks=sum(bool(w["tracks"]) for w in catalog["weeks"]))
    report["files"] = [{"path": str(p.relative_to(path / "public")), "bytes": p.stat().st_size,
                        "sha256": release.sha256(p)} for p in sorted((path / "public").rglob("*")) if p.is_file()]
    report["totalBytes"] = sum(item["bytes"] for item in report["files"])
    if report.get("feedbackEnabled"):
        write_json(path / "feedback-catalog.json", release.feedback_catalog(catalog))
        report["feedbackCatalogSha256"] = release.sha256(path / "feedback-catalog.json")
    write_json(path / "build-report.json", report)


def page_with_downloads_and_fingerprint(date, source, *, media_version="v1"):
    """Source-stable, inert downloads and numeric index; never real audio."""
    source_hash = hashlib.sha256(source.encode()).hexdigest()
    page, assets = week(date, "source-" + source_hash[:16], media_version=media_version)
    page.update(sourceRoute="same_video", id=f"{date}-same_video-{page['sourceId']}",
                sourceStartSeconds=5, sourceEndSeconds=7)
    page["downloads"] = {}
    for kind, extension in (("readingPdf", "pdf"), ("companionPdf", "pdf"),
                            ("fullVideoMp3", "mp3"), ("fullVideoSrt", "srt")):
        data = f"inert:{source}:{media_version}:{kind}".encode()
        name = f"downloads/{hashlib.sha256(data).hexdigest()[:16]}-{kind}.{extension}"
        assets[name] = data
        page["downloads"][kind] = "/" + name
    index = {"schemaVersion": "sermon-landmark-index-v1", "algorithmVersion": "spectral-landmarks-v1",
        "sampleRate": 8000, "hopSize": 256, "fftSize": 1024, "sourceSha256": source_hash,
        "trackSha256": page["tracks"][0]["sha256"], "pageId": page["id"],
        "sourceStartSeconds": 5, "sourceEndSeconds": 7, "window": {"startSeconds": 5, "endSeconds": 7},
        "durationSeconds": 2, "landmarkCount": 3, "postings": {"123": [1, 4, 8]}}
    raw = json.dumps(index).encode()
    digest = hashlib.sha256(raw).hexdigest()
    name = "fingerprints/" + digest[:16] + "-landmarks.json"
    assets[name] = raw
    binding = {k: index[k] for k in ("pageId", "algorithmVersion", "sourceSha256", "trackSha256",
                                   "sourceStartSeconds", "sourceEndSeconds")}
    page["audioFingerprint"] = {**binding, "schemaVersion": "sermon-audio-fingerprint-binding-v1",
        "captureSeconds": 10, "indexUrl": "/" + name, "indexSha256": digest}
    from deploy_firebase import FINGERPRINT_UI
    for name in FINGERPRINT_UI:
        assets[name] = b"// inert registered fingerprint fixture"
    return page, assets


def verification(path):
    path = Path(path)
    report = json.loads((path / "build-report.json").read_text())
    checked = [{"path": item["path"], "passed": True, "httpStatus": 200,
                "expectedSha256": item["sha256"], "observedSha256": item["sha256"],
                "expectedBytes": item["bytes"], "receivedBytes": item["bytes"]} for item in report["files"]]
    ranges = []
    for item in report["files"]:
        if not item["path"].endswith(".mp3"):
            continue
        size = item["bytes"]
        prefix = (path / "public" / item["path"]).read_bytes()[:1024]
        digest = hashlib.sha256(prefix).hexdigest()
        ranges.append({"path": item["path"], "passed": True, "httpStatus": 206,
                       "contentRange": f"bytes 0-{len(prefix)-1}/{size}",
                       "expectedSha256": digest, "observedSha256": digest,
                       "expectedBytes": len(prefix), "receivedBytes": len(prefix)})
    return {"passed": True, "origin": ORIGIN, "buildReportSha256": release.sha256(path / "build-report.json"),
            "expectedFileCount": len(checked), "checkedFileCount": len(checked),
            "checkedFiles": checked, "audioRanges": ranges}


class WeeklyReleaseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.old_pages = [week("2026-08-30", "oldB"), week("2026-08-23", "oldA")]
        self.base = release_fixture(self.root / "base", self.old_pages)
        self.registry = self.root / "registry"

    def bootstrap(self):
        return release.bootstrap(self.registry, self.base, ORIGIN)

    def prepare_new(self, *, name="new", date="2026-09-06", source="newC"):
        candidate = release_fixture(self.root / name, [week(date, source)], ui="candidate UI")
        out = self.root / (name + "-prepared")
        plan = release.prepare(self.registry, candidate, out)
        return out, plan

    def catalog(self, path):
        return json.loads((Path(path) / "public/weekly.json").read_text())

    def registry_bytes(self):
        return (self.registry / "registry.json").read_bytes()

    def test_read_release_accepts_complete_bound_local_fixture(self):
        report, catalog = release.read_release(self.base)
        self.assertEqual(report["weeks"], 2)
        self.assertEqual(catalog["weeks"], [x[0] for x in self.old_pages])

    def test_changed_file_hash_and_unknown_public_file_are_rejected(self):
        (self.base / "public/index.html").write_text("tampered bytes")
        with self.assertRaises(ValueError):
            release.read_release(self.base)
        refresh_manifest(self.base)
        (self.base / "public/private-training.wav").write_bytes(b"not audio")
        with self.assertRaises(ValueError):
            release.read_release(self.base)
        refresh_manifest(self.base)
        with self.assertRaises(ValueError):
            release.read_release(self.base)

    def test_manifest_rejects_unsafe_paths_and_duplicate_files(self):
        original = json.loads((self.base / "build-report.json").read_text())
        for name in ("../outside.mp3", "/tmp/outside.mp3", "media/../outside.mp3", "media\\outside.mp3", ".private"):
            with self.subTest(path=name):
                report = copy.deepcopy(original)
                report["files"][0]["path"] = name
                write_json(self.base / "build-report.json", report)
                with self.assertRaises(ValueError):
                    release.read_release(self.base)
        report = copy.deepcopy(original)
        report["files"].append(copy.deepcopy(report["files"][0]))
        write_json(self.base / "build-report.json", report)
        with self.assertRaises(ValueError):
            release.read_release(self.base)

    def test_release_public_and_file_symlinks_are_rejected(self):
        alias = self.root / "release-link"
        alias.symlink_to(self.base, target_is_directory=True)
        with self.assertRaises(ValueError):
            release.read_release(alias)
        index = self.base / "public/index.html"
        external = self.root / "outside-index.html"
        external.write_bytes(index.read_bytes())
        index.unlink()
        index.symlink_to(external)
        with self.assertRaises(ValueError):
            release.read_release(self.base)
        index.unlink()
        index.write_bytes(external.read_bytes())
        public = self.base / "public"
        public.rename(self.base / "real-public")
        public.symlink_to(self.base / "real-public", target_is_directory=True)
        with self.assertRaises(ValueError):
            release.read_release(self.base)

    def test_catalog_audio_hash_and_source_identity_are_bound(self):
        original = self.catalog(self.base)
        bad = copy.deepcopy(original)
        bad["weeks"][0]["tracks"][0]["sha256"] = "f" * 64
        write_json(self.base / "public/weekly.json", bad)
        refresh_manifest(self.base)
        with self.assertRaisesRegex(ValueError, "audio is not bound"):
            release.read_release(self.base)
        bad = copy.deepcopy(original)
        bad["weeks"][0]["sourceId"] = "different-source"
        write_json(self.base / "public/weekly.json", bad)
        refresh_manifest(self.base)
        with self.assertRaisesRegex(ValueError, "source identity"):
            release.read_release(self.base)

    def test_bootstrap_copies_an_immutable_baseline_and_never_overwrites_registry(self):
        state = self.bootstrap()
        saved = self.registry / "releases" / state["head"]
        before = self.registry_bytes()
        self.assertEqual(self.catalog(saved), self.catalog(self.base))
        with self.assertRaisesRegex(ValueError, "already initialized"):
            self.bootstrap()
        self.assertEqual(before, self.registry_bytes())
        (self.base / "public/index.html").write_text("source changed later")
        self.assertEqual((saved / "public/index.html").read_text(), "registered UI")

    def test_prepare_adds_one_week_and_preserves_old_pages_ui_settings_and_head(self):
        state = self.bootstrap()
        before = self.registry_bytes()
        out, plan = self.prepare_new()
        catalog = self.catalog(out)
        self.assertEqual(len(catalog["weeks"]), 3)
        by_id = {w["id"]: w for w in catalog["weeks"]}
        for page, _ in self.old_pages:
            self.assertEqual(by_id[page["id"]], page)
        self.assertEqual(plan["changes"]["unchanged"], sorted(x[0]["id"] for x in self.old_pages))
        self.assertEqual(len(plan["changes"]["added"]), 1)
        self.assertEqual(plan["changes"]["removed"], [])
        self.assertEqual(plan["parentReleaseId"], state["head"])
        self.assertFalse(plan["workflowComplete"])
        for name in ("index.html", "app.mjs", "engagement.json"):
            self.assertEqual((out / "public" / name).read_bytes(), (self.base / "public" / name).read_bytes())
        self.assertEqual(catalog["fixtureSetting"], "preserve-base")
        self.assertEqual(before, self.registry_bytes())
        self.assertEqual(len(list((out / "public/media").iterdir())), 3)

    def test_prepare_same_date_different_source_remains_a_separate_page(self):
        self.bootstrap()
        out, plan = self.prepare_new(date="2026-08-30", source="alternate")
        same_date = [w for w in self.catalog(out)["weeks"] if w["date"] == "2026-08-30"]
        self.assertEqual({w["sourceId"] for w in same_date}, {"oldB", "alternate"})
        self.assertEqual(len(plan["changes"]["added"]), 1)
        self.assertEqual(plan["changes"]["updated"], [])

    def test_prepare_same_id_replaces_content_while_preserving_prior_release(self):
        state = self.bootstrap()
        changed = week("2026-08-30", "oldB", title="Reviewed revision", media_version="v2")
        candidate = release_fixture(self.root / "revision", [changed])
        out = self.root / "revised"
        with self.assertRaises(ValueError):
            release.prepare(self.registry, candidate, out)
        self.assertFalse(out.exists())
        plan = release.prepare(self.registry, candidate, out, replace_ids=[changed[0]["id"]])
        self.assertEqual(plan["changes"]["updated"], [changed[0]["id"]])
        self.assertEqual(plan["changes"]["added"], [])
        self.assertEqual(len(self.catalog(out)["weeks"]), 2)
        self.assertEqual(self.catalog(out)["weeks"][0]["title"], "Reviewed revision")
        previous = self.registry / "releases" / state["head"]
        self.assertEqual(self.catalog(previous)["weeks"][0]["title"], "Fixture oldB")

    def test_replacement_prunes_only_unreferenced_downloads_indexes_from_new_output(self):
        old_page, old_assets = page_with_downloads_and_fingerprint("2026-09-13", "current")
        other_page, other_assets = page_with_downloads_and_fingerprint("2026-09-06", "other")
        # A file previously attached to the replaced page is also still used by
        # another page: cleanup must preserve references across the full catalog.
        del other_assets[other_page["downloads"]["readingPdf"][1:]]
        shared = old_page["downloads"]["readingPdf"]
        other_page["downloads"]["readingPdf"] = shared
        base = release_fixture(self.root / "asset-base", [(old_page, old_assets), (other_page, other_assets)])
        registry = self.root / "asset-registry"
        state = release.bootstrap(registry, base, ORIGIN)
        new_page, new_assets = page_with_downloads_and_fingerprint("2026-09-13", "current", media_version="v2")
        new_page.update(humanApproval=False, audioStatus="full_candidate", videoSynchronization="candidate_aligned")
        candidate = release_fixture(self.root / "asset-revision", [(new_page, new_assets)])
        def tree(path):
            return {str(p.relative_to(path)): p.read_bytes() for p in path.rglob("*") if p.is_file()}
        before = {path: tree(path) for path in (base, registry, candidate)}
        out = self.root / "asset-merged"
        plan = release.prepare(registry, candidate, out, replace_ids=[new_page["id"]])
        report, catalog = release.read_release(out)
        by_id = {w["id"]: w for w in catalog["weeks"]}
        self.assertEqual(by_id, {new_page["id"]: new_page, other_page["id"]: other_page})
        self.assertFalse(by_id[new_page["id"]]["humanApproval"])
        self.assertEqual(plan["changes"], {"added": [], "updated": [new_page["id"]],
            "unchanged": [other_page["id"]], "removed": []})
        removed = {url[1:] for key, url in old_page["downloads"].items() if key != "readingPdf"}
        removed.add(old_page["audioFingerprint"]["indexUrl"][1:])
        self.assertEqual(set(report["releaseRegistry"]["prunedUnreferencedAssets"]), removed)
        for name in removed:
            self.assertFalse((out / "public" / name).exists())
        for name, content in {**other_assets, **new_assets, shared[1:]: old_assets[shared[1:]]}.items():
            self.assertEqual((out / "public" / name).read_bytes(), content)
        self.assertEqual((out / "public/index.html").read_bytes(), (base / "public/index.html").read_bytes())
        for path, expected in before.items():
            self.assertEqual(tree(path), expected, f"Source release or registry mutated: {path}")
        self.assertEqual(read_json := json.loads((registry / "registry.json").read_text()),
                         json.loads(before[registry]["registry.json"]))
        self.assertEqual(read_json["head"], state["head"])

    def test_staging_cleanup_rejects_bad_reference_or_symlink_before_deletion(self):
        public = self.base / "public"
        downloads = public / "downloads"
        downloads.mkdir()
        orphan = downloads / "orphan.pdf"
        orphan.write_bytes(b"inert orphan in output")
        bad = self.catalog(self.base)
        bad["weeks"][0]["downloads"] = {"readingPdf": "/downloads/../outside.pdf"}
        with self.assertRaises(ValueError):
            release.prune_unreferenced_assets(public, bad)
        self.assertEqual(orphan.read_bytes(), b"inert orphan in output")
        target = self.root / "outside.pdf"
        target.write_bytes(b"outside must remain")
        (downloads / "alias.pdf").symlink_to(target)
        with self.assertRaises(ValueError):
            release.prune_unreferenced_assets(public, self.catalog(self.base))
        self.assertEqual(orphan.read_bytes(), b"inert orphan in output")
        self.assertEqual(target.read_bytes(), b"outside must remain")

    def test_include_history_placeholder_cannot_erase_a_playable_registered_page(self):
        self.bootstrap()
        placeholder = copy.deepcopy(self.old_pages[0][0])
        placeholder.update(tracks=[], audioStatus="not_available", title="Historical placeholder")
        candidate = release_fixture(
            self.root / "history-placeholder",
            [week("2026-09-06", "newC"), (placeholder, {})],
        )
        report = json.loads((candidate / "build-report.json").read_text())
        report["includeHistory"] = True
        write_json(candidate / "build-report.json", report)
        release.read_release(candidate)
        before = self.registry_bytes()
        out = self.root / "history-placeholder-prepared"
        with self.assertRaises(ValueError):
            release.prepare(self.registry, candidate, out)
        self.assertFalse(out.exists())
        self.assertEqual(self.registry_bytes(), before)
        _, previous, _, _ = release.load_registry(self.registry)
        self.assertEqual(self.catalog(previous)["weeks"][0]["tracks"], self.old_pages[0][0]["tracks"])

    def test_prepare_rejects_existing_output_without_touching_it(self):
        self.bootstrap()
        out, _ = self.prepare_new()
        before = (out / "build-report.json").read_bytes()
        with self.assertRaisesRegex(ValueError, "new output"):
            release.prepare(self.registry, self.root / "new", out)
        self.assertEqual((out / "build-report.json").read_bytes(), before)

    def test_prepare_rejects_outputs_nested_in_registry_or_candidate(self):
        self.bootstrap()
        candidate = release_fixture(self.root / "candidate-nesting", [week("2026-09-06", "newC")])
        before = self.registry_bytes()
        for out in (self.registry / "nested-output", candidate / "nested-output"):
            with self.subTest(out=out), self.assertRaisesRegex(ValueError, "outside registry and candidate"):
                release.prepare(self.registry, candidate, out)
            self.assertFalse(out.exists())
            self.assertEqual(self.registry_bytes(), before)

    def test_prepare_rejects_source_collision_for_existing_legacy_page(self):
        legacy = release_fixture(self.root / "legacy", [week("2026-08-30", "original", legacy=True)])
        release.bootstrap(self.registry, legacy, ORIGIN)
        candidate = release_fixture(self.root / "collision", [week("2026-08-30", "different", legacy=True)])
        before = self.registry_bytes()
        out = self.root / "collision-output"
        with self.assertRaisesRegex(ValueError, "source identity cannot change"):
            release.prepare(self.registry, candidate, out)
        self.assertFalse(out.exists())
        self.assertEqual(before, self.registry_bytes())

    def test_feedback_catalog_covers_old_and_new_pages_and_keeps_enabled_setting(self):
        enabled = release_fixture(self.root / "enabled", self.old_pages, feedback=True)
        release.bootstrap(self.registry, enabled, ORIGIN)
        out, _ = self.prepare_new()
        report, catalog = release.read_release(out)
        self.assertTrue(report["feedbackEnabled"])
        feedback = json.loads((out / "feedback-catalog.json").read_text())
        expected = {(w["date"], t["id"], t["sha256"]) for w in catalog["weeks"] for t in w["tracks"]}
        actual = {(s["week"], s["trackId"], s["audioSha256"]) for s in feedback["sources"]}
        self.assertEqual(actual, expected)
        self.assertEqual(len(actual), 3)
        self.assertTrue(json.loads((out / "public/engagement.json").read_text())["enabled"])

    def test_candidate_cannot_enable_feedback_on_a_disabled_registered_site(self):
        self.bootstrap()
        candidate = release_fixture(self.root / "enabled-candidate", [week("2026-09-06", "newC")], feedback=True)
        out = self.root / "disabled-merged"
        release.prepare(self.registry, candidate, out)
        report, _ = release.read_release(out)
        self.assertFalse(report["feedbackEnabled"])
        self.assertFalse(json.loads((out / "public/engagement.json").read_text())["enabled"])

    def voice_bank_catalogs(self):
        base = self.catalog(self.base)
        base["voiceBank"] = {"speakers": [{
            "id": "fixture-speaker", "name": "Fixture speaker", "reviewStatus": "human_approved",
            "reference": copy.deepcopy(self.old_pages[0][0]["tracks"][0]),
            "chinese": copy.deepcopy(self.old_pages[1][0]["tracks"][0]),
        }]}
        new_page = week("2026-09-06", "newC")[0]
        candidate = {"schemaVersion": "sermon-weekly-catalog-v1", "defaultWeekId": new_page["id"], "weeks": [new_page]}
        return base, candidate

    def test_candidate_without_voice_bank_preserves_the_registered_bank(self):
        base, candidate = self.voice_bank_catalogs()
        before = copy.deepcopy(base)
        merged, _ = release.merged_catalog(base, candidate)
        self.assertEqual(merged["voiceBank"], before["voiceBank"])
        self.assertEqual(base, before)
        self.assertIsNot(merged["voiceBank"], base["voiceBank"])

    def test_candidate_with_identical_voice_bank_is_accepted(self):
        base, candidate = self.voice_bank_catalogs()
        candidate["voiceBank"] = copy.deepcopy(base["voiceBank"])
        merged, changes = release.merged_catalog(base, candidate)
        self.assertEqual(merged["voiceBank"], base["voiceBank"])
        self.assertEqual(len(changes["added"]), 1)

    def test_same_speaker_review_status_or_audio_change_requires_separate_review(self):
        base, candidate = self.voice_bank_catalogs()
        for change in ("review_status", "reference_audio", "chinese_audio"):
            with self.subTest(change=change):
                revised = copy.deepcopy(candidate)
                revised["voiceBank"] = copy.deepcopy(base["voiceBank"])
                speaker = revised["voiceBank"]["speakers"][0]
                if change == "review_status":
                    speaker["reviewStatus"] = "candidate"
                else:
                    track = week("2026-09-06", "replacement-voice")[0]["tracks"][0]
                    speaker["reference" if change == "reference_audio" else "chinese"] = track
                with self.assertRaisesRegex(ValueError, "voice bank changes"):
                    release.merged_catalog(base, revised)
        self.assertEqual(base["voiceBank"]["speakers"][0]["reviewStatus"], "human_approved")

    def test_weekly_candidate_cannot_introduce_a_new_voice_bank(self):
        base, candidate = self.voice_bank_catalogs()
        candidate["voiceBank"] = base.pop("voiceBank")
        with self.assertRaisesRegex(ValueError, "voice bank changes"):
            release.merged_catalog(base, candidate)

    def test_record_published_advances_once_and_preserves_previous_release(self):
        initial = self.bootstrap()
        out, plan = self.prepare_new()
        receipt = verification(out)
        state = release.record_published(self.registry, out, receipt)
        self.assertEqual(state["head"], plan["releaseId"])
        self.assertEqual(state["generation"], 1)
        self.assertEqual(len(state["history"]), 2)
        previous = self.registry / "releases" / initial["head"]
        release.read_release(previous)
        self.assertEqual(len(self.catalog(previous)["weeks"]), 2)
        before = self.registry_bytes()
        self.assertEqual(release.record_published(self.registry, out, receipt), state)
        self.assertEqual(self.registry_bytes(), before)

    def test_failed_wrong_origin_or_wrong_hash_receipt_never_advances(self):
        self.bootstrap()
        out, _ = self.prepare_new()
        before = self.registry_bytes()
        for patch in ({"passed": False}, {"origin": "https://other.example"}, {"buildReportSha256": "f" * 64}):
            with self.subTest(patch=patch):
                receipt = {**verification(out), **patch}
                with self.assertRaises(ValueError):
                    release.record_published(self.registry, out, receipt)
                self.assertEqual(before, self.registry_bytes())
                self.assertEqual(len(list((self.registry / "releases").iterdir())), 1)

    def test_incomplete_file_or_range_receipts_cannot_advance_registry(self):
        self.bootstrap()
        out, _ = self.prepare_new()
        before = self.registry_bytes()
        for omit in ("checkedFiles", "audioRanges"):
            with self.subTest(omit=omit):
                receipt = verification(out)
                receipt[omit] = []
                with self.assertRaisesRegex(ValueError, "coverage incomplete"):
                    release.record_published(self.registry, out, receipt)
                self.assertEqual(self.registry_bytes(), before)

    def test_same_public_files_with_changed_build_report_get_a_new_revision_id(self):
        report, _ = release.read_release(self.base)
        first = release.release_id(report)
        revised = copy.deepcopy(report)
        revised["builtAt"] = "2026-09-02T12:00:00Z"
        self.assertEqual(revised["files"], report["files"])
        self.assertNotEqual(release.release_id(revised), first)

    def test_prepared_candidate_cannot_advance_after_another_release_wins(self):
        self.bootstrap()
        first, _ = self.prepare_new(name="first", source="first")
        stale, _ = self.prepare_new(name="stale", source="stale")
        release.record_published(self.registry, first, verification(first))
        before = self.registry_bytes()
        with self.assertRaisesRegex(ValueError, "registry advanced"):
            release.record_published(self.registry, stale, verification(stale))
        self.assertEqual(before, self.registry_bytes())

    def test_parent_generation_change_rejects_even_when_head_is_unchanged(self):
        self.bootstrap()
        out, _ = self.prepare_new()
        state = json.loads(self.registry_bytes())
        state["generation"] += 1
        write_json(self.registry / "registry.json", state)
        before = self.registry_bytes()
        with self.assertRaisesRegex(ValueError, "registry advanced"):
            release.record_published(self.registry, out, verification(out))
        self.assertEqual(before, self.registry_bytes())

    def test_forged_plan_parent_cannot_override_a_different_build_report_parent(self):
        state = self.bootstrap()
        out, original_plan = self.prepare_new()
        original_report = json.loads((out / "build-report.json").read_text())
        before = self.registry_bytes()
        for field, wrong_value in (
            ("parentReleaseId", "rel_" + "f" * 24),
            ("parentGeneration", state["generation"] + 1),
        ):
            with self.subTest(field=field):
                report = copy.deepcopy(original_report)
                report["releaseRegistry"][field] = wrong_value
                write_json(out / "build-report.json", report)
                plan = copy.deepcopy(original_plan)
                plan.update(parentReleaseId=state["head"], parentGeneration=state["generation"],
                            releaseId=release.release_id(report),
                            buildReportSha256=release.sha256(out / "build-report.json"))
                write_json(out / "release-plan.json", plan)
                with self.assertRaisesRegex(ValueError, "build report parent"):
                    release.record_published(self.registry, out, verification(out))
                self.assertEqual(self.registry_bytes(), before)
                self.assertEqual(len(list((self.registry / "releases").iterdir())), 1)

    def test_bootstrap_rejects_symlinked_registry_releases_directory(self):
        self.registry.mkdir()
        external = self.root / "outside-releases"
        external.mkdir()
        (self.registry / "releases").symlink_to(external, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "symlink"):
            self.bootstrap()
        self.assertFalse((self.registry / "registry.json").exists())
        self.assertEqual(list(external.iterdir()), [])

    def test_load_registry_rejects_symlinked_releases_without_changing_head(self):
        self.bootstrap()
        before = self.registry_bytes()
        external = self.root / "moved-releases"
        (self.registry / "releases").rename(external)
        (self.registry / "releases").symlink_to(external, target_is_directory=True)
        with self.assertRaises(ValueError):
            release.load_registry(self.registry)
        self.assertEqual(self.registry_bytes(), before)
        self.assertEqual(len(list(external.iterdir())), 1)


if __name__ == "__main__":
    unittest.main()
