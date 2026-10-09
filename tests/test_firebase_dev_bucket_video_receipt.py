import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from scripts import align_firebase_dev_v3 as dev


PAGE_ID = "resi-test"
SHA = "b" * 64
STORAGE = f"https://storage.googleapis.com/bucket/weekly/{PAGE_ID}/{SHA}.mp4"


def page(storage_url=STORAGE, sha=SHA, bytes_=1234):
    return {"id": PAGE_ID, "videoDelivery": {"storageUrl": storage_url, "sha256": sha, "bytes": bytes_}}


def receipt(**overrides):
    value = {"schemaVersion": "sermon-bucket-video-receipt-v1", "status": "verified",
             "pageId": PAGE_ID, "storageUrl": STORAGE, "sha256": SHA, "bytes": 1234}
    value.update(overrides)
    return value


class BucketVideoReceiptTests(unittest.TestCase):
    def run_check(self, receipt_value, delivery=None, local_video=False):
        with TemporaryDirectory() as folder:
            candidate = Path(folder)
            public = candidate / "public"
            public.mkdir()
            if local_video:
                video = public / f"pages/{PAGE_ID}/full-video-browser.mp4"
                video.parent.mkdir(parents=True)
                video.write_bytes(b"local")
            if receipt_value is not None:
                (candidate / "bucket-video-receipt.json").write_text(json.dumps(receipt_value), encoding="utf-8")
            dev.checked_browser_video(public, PAGE_ID, delivery or page(), SHA)

    def test_accepts_bucket_video_with_matching_receipt(self):
        self.run_check(receipt())

    def test_rejects_bucket_video_without_receipt(self):
        with self.assertRaises(ValueError):
            self.run_check(None)

    def test_rejects_receipt_for_another_object(self):
        with self.assertRaises(ValueError):
            self.run_check(receipt(storageUrl=STORAGE + "x"))

    def test_rejects_unverified_receipt(self):
        with self.assertRaises(ValueError):
            self.run_check(receipt(status="mismatch"))

    def test_rejects_receipt_with_wrong_size(self):
        with self.assertRaises(ValueError):
            self.run_check(receipt(bytes=999))

    def test_local_video_still_checked_by_hash(self):
        with self.assertRaises(ValueError):
            self.run_check(None, delivery={"sha256": SHA}, local_video=True)
        # A local file is checked against the expected hash; a bucket receipt is not consulted.
        with TemporaryDirectory() as folder:
            public = Path(folder) / "public"
            video = public / f"pages/{PAGE_ID}/full-video-browser.mp4"
            video.parent.mkdir(parents=True)
            video.write_bytes(b"local")
            with self.assertRaises(ValueError):
                dev.checked_browser_video(public, PAGE_ID, page(), SHA)


if __name__ == "__main__":
    unittest.main()
