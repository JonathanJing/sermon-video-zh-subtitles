"""Alignment sidecar assembly and snapshot re-sealing tools (2026-11-21 operator errors)."""

import hashlib
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE / "tools" / "ops"))

import build_alignment_sidecar as SIDE  # noqa: E402
import reseal_snapshot as SEAL  # noqa: E402

PAGE = "page-under-test"
LOCALES = ("zh-Hans", "ko")


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def make_snapshot(root: Path, *, with_window: bool = True) -> Path:
    public = root / "public"
    (public / "alignment").mkdir(parents=True)
    (public / "fingerprints").mkdir(parents=True)
    media = "m" * 64
    identity = "i" * 64
    targets = {}
    for locale in LOCALES:
        (public / "content" / PAGE).mkdir(parents=True, exist_ok=True)
        (public / "media" / PAGE).mkdir(parents=True, exist_ok=True)
        (public / "releases-v2" / PAGE).mkdir(parents=True, exist_ok=True)
        mp3 = public / "media" / PAGE / f"{locale}.mp3"
        mp3.write_bytes(f"audio-{locale}".encode())
        content = {"schemaVersion": "sermon-full-video-text-content-v2", "pageId": PAGE,
                   "targetLocale": locale, "durationSeconds": 120.5, "audioDurationSeconds": 120.5,
                   "sourceMediaSha256": media, "englishSourcePackageJsonSha256": identity, "cues": []}
        if with_window:
            content["sourceWindow"] = {"schemaVersion": "sermon-original-recording-window-v1",
                                       "mediaSha256": media, "startSeconds": 0.0, "endSeconds": 120.5}
        (public / "content" / PAGE / f"{locale}.json").write_text(json.dumps(content), encoding="utf-8")
        release = {"schemaVersion": "sermon-release-v2", "pageId": PAGE, "targetLocale": locale,
                   "assets": [{"role": "audio", "path": f"/media/{PAGE}/{locale}.mp3", "sha256": sha(mp3)},
                              {"role": "content", "path": f"/content/{PAGE}/{locale}.json",
                               "sha256": sha(public / "content" / PAGE / f"{locale}.json")}]}
        release_path = public / "releases-v2" / PAGE / f"{locale}.json"
        release_path.write_text(json.dumps(release), encoding="utf-8")
        targets[locale] = {"releasePackageUrl": f"/releases-v2/{PAGE}/{locale}.json",
                           "releasePackageJsonSha256": sha(release_path)}
        index = {"schemaVersion": "sermon-landmark-index-v1", "algorithmVersion": "spectral-landmarks-v1",
                 "pageId": PAGE, "sourceSha256": media, "trackSha256": sha(mp3),
                 "sourceStartSeconds": 0.0, "sourceEndSeconds": 120.5, "landmarks": []}
        index_path = root / f"index-{locale}.json"
        index_path.write_text(json.dumps(index), encoding="utf-8")
    catalog = {"schemaVersion": "sermon-multilingual-catalog-v5", "pages": [
        {"id": PAGE, "sourceIdentitySha256": identity, "targets": targets}]}
    (public / "multilingual-v5.json").write_text(json.dumps(catalog), encoding="utf-8")
    return public


def test_sidecar_uses_release_file_bytes_and_the_content_window(tmp_path):
    public = make_snapshot(tmp_path)
    indexes = {locale: tmp_path / f"index-{locale}.json" for locale in LOCALES}
    sidecar, evidence = SIDE.build_sidecar(public, PAGE, indexes)
    assert sidecar["sourceIdentitySha256"] == "i" * 64
    for locale in LOCALES:
        target = sidecar["targets"][locale]
        release_file = public / f"releases-v2/{PAGE}/{locale}.json"
        assert target["releasePackageJsonSha256"] == sha(release_file)  # file bytes, not canonical json
        fingerprint = target["audioFingerprint"]
        assert fingerprint["schemaVersion"] == "sermon-audio-fingerprint-binding-v1"
        assert fingerprint["captureSeconds"] == 10
        assert fingerprint["indexUrl"].startswith("/fingerprints/")
        assert fingerprint["indexUrl"].endswith("-landmarks.json")
        assert fingerprint["indexSha256"][:16] in fingerprint["indexUrl"]
    assert evidence["catalog"] == "multilingual-v5.json"


def test_sidecar_rejects_an_index_bound_to_another_track(tmp_path):
    public = make_snapshot(tmp_path)
    index_path = tmp_path / "index-zh-Hans.json"
    index = json.loads(index_path.read_text())
    index["trackSha256"] = "0" * 64
    index_path.write_text(json.dumps(index), encoding="utf-8")
    try:
        SIDE.build_sidecar(public, PAGE, {locale: tmp_path / f"index-{locale}.json" for locale in LOCALES})
    except SystemExit as exc:
        assert "index binds track" in str(exc)
    else:
        raise AssertionError("a mismatched track hash must be refused")


def test_sidecar_write_copies_indexes_and_writes_sidecar(tmp_path):
    public = make_snapshot(tmp_path)
    out = tmp_path / "out"
    code = SIDE.main(["--public", str(public), "--page-id", PAGE,
                      "--index", f"zh-Hans={tmp_path / 'index-zh-Hans.json'}",
                      "--index", f"ko={tmp_path / 'index-ko.json'}",
                      "--out", str(out), "--write"])
    assert code == 0
    sidecar = json.loads((out / "alignment" / f"{PAGE}.json").read_text())
    assert sorted(sidecar["targets"]) == sorted(LOCALES)
    for target in sidecar["targets"].values():
        copied = out / target["audioFingerprint"]["indexUrl"].lstrip("/")
        assert copied.is_file()


def test_reseal_updates_catalog_hashes_and_file_list(tmp_path):
    public = make_snapshot(tmp_path)
    snapshot = tmp_path
    (snapshot / "seal-report.json").write_text(json.dumps({"catalogSha256": "old" * 21, "files": []}), encoding="utf-8")
    (public / "alignment" / f"{PAGE}.json").write_text("{}", encoding="utf-8")
    result = SEAL.reseal(snapshot)
    report = json.loads((snapshot / "seal-report.json").read_text())
    assert report["catalogV5Sha256"] == sha(public / "multilingual-v5.json")
    assert "catalogSha256" not in report  # this fixture ships v5 only; absent catalogs are not invented
    assert len(report["files"]) == len([p for p in public.rglob("*") if p.is_file()])
    assert result["catalogChanges"]
    assert any(row["path"].endswith(f"alignment/{PAGE}.json") for row in report["files"])
