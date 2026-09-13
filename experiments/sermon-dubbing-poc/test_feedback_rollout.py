"""Verified old/new catalog rollout; temporary fixtures and an in-memory API store."""
import contextlib
import copy
import hashlib
import io
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import deploy_feedback_compat as deploy
from deploy_feedback import verified_feedback_catalog as verify_standard_catalog, public_week_date
from poc import sha256, write_json



class ArchivePageIdentityTests(unittest.TestCase):
    def test_archive_page_date_requires_exact_bound_identity(self):
        page = {"id": "2026-08-16-archive_caption-A_WNHtupo3Q", "date": "2026-08-16",
                "sourceRoute": "archive_caption", "sourceId": "A_WNHtupo3Q"}
        self.assertEqual(public_week_date(page), "2026-08-16")
        for change in [{"id": "2026-08-16-archive_caption-other"}, {"sourceRoute": "unknown"}, {"date": "2026-08-17"}]:
            with self.subTest(change=change), self.assertRaises(ValueError):
                public_week_date({**page, **change})


def release_fixture(root, name, audio=b"new audio", cue_end=3.0):
    release = root / name
    public = release / "public"
    (public / "media").mkdir(parents=True)
    digest = hashlib.sha256(audio).hexdigest()
    media_name = digest[:16] + "-zh-synced.mp3"
    (public / "media" / media_name).write_bytes(audio)
    (public / "index.html").write_text("<p>Fixture review candidate</p>")
    cues = [{"start": 0.0, "end": cue_end, "blockId": 0, "text": "首句"},
            {"start": 5.0, "end": 8.0, "blockId": 1, "text": "末句"}]
    track = {"id": "full_candidate", "file": media_name, "audioUrl": "/media/" + media_name,
             "sha256": digest, "durationSeconds": 10.0, "cues": cues}
    write_json(public / "weekly.json", {"schemaVersion": "sermon-weekly-catalog-v1",
        "defaultWeekId": "2026-08-30", "weeks": [{"id": "2026-08-30", "tracks": [track], "humanApproval": False}]})
    api_cues = [{"id": str(i), "start": c["start"], "end": c["end"], "blockId": str(c["blockId"])} for i, c in enumerate(cues)]
    source = {"week": "2026-08-30", "trackId": "full_candidate", "audioSha256": digest,
              "durationSeconds": 10.0, "cueIds": ["0", "1"], "blockIds": ["0", "1"], "cues": api_cues}
    write_json(release / "feedback-catalog.json", {"schemaVersion": 1, "sources": [source]})
    refresh_report(release)
    return release


def refresh_report(release):
    public = release / "public"
    files = [{"path": str(p.relative_to(public)), "sha256": sha256(p), "bytes": p.stat().st_size}
             for p in sorted(public.rglob("*")) if p.is_file()]
    write_json(release / "build-report.json", {"schemaVersion": "sermon-weekly-build-v1",
        "feedbackEnabled": True, "feedbackCatalogSha256": sha256(release / "feedback-catalog.json"),
        "files": files, "totalBytes": sum(item["bytes"] for item in files)})


def source_pages_fixture(root):
    """Two source pages share a Sunday and even MP3 bytes, but not identity."""
    release = release_fixture(root, "dual-source")
    track = read(release / "public/weekly.json")["weeks"][0]["tracks"][0]
    source = read(release / "feedback-catalog.json")["sources"][0]
    pages, sources = [], []
    for route in ("same_video", "live_archive"):
        track_id = f'full_candidate__{route}__video'
        pages.append({"id": f'2026-09-06-{route}-video', "date": "2026-09-06", "sourceRoute": route,
            "sourceId": "video", "tracks": [{**track, "id": track_id}], "humanApproval": False})
        sources.append({**source, "week": "2026-09-06", "trackId": track_id})
    write_json(release / "public/weekly.json", {"schemaVersion": "sermon-weekly-catalog-v1", "defaultWeekId": pages[0]["id"], "weeks": pages})
    write_json(release / "feedback-catalog.json", {"schemaVersion": 1, "sources": sources, "weekIds": ["2026-09-06"], "voiceIds": []})
    refresh_report(release)
    return release


def read(path):
    return json.loads(path.read_text())


def snapshot(root):
    return {str(p.relative_to(root)): sha256(p) for p in root.rglob("*") if p.is_file()}


