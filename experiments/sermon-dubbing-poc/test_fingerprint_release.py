"""Standalone source/track-bound non-audio fingerprint publication regressions.

All media bytes are inert fixture content; no registry, feedback API or source
recordings are needed to exercise the actual uploader validation boundary.
"""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from deploy_firebase import verify_release, FINGERPRINT_UI


def write_json(path, value):
    Path(path).write_text(json.dumps(value) + "\n")


def digest(data):
    return hashlib.sha256(data).hexdigest()


class FingerprintReleaseTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.release = Path(self.tmp.name)
        self.public = self.release / "public"
        (self.public / "media").mkdir(parents=True)
        (self.public / "fingerprints").mkdir()
        audio = b"inert fixture, not source audio"
        track_sha = digest(audio)
        name = track_sha[:16] + "-zh-synced.mp3"
        (self.public / "media" / name).write_bytes(audio)
        (self.public / "index.html").write_text("Fixture")
        for filename in FINGERPRINT_UI:
            (self.public / filename).write_text("// inert test runtime")
        self.week = {
            "id": "2026-09-13-same_video-source-" + "a" * 16,
            "sourceRoute": "same_video", "sourceId": "source-" + "a" * 16,
            "sourceStartSeconds": 1793, "sourceEndSeconds": 1795,
            "tracks": [{"id": "sync", "sha256": track_sha, "file": name,
                        "audioUrl": "/media/" + name, "durationSeconds": 2}],
        }
        self.index = dict(schemaVersion="sermon-landmark-index-v1", algorithmVersion="spectral-landmarks-v1",
                          sampleRate=8000, hopSize=256, fftSize=1024, sourceSha256="a" * 64,
                          trackSha256=track_sha, pageId=self.week["id"], sourceStartSeconds=1793,
                          sourceEndSeconds=1795, window={"startSeconds": 1793, "endSeconds": 1795},
                          durationSeconds=2, landmarkCount=3, postings={"123": [1, 4, 8]})
        self.install_index(self.index)

    def refresh(self):
        files = [{"path": p.relative_to(self.public).as_posix(), "sha256": digest(p.read_bytes()),
                  "bytes": p.stat().st_size} for p in sorted(self.public.rglob("*")) if p.is_file()]
        write_json(self.release / "build-report.json", {"files": files, "totalBytes": sum(p["bytes"] for p in files)})

    def install_index(self, index):
        for path in (self.public / "fingerprints").iterdir():
            path.unlink()
        data = json.dumps(index).encode()
        sha = digest(data)
        self.index_path = self.public / "fingerprints" / (sha[:16] + "-landmarks.json")
        self.index_path.write_bytes(data)
        binding = {key: index[key] for key in ("algorithmVersion", "sourceSha256", "trackSha256", "pageId", "sourceStartSeconds", "sourceEndSeconds")}
        binding.update(schemaVersion="sermon-audio-fingerprint-binding-v1", captureSeconds=10,
                       indexUrl="/" + self.index_path.relative_to(self.public).as_posix(), indexSha256=sha)
        page = copy.deepcopy(self.week)
        page["audioFingerprint"] = binding
        write_json(self.public / "weekly.json", {"schemaVersion": "sermon-weekly-catalog-v1", "weeks": [page]})
        self.refresh()

    def change_catalog(self, mutate):
        path = self.public / "weekly.json"
        catalog = json.loads(path.read_text())
        mutate(catalog)
        write_json(path, catalog)
        self.refresh()

    def reject(self):
        with self.assertRaises(ValueError):
            verify_release(self.release)

    def test_valid_bound_index(self):
        report = verify_release(self.release)
        self.assertIn(self.index_path.relative_to(self.public).as_posix(), {f["path"] for f in report["files"]})

    def test_wrong_source_track_window_and_page_rejected_even_rehashed(self):
        for key, value in [("sourceSha256", "b" * 64), ("trackSha256", "b" * 64),
                           ("pageId", "wrong"), ("sourceStartSeconds", 1792), ("sourceEndSeconds", 1796)]:
            with self.subTest(field=key):
                index = copy.deepcopy(self.index)
                index[key] = value
                self.install_index(index)
                self.reject()

    def test_no_raw_audio_or_private_extra_fields(self):
        index = copy.deepcopy(self.index)
        index["rawAudio"] = "private base64"
        self.install_index(index)
        self.reject()

    def test_only_numeric_ordered_bounded_postings(self):
        for times in [["raw"], [3, 2], [1, 1], [-1], [1000], [True], [], [1] * 10001]:
            with self.subTest(times=str(times)[:40]):
                index = copy.deepcopy(self.index)
                index["postings"]["123"] = times
                self.install_index(index)
                self.reject()
        for key in ["raw", "01", "4294967296", "-1"]:
            index = copy.deepcopy(self.index)
            index["postings"] = {key: [1]}
            self.install_index(index)
            self.reject()

    def test_external_or_unbound_index_rejected(self):
        self.change_catalog(lambda c: c["weeks"][0]["audioFingerprint"].update(indexUrl="https://example.com/secret.json"))
        self.reject()
        self.install_index(self.index)
        self.change_catalog(lambda c: c["weeks"][0].pop("audioFingerprint"))
        self.reject()

    def test_tampered_bytes_and_missing_runtime_rejected(self):
        self.index_path.write_text("{}")
        self.reject()
        self.install_index(self.index)
        (self.public / "fingerprint-worker.mjs").unlink()
        self.refresh()
        self.reject()

    def test_schema_algorithm_duration_and_missing_binding_field(self):
        for key, value in [("schemaVersion", "wrong"), ("algorithmVersion", "wrong"), ("captureSeconds", 9), ("indexSha256", "bad")]:
            with self.subTest(field=key):
                self.install_index(self.index)
                self.change_catalog(lambda c: c["weeks"][0]["audioFingerprint"].update({key: value}))
                self.reject()
        self.install_index(self.index)
        self.change_catalog(lambda c: c["weeks"][0]["audioFingerprint"].pop("sourceEndSeconds"))
        self.reject()
        for key, value in [("schemaVersion", "wrong"), ("sampleRate", 16000), ("hopSize", 128), ("fftSize", 2048),
                           ("window", {"startSeconds": 0, "endSeconds": 2}), ("durationSeconds", 3), ("landmarkCount", 2), ("landmarkCount", True)]:
            index = copy.deepcopy(self.index)
            index[key] = value
            self.install_index(index)
            self.reject()

    def test_catalog_schema_and_source_route(self):
        self.change_catalog(lambda c: c.update(schemaVersion="wrong"))
        self.reject()
        self.install_index(self.index)
        self.change_catalog(lambda c: c["weeks"][0].update(sourceRoute="live_archive"))
        self.reject()

    def test_duplicate_manifest_path_rejected(self):
        path = self.release / "build-report.json"
        report = json.loads(path.read_text())
        report["files"].append(copy.deepcopy(report["files"][0]))
        write_json(path, report)
        self.reject()

    def test_index_manifest_size_and_hash_must_match(self):
        for key, value in [("sha256", "c" * 64), ("bytes", 1)]:
            self.refresh()
            path = self.release / "build-report.json"
            report = json.loads(path.read_text())
            next(f for f in report["files"] if f["path"].startswith("fingerprints/"))[key] = value
            write_json(path, report)
            self.reject()

    def test_binding_to_actual_published_mp3_is_required_without_a_registry(self):
        for mutate in [lambda t: t.update(file="missing.mp3"), lambda t: t.update(audioUrl="/media/other.mp3"),
                       lambda t: t.update(durationSeconds=float("nan")), lambda t: t.update(durationSeconds=True)]:
            self.install_index(self.index)
            self.change_catalog(lambda c: mutate(c["weeks"][0]["tracks"][0]))
            self.reject()
        self.install_index(self.index)
        self.change_catalog(lambda c: c["weeks"][0]["tracks"].append(copy.deepcopy(c["weeks"][0]["tracks"][0])))
        self.reject()
        self.install_index(self.index)
        track = self.week["tracks"][0]
        (self.public / "media" / track["file"]).write_bytes(b"changed, not matching catalog audio")
        self.refresh()
        self.reject()

    def test_index_symlink_and_unknown_upload_rejected(self):
        outside = self.release / "index-source.json"
        outside.write_bytes(self.index_path.read_bytes())
        self.index_path.unlink()
        self.index_path.symlink_to(outside)
        self.refresh()
        self.reject()
        self.install_index(self.index)
        (self.public / "recording.wav").write_bytes(b"not uploadable")
        self.refresh()
        self.reject()

    def test_old_catalog_without_index_remains_supported(self):
        self.index_path.unlink()
        self.change_catalog(lambda c: c["weeks"][0].pop("audioFingerprint"))
        verify_release(self.release)


if __name__ == "__main__":
    unittest.main()
