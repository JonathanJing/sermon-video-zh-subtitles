"""Private evidence store: text evidence only, credentials scrubbed, never a public bucket."""
import base64
import hashlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from tools.ops import evidence_store as store


class FakeBlob:
    def __init__(self, bucket, name):
        self.bucket, self.name = bucket, name

    @property
    def md5_hash(self):
        data = self.bucket.objects.get(self.name)
        return None if data is None else base64.b64encode(hashlib.md5(data).digest()).decode()

    def exists(self):
        return self.name in self.bucket.objects

    def download_as_bytes(self):
        return self.bucket.objects[self.name]

    def upload_from_string(self, data, content_type=None):
        self.bucket.objects[self.name] = data
        self.bucket.content_types[self.name] = content_type


class FakeBucket:
    def __init__(self, uniform=True, prevention="enforced"):
        self.objects, self.content_types = {}, {}
        self.iam_configuration = SimpleNamespace(uniform_bucket_level_access_enabled=uniform,
                                                 public_access_prevention=prevention)

    def blob(self, name):
        return FakeBlob(self, name)

    def reload(self):
        pass


class FakeClient:
    def __init__(self, bucket):
        self._bucket = bucket

    def bucket(self, name):
        return self._bucket

    def list_blobs(self, bucket, prefix="", delimiter=None):
        return [FakeBlob(bucket, name) for name in sorted(bucket.objects) if name.startswith(prefix)]


class EvidenceStoreTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.base = Path(temp.name)
        self.run = self.base / "20261115-sample-zh"
        (self.run / "translate").mkdir(parents=True)
        (self.run / "slices").mkdir()
        (self.run / "stage1" / "public" / "pages").mkdir(parents=True)
        (self.run / "translations.jsonl").write_text('{"id": 1, "zh": "耶稣胜过这世界"}\n', encoding="utf-8")
        (self.run / "journal.ndjson").write_text('{"stage": "l4.publish", "event": "started"}\n')
        (self.run / "translate" / "run.log").write_text(
            "OPENAI_API_KEY=sk-proj-abcdefghijklmnopqrstuvwxyz\nAuthorization: Bearer abc.def.ghijkl\n"
            "reviewer someone@example.com at /Users/someone/run\n")
        (self.run / "stage1" / "deployment-attempt-v2.json").write_text(json.dumps({"status": "deployed"}))
        (self.run / "stage1" / "public" / "pages" / "index.html").write_text("<html></html>")
        (self.run / "slices" / "0001.wav").write_bytes(b"RIFF" * 8)
        (self.run / "track.wav").write_bytes(b"RIFF" * 64)
        (self.run / ".journal-host-salt").write_text("salt")
        (self.run / "service-account.json").write_text('{"private_key": "x"}')
        (self.run / "binary.json").write_bytes(b"\xff\xfe\x00bad")

    def test_collect_keeps_text_and_counts_media(self):
        manifest, files = store.collect(self.run, secrets=[], host="host-a")
        self.assertEqual(sorted(files), ["journal.ndjson", "stage1/deployment-attempt-v2.json",
                                         "translate/run.log", "translations.jsonl"])
        self.assertIn("耶稣胜过这世界", files["translations.jsonl"].decode("utf-8"))
        self.assertEqual(manifest["skipped"][".wav"], {"files": 1, "bytes": 256})
        self.assertEqual(manifest["skipped"]["dir:slices"], {"dirs": 1, "bytes": 32})
        self.assertEqual(manifest["skipped"]["dir:public"]["dirs"], 1)
        reasons = {row["path"]: row["reason"] for row in manifest["omitted"]}
        self.assertEqual(reasons, {".journal-host-salt": "denied_name", "service-account.json": "denied_name",
                                   "binary.json": "not_utf8"})
        self.assertEqual(manifest["source"]["host"], "host-a")
        original = (self.run / "translations.jsonl").read_bytes()
        entry = next(row for row in manifest["files"] if row["path"] == "translations.jsonl")
        self.assertEqual(entry["sha256"], hashlib.sha256(original).hexdigest())

    def test_credentials_are_scrubbed_but_private_text_stays(self):
        manifest, files = store.collect(self.run, secrets=["supersecretvalue123"], host="host-a")
        log = files["translate/run.log"].decode("utf-8")
        self.assertNotIn("sk-proj-", log)
        self.assertNotIn("abc.def.ghijkl", log)
        self.assertIn("someone@example.com", log)
        self.assertIn("/Users/someone/run", log)
        self.assertGreaterEqual(manifest["totals"]["scrubbed"], 2)

    def test_tar_round_trip_and_unsafe_members(self):
        buffer = io.BytesIO()
        store.write_tar([self.run], buffer, secrets=[])
        buffer.seek(0)
        (manifest, files), = store.read_tar(buffer)
        self.assertEqual(manifest["runName"], "20261115-sample-zh")
        self.assertIn("translations.jsonl", files)
        import tarfile
        bad = io.BytesIO()
        with tarfile.open(fileobj=bad, mode="w:gz") as archive:
            info = tarfile.TarInfo("run/../../escape.json")
            info.size = 2
            archive.addfile(info, io.BytesIO(b"{}"))
        bad.seek(0)
        with self.assertRaises(ValueError):
            store.read_tar(bad)

    def test_upload_is_incremental_and_refuses_another_source(self):
        target = store.LocalStore(self.base / "store")
        manifest, files = store.collect(self.run, secrets=[], host="host-a")
        first = store.upload_bundle(target, manifest, files)
        self.assertEqual((first["sent"], first["unchanged"]), (4, 0))
        self.assertTrue((self.base / "store/runs/20261115-sample-zh/_manifest.json").is_file())
        (self.run / "journal.ndjson").write_text('{"stage": "l4.publish", "event": "finished"}\n')
        manifest, files = store.collect(self.run, secrets=[], host="host-a")
        second = store.upload_bundle(target, manifest, files)
        self.assertEqual((second["sent"], second["unchanged"]), (1, 3))
        other, other_files = store.collect(self.run, secrets=[], host="host-b")
        with self.assertRaises(ValueError):
            store.upload_bundle(target, other, other_files)
        merged = store.upload_bundle(target, other, other_files, replace_source=True)
        self.assertEqual(merged["sent"], 0)

    def test_gcs_store_checks_privacy_before_any_upload(self):
        public = FakeBucket(prevention="inherited")
        with self.assertRaises(ValueError):
            store.push_runs([self.run], "gs://example-bucket/run-evidence/v1", client=FakeClient(public))
        self.assertEqual(public.objects, {})
        private = FakeBucket()
        result, = store.push_runs([self.run], "gs://example-bucket/run-evidence/v1", client=FakeClient(private))
        self.assertEqual(result["sent"], 4)
        self.assertIn("run-evidence/v1/runs/20261115-sample-zh/translations.jsonl", private.objects)
        self.assertEqual(private.content_types["run-evidence/v1/runs/20261115-sample-zh/_manifest.json"],
                         "application/json; charset=utf-8")
        again, = store.push_runs([self.run], "gs://example-bucket/run-evidence/v1", client=FakeClient(private))
        self.assertEqual((again["sent"], again["unchanged"]), (0, 4))

    def test_put_and_pull_private_reports(self):
        target = store.LocalStore(self.base / "store")
        report = self.base / "usage-report"
        report.mkdir()
        (report / "summary.json").write_text(json.dumps({"totals": {"sessions": 3}}))
        (report / "index.html").write_text("<html>report</html>")
        with self.assertRaises(ValueError):
            store.put_directory(target, report, "runs/x")
        with self.assertRaises(ValueError):
            store.put_directory(target, report, "frontend/../runs")
        result = store.put_directory(target, report, "frontend/20261109_20261115/usage", secrets=[])
        self.assertEqual(result["sent"], 2)
        written = store.pull(target, "frontend/20261109_20261115", self.base / "cache")
        self.assertIn("frontend/20261109_20261115/usage/summary.json", written)
        self.assertEqual(target.names("frontend/"), ["frontend/20261109_20261115/"])

    def test_index_lists_names_and_hashes_only(self):
        target = store.LocalStore(self.base / "store")
        manifest, files = store.collect(self.run, secrets=[], host="host-a")
        store.upload_bundle(target, manifest, files)
        report = self.base / "usage-report"
        report.mkdir()
        (report / "summary.json").write_text("{}")
        store.put_directory(target, report, "frontend/20261115/usage", secrets=[])
        index = store.build_index(target)
        self.assertEqual([row["runName"] for row in index["runs"]], ["20261115-sample-zh"])
        self.assertEqual(set(index["runs"][0]), {"runName", "files", "collectedAt", "manifestSha256"})
        self.assertEqual((index["frontend"], index["weekly"]), (["20261115"], []))
        text = json.dumps(index, ensure_ascii=False)
        self.assertNotIn("host-a", text)
        self.assertNotIn("耶稣", text)


if __name__ == "__main__":
    unittest.main()