def api_fixture(root, real_runtime=False):
    source = root / "api-source"
    if source.exists():
        return source
    source.mkdir()
    if real_runtime:
        # Freeze once into a test-local manifest. Only the copied bundle is later
        # imported; no API, Firestore, credentials or production files are used.
        for name in ["index.mjs", "core.mjs", "firestore-store.mjs", "usage-core.mjs"]:
            path = deploy.HERE / "feedback-api" / name
            if path.exists():
                (source / path.name).write_bytes(path.read_bytes())
        for name in ["package.json", "package-lock.json"]:
            (source / name).write_bytes((deploy.HERE / "feedback-api" / name).read_bytes())
    else:
        (source / "index.mjs").write_text("export { value } from './core.mjs';\n")
        (source / "core.mjs").write_text("import { value } from './helper.mjs'; export { value };\n")
        (source / "helper.mjs").write_text("export const value = 42;\n")
        write_json(source / "package.json", {"type": "module"})
        write_json(source / "package-lock.json", {"lockfileVersion": 3})
    write_json(source / "catalog.json", {"schemaVersion": 1, "sources": []})
    write_json(source / "server-config.json", {"projectId": deploy.PROJECT, "databaseId": deploy.DATABASE,
        "serviceAccount": f"sermon-feedback-runtime@{deploy.PROJECT}.iam.gserviceaccount.com", "origins": ["https://example.invalid"]})
    refresh_api_manifest(source)
    return source


def refresh_api_manifest(source):
    write_json(source / "source-manifest.json", {"releaseBuildSha256": "a" * 64,
        "feedbackCatalogSha256": sha256(source / "catalog.json"),
        "files": [{"path": p.name, "sha256": sha256(p)} for p in sorted(source.iterdir())
                  if p.is_file() and p.name != "source-manifest.json"]})


def prepare(release, out, previous_releases=(), *, api_source=None):
    return deploy.prepare(release, out, previous_releases,
                          api_source=api_source if api_source is not None else api_fixture(out.parent))


def add_usage_context(release, voice_id="eric"):
    weekly = read(release / "public/weekly.json")
    weekly["voiceBank"] = {"speakers": [{"id": voice_id}]}
    write_json(release / "public/weekly.json", weekly)
    catalog = read(release / "feedback-catalog.json")
    catalog.update(weekIds=[w["id"] for w in weekly["weeks"]], voiceIds=[voice_id])
    write_json(release / "feedback-catalog.json", catalog)
    refresh_report(release)


