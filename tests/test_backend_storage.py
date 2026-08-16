import unittest

from google.api_core.exceptions import NotFound

from backend.storage import GcsArtifactReader


class _MissingBlob:
    def download_as_bytes(self):
        raise NotFound("missing object")


class _FakeBucket:
    def blob(self, _object_name):
        return _MissingBlob()


class _FakeStorageClient:
    def bucket(self, _bucket_name):
        return _FakeBucket()


class GcsArtifactReaderTest(unittest.TestCase):
    def test_missing_gcs_object_is_normalized_to_file_not_found(self):
        reader = GcsArtifactReader(storage_client=_FakeStorageClient())

        with self.assertRaises(FileNotFoundError) as captured:
            reader.read_bytes("gs://test-bucket/sundays/2026-08-16/cloud-manifest.json")

        self.assertEqual(
            str(captured.exception),
            "gs://test-bucket/sundays/2026-08-16/cloud-manifest.json",
        )


if __name__ == "__main__":
    unittest.main()