class FeedbackRolloutTests(unittest.TestCase):
    def test_both_catalog_validators_admit_same_week_source_pages(self):
        with tempfile.TemporaryDirectory() as tmp:
            current = source_pages_fixture(Path(tmp))
            before = snapshot(current)
            standard, standard_receipt = verify_standard_catalog(current)
            compatible, compatible_receipt = deploy.verified_feedback_catalog(current)
            self.assertEqual(standard, compatible)
            self.assertEqual(standard_receipt, compatible_receipt)
            self.assertEqual(compatible["weekIds"], ["2026-09-06"])
            self.assertEqual(len({deploy.source_identity(source) for source in compatible["sources"]}), 2)
            self.assertEqual(snapshot(current), before)

    def test_dual_source_compat_plan_preserves_previous_pages_and_exact_api(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            current = source_pages_fixture(root)
            previous = release_fixture(root, "old-open-page", b"old audio")
            api = api_fixture(root)
            before = {path.name: snapshot(path) for path in (current, previous, api)}
            with patch.object(deploy.subprocess, "run", side_effect=AssertionError("No deployment or network")):
                manifest = prepare(current, root / "new-api", [previous], api_source=api)
            merged = read(root / "new-api/catalog.json")
            self.assertEqual(manifest["currentSourceCount"], 2)
            self.assertEqual(manifest["runtimeSourceCount"], 3)
            self.assertEqual(merged["weekIds"], ["2026-08-30", "2026-09-06"])
            self.assertEqual(len({deploy.source_identity(source) for source in merged["sources"]}), 3)
            self.assertEqual(manifest["compatibleReleases"][0]["addedSourceCount"], 1)
            for item in manifest["apiSource"]["runtimeFiles"]:
                self.assertEqual((root / "new-api" / item["path"]).read_bytes(), (api / item["path"]).read_bytes())
            self.assertEqual({path.name: snapshot(path) for path in (current, previous, api)}, before)

    def test_rehashed_wrong_date_route_or_duplicate_source_page_is_rejected(self):
        mutations = [lambda pages: pages[0].update(date="2026-09-13"),
                     lambda pages: pages[0].update(sourceRoute="live_archive"),
                     lambda pages: pages.append(copy.deepcopy(pages[0]))]
        for mutation in mutations:
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                current = source_pages_fixture(root)
                weekly = read(current / "public/weekly.json")
                mutation(weekly["weeks"])
                write_json(current / "public/weekly.json", weekly)
                refresh_report(current)
                before = snapshot(current)
                for verify in (verify_standard_catalog, deploy.verified_feedback_catalog):
                    with self.assertRaises(ValueError):
                        verify(current)
                with self.assertRaises(ValueError):
                    prepare(current, root / "new-api")
                self.assertFalse((root / "new-api").exists())
                self.assertEqual(snapshot(current), before)

    def test_default_preserves_current_catalog_and_binds_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            current = release_fixture(root, "current")
            before = snapshot(current)
            manifest = prepare(current, root / "api")
            self.assertEqual(read(root / "api/catalog.json"), read(current / "feedback-catalog.json"))
            self.assertEqual(manifest["compatibleReleases"], [])
            self.assertEqual(manifest["releaseBuildSha256"], sha256(current / "build-report.json"))
            self.assertEqual(manifest["feedbackCatalogSha256"], sha256(current / "feedback-catalog.json"))
            self.assertEqual(manifest["runtimeCatalogSha256"], sha256(root / "api/catalog.json"))
            for item in manifest["files"]:
                self.assertEqual(item["sha256"], sha256(root / "api" / item["path"]))
            self.assertEqual(snapshot(current), before)

    def test_pinned_api_keeps_exact_code_config_and_dependency_closure(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            current = release_fixture(root, "current")
            api = api_fixture(root)
            (api / "admin.mjs").write_text("throw new Error('not a runtime dependency');")
            refresh_api_manifest(api)
            before = snapshot(api)
            manifest = prepare(current, root / "api", api_source=api)
            self.assertEqual(manifest["apiSource"]["sourceManifestSha256"], sha256(api / "source-manifest.json"))
            for item in manifest["apiSource"]["runtimeFiles"]:
                self.assertEqual((root / "api" / item["path"]).read_bytes(), (api / item["path"]).read_bytes())
            self.assertEqual((root / "api/server-config.json").read_bytes(), (api / "server-config.json").read_bytes())
            self.assertTrue((root / "api/helper.mjs").is_file())
            self.assertFalse((root / "api/admin.mjs").exists())
            self.assertEqual(snapshot(api), before)

    def test_pinned_api_tampering_missing_dependency_and_unsafe_imports_fail_closed(self):
        def remove_dependency(source):
            manifest = read(source / "source-manifest.json")
            manifest["files"] = [item for item in manifest["files"] if item["path"] != "helper.mjs"]
            write_json(source / "source-manifest.json", manifest)
        def replace_import(source, text):
            (source / "core.mjs").write_text(text)
            refresh_api_manifest(source)
        def wrong_target(source):
            config = read(source / "server-config.json")
            config["databaseId"] = "other-database"
            write_json(source / "server-config.json", config)
            refresh_api_manifest(source)
        def unsafe_manifest(source):
            manifest = read(source / "source-manifest.json")
            manifest["files"].append({"path": "../outside.mjs", "sha256": "a" * 64})
            write_json(source / "source-manifest.json", manifest)
        changes = {
            "changed_file": lambda s: (s / "core.mjs").write_text("changed"),
            "unbound_dependency": remove_dependency,
            "parent_import": lambda s: replace_import(s, "import '../outside.mjs';"),
            "computed_import": lambda s: replace_import(s, "const name = './helper.mjs'; import(name);"),
            "url_import": lambda s: replace_import(s, "import 'https://example.invalid/module.mjs';"),
            "wrong_target": wrong_target,
            "unsafe_manifest": unsafe_manifest,
        }
        for name, change in changes.items():
            with self.subTest(name=name), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                current = release_fixture(root, "current")
                api = api_fixture(root)
                change(api)
                with self.assertRaises(ValueError):
                    prepare(current, root / "api", api_source=api)
                self.assertFalse((root / "api").exists())

    def test_extended_catalog_preserves_bound_week_and_voice_union(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            current = release_fixture(root, "current")
            old = release_fixture(root, "old", b"old")
            add_usage_context(current, "eric")
            add_usage_context(old, "jared")
            catalog, _, compatible = deploy.merge_release_catalogs(current, [old])
            self.assertEqual(catalog["weekIds"], ["2026-08-30"])
            self.assertEqual(catalog["voiceIds"], ["eric", "jared"])
            self.assertEqual(len(catalog["sources"]), 2)
            self.assertEqual(compatible[0]["feedbackCatalogSha256"], sha256(old / "feedback-catalog.json"))

    def test_rehashed_unknown_usage_allowlists_are_rejected(self):
        for field, value in [("weekIds", ["2026-09-06"]), ("voiceIds", ["unpublished-speaker"]),
                             ("voiceIds", ["eric", "eric"]), ("unknown", ["anything"])]:
            with self.subTest(field=field, value=value), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                current = release_fixture(root, "current")
                add_usage_context(current)
                catalog = read(current / "feedback-catalog.json")
                catalog[field] = value
                write_json(current / "feedback-catalog.json", catalog)
                refresh_report(current)
                with self.assertRaises(ValueError):
                    deploy.merge_release_catalogs(current)

    def test_previous_releases_merge_by_audio_identity_and_deduplicate(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            current = release_fixture(root, "current")
            old = release_fixture(root, "old", b"old audio")
            older = release_fixture(root, "older", b"older audio")
            before = {p.name: snapshot(p) for p in [current, old, older]}
            manifest = prepare(current, root / "api", [old, older, old, current])
            sources = read(root / "api/catalog.json")["sources"]
            self.assertEqual(len(sources), 3)
            self.assertEqual(sources[0], read(current / "feedback-catalog.json")["sources"][0])
            self.assertEqual(len({deploy.source_identity(s) for s in sources}), 3)
            self.assertEqual(manifest["currentSourceCount"], 1)
            self.assertEqual(manifest["runtimeSourceCount"], 3)
            self.assertEqual([r["addedSourceCount"] for r in manifest["compatibleReleases"]], [1, 1])
            self.assertEqual(manifest["compatibleReleases"][0]["releaseBuildSha256"], sha256(old / "build-report.json"))
            self.assertEqual(manifest["compatibleReleases"][0]["feedbackCatalogSha256"], sha256(old / "feedback-catalog.json"))
            self.assertEqual({p.name: snapshot(p) for p in [current, old, older]}, before)

    def test_same_source_in_distinct_build_is_retained_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            current = release_fixture(root, "current")
            old = release_fixture(root, "old")
            (old / "public/index.html").write_text("An older UI for the same exact audio and cues")
            refresh_report(old)
            catalog, _, compatible = deploy.merge_release_catalogs(current, [old])
            self.assertEqual(len(catalog["sources"]), 1)
            self.assertEqual(compatible[0]["addedSourceCount"], 0)

    def test_changed_previous_public_bytes_fail_before_output_creation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            current = release_fixture(root, "current")
            old = release_fixture(root, "old", b"old")
            (old / "public/index.html").write_text("changed after release")
            with self.assertRaisesRegex(ValueError, "file or path changed"):
                prepare(current, root / "api", [old])
            self.assertFalse((root / "api").exists())

    def test_changed_previous_catalog_hash_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            current = release_fixture(root, "current")
            old = release_fixture(root, "old", b"old")
            catalog = read(old / "feedback-catalog.json")
            catalog["sources"][0]["durationSeconds"] = 11
            write_json(old / "feedback-catalog.json", catalog)
            with self.assertRaisesRegex(ValueError, "catalog changed"):
                prepare(current, root / "api", [old])
            self.assertFalse((root / "api").exists())

    def test_rehashed_catalog_cannot_add_unknown_sources_or_change_timing(self):
        mutations = {
            "unknown_source": lambda c: c["sources"].append({**c["sources"][0], "audioSha256": "a" * 64}),
            "duplicate_source": lambda c: c["sources"].append(copy.deepcopy(c["sources"][0])),
            "duration": lambda c: c["sources"][0].update(durationSeconds=11),
            "cue": lambda c: c["sources"][0]["cues"][0].update(end=4),
            "boolean_cue": lambda c: c["sources"][0]["cues"][0].update(start=False),
            "extra_field": lambda c: c["sources"][0].update(path="/outside/unverified.mp3"),
            "missing_source": lambda c: c.update(sources=[]),
        }
        for name, mutate in mutations.items():
            with self.subTest(name=name), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                current = release_fixture(root, "current")
                old = release_fixture(root, "old", b"old")
                catalog = read(old / "feedback-catalog.json")
                mutate(catalog)
                write_json(old / "feedback-catalog.json", catalog)
                refresh_report(old)
                with self.assertRaises(ValueError):
                    prepare(current, root / "api", [old])
                self.assertFalse((root / "api").exists())

    def test_public_audio_identity_must_match_verified_media_bytes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            current = release_fixture(root, "current")
            old = release_fixture(root, "old", b"old")
            weekly = read(old / "public/weekly.json")
            weekly["weeks"][0]["tracks"][0]["sha256"] = "a" * 64
            catalog = read(old / "feedback-catalog.json")
            catalog["sources"][0]["audioSha256"] = "a" * 64
            write_json(old / "public/weekly.json", weekly)
            write_json(old / "feedback-catalog.json", catalog)
            refresh_report(old)
            with self.assertRaisesRegex(ValueError, "verified public release file"):
                prepare(current, root / "api", [old])
            self.assertFalse((root / "api").exists())

    def test_same_audio_identity_with_changed_cues_cannot_be_silently_overridden(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            current = release_fixture(root, "current")
            old = release_fixture(root, "old", cue_end=4.0)
            with self.assertRaisesRegex(ValueError, "Conflicting feedback timing"):
                prepare(current, root / "api", [old])
            self.assertFalse((root / "api").exists())

    def test_previous_catalog_symlink_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            current = release_fixture(root, "current")
            old = release_fixture(root, "old", b"old")
            data = (old / "feedback-catalog.json").read_bytes()
            (root / "outside.json").write_bytes(data)
            (old / "feedback-catalog.json").unlink()
            (old / "feedback-catalog.json").symlink_to(root / "outside.json")
            with self.assertRaisesRegex(ValueError, "symlinks"):
                prepare(current, root / "api", [old])
            self.assertFalse((root / "api").exists())

    def test_invalid_schema_duplicate_files_and_sizes_are_rejected(self):
        mutations = {
            "build_schema": lambda r: r.update(schemaVersion="unknown"),
            "feedback_disabled": lambda r: r.update(feedbackEnabled=False),
            "duplicate_file": lambda r: r["files"].append(dict(r["files"][0])),
            "file_size": lambda r: r["files"][0].update(bytes=0),
        }
        for name, mutate in mutations.items():
            with self.subTest(name=name), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                current = release_fixture(root, "current")
                old = release_fixture(root, "old", b"old")
                report = read(old / "build-report.json")
                mutate(report)
                write_json(old / "build-report.json", report)
                with self.assertRaises(ValueError):
                    prepare(current, root / "api", [old])
                self.assertFalse((root / "api").exists())

    def test_existing_api_directory_is_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            current = release_fixture(root, "current")
            out = root / "api"
            out.mkdir()
            (out / "sentinel").write_text("existing deployment")
            before = snapshot(out)
            with self.assertRaisesRegex(ValueError, "new API output"):
                prepare(current, out)
            self.assertEqual(snapshot(out), before)

    def test_cli_accepts_repeated_previous_releases_without_deploying(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            current = release_fixture(root, "current")
            old = release_fixture(root, "old", b"old")
            older = release_fixture(root, "older", b"older")
            args = ["deploy_feedback_compat.py", "--release", str(current), "--out", str(root / "api"), "--api-source", str(api_fixture(root)),
                    "--previous-release", str(old), "--previous-release", str(older)]
            with patch.object(sys, "argv", args), patch.object(deploy.subprocess, "run") as run, contextlib.redirect_stdout(io.StringIO()):
                deploy.main()
            run.assert_not_called()
            receipt = read(root / "api/deployment-receipt.json")
            self.assertEqual(receipt["status"], "prepared_not_deployed")
            self.assertEqual(len(receipt["compatibleReleases"]), 2)
            self.assertEqual(receipt["sourceManifestSha256"], sha256(root / "api/source-manifest.json"))
            self.assertEqual(receipt["runtimeCatalogSha256"], sha256(root / "api/catalog.json"))

    @unittest.skipUnless(shutil.which("node"), "Node is required for the in-memory API rollout test")
    def test_runtime_accepts_new_audio_and_old_session_withdrawal_after_rollout(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            current = release_fixture(root, "current")
            old = release_fixture(root, "old", b"old")
            merged, _, _ = deploy.merge_release_catalogs(current, [old])
            prepare(current, root / "api", [old], api_source=api_fixture(root, real_runtime=True))
            script = r"""
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { pathToFileURL } from 'node:url';
const { createService, prepareCatalog } = await import(pathToFileURL(process.argv[1]).href);
const input = JSON.parse(readFileSync(0, 'utf8'));
const records = new Map();
const store = { transaction: async (fn) => fn({
  get: async (path) => structuredClone(records.get(path)),
  set: (path, value) => records.set(path, structuredClone(value)),
  delete: (path) => records.delete(path),
}) };
let token = 0;
const service = (catalog) => createService({ store, catalog, origins: ['https://example.invalid'],
  now: () => 1788600000000, ipLimiter: () => {},
  randomToken: () => (++token === 1 ? 'A' : 'B').repeat(43) });
const oldApi = service(input.old);
const nextApi = service(input.merged);
assert.equal(prepareCatalog(input.merged).size, 2);
const identity = (source, appVersion) => ({ schemaVersion: 1, week: source.week,
  trackId: source.trackId, audioSha256: source.audioSha256, appVersion });
const oldBody = identity(input.old.sources[0], 'old-ui');
const nextBody = identity(input.current.sources[0], 'new-ui');
const call = (api, path, body, session) => api({ method: 'POST', path,
  origin: 'https://example.invalid', contentType: 'application/json', body,
  rawBytes: Buffer.byteLength(JSON.stringify(body)), authorization: session ? `Bearer ${session.token}` : undefined });
const oldSession = await call(oldApi, '/api/session', oldBody);
await call(oldApi, '/api/feedback', { ...oldBody, kind: 'vote', seq: 1, vote: 'up' }, oldSession);
const feedbackId = '11111111-1111-4111-8111-111111111111';
await call(oldApi, '/api/feedback', { ...oldBody, kind: 'issue', seq: 1, feedbackId,
  action: 'upsert', categories: ['pronunciation'], comment: 'fixture only', context: 'unspecified',
  positionSeconds: 1, cueId: '0', blockId: '0' }, oldSession);
const vote = await call(nextApi, '/api/feedback', { ...oldBody, kind: 'vote', seq: 2, vote: null }, oldSession);
const issue = await call(nextApi, '/api/feedback', { ...oldBody, kind: 'issue', seq: 2, feedbackId, action: 'delete' }, oldSession);
assert.equal(vote.accepted, true);
assert.equal(issue.accepted, true);
assert.equal([...records.keys()].filter((key) => key.startsWith('feedback/')).length, 0);
const nextSession = await call(nextApi, '/api/session', nextBody);
const nextVote = await call(nextApi, '/api/feedback', { ...nextBody, kind: 'vote', seq: 1, vote: 'up' }, nextSession);
assert.equal(nextVote.accepted, true);
await assert.rejects(call(nextApi, '/api/session', { ...nextBody, audioSha256: 'f'.repeat(64) }),
  (error) => error.code === 'unknown_source');
await assert.rejects(call(nextApi, '/api/feedback', { ...nextBody, kind: 'vote', seq: 3, vote: null }, oldSession),
  (error) => error.code === 'invalid_session');
process.stdout.write(JSON.stringify({ oldVoteAndIssueWithdrawn: true, newAudioAccepted: true,
  unknownSourceRejected: true, sessionsRemainAudioBound: true }));
"""
            result = subprocess.run(["node", "--input-type=module", "--eval", script,
                str(root / "api/core.mjs")],
                input=json.dumps({"old": read(old / "feedback-catalog.json"),
                                  "current": read(current / "feedback-catalog.json"), "merged": merged}),
                capture_output=True, text=True, check=True, timeout=20)
            self.assertTrue(all(json.loads(result.stdout).values()))


if __name__ == "__main__":
    unittest.main()
