import hashlib
import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from scripts import build_four_layer_tracker_snapshot as tracker
from scripts import four_layer_progress


class TrackerSnapshotTest(unittest.TestCase):
    def setUp(self):
        self.ledger = four_layer_progress.new_ledger("page-2026-09-20", ["zh-Hans", "ko", "es"])
        self.monitor = {
            "sunday": "2026-09-20", "status": "source_detected",
            "checkedAt": "2026-09-20T10:00:00-07:00",
            "selectedSource": {"url": "https://www.youtube.com/watch?v=abcdefghijk",
                               "state": "was_live", "kind": "youtube-stream"},
        }

    def test_source_video_change_uses_private_state_and_public_snapshot_is_redacted(self):
        first = tracker.build_snapshot(self.ledger, monitor=self.monitor,
                                       source_page_url="https://www.marinerschurch.org/irvine/",
                                       service_date="2026-09-20")
        self.assertEqual(first["schemaVersion"], "sermon-public-tracker-snapshot-v2")
        self.assertEqual(first["source"]["videoChange"], "first_seen")
        self.assertNotIn("videoId", first["source"])
        self.assertNotIn("videoUrl", first["source"])
        _, private = tracker.source_summary(self.monitor, None, None, "2026-09-20")
        second = tracker.build_snapshot(self.ledger, monitor=self.monitor, previous_source_state=private,
                                        service_date="2026-09-20")
        self.assertEqual(second["source"]["videoChange"], "first_seen")
        revised = dict(self.monitor, selectedSource={"url": "https://youtu.be/0123456789A",
                                                     "state": "available"})
        third = tracker.build_snapshot(self.ledger, monitor=revised, previous_source_state=private,
                                       service_date="2026-09-20")
        self.assertEqual(third["source"]["videoChange"], "updated")
        self.assertNotIn("abcdefghijk", str(third))
        self.assertNotIn("0123456789A", str(third))
        with self.assertRaisesRegex(ValueError, "date"):
            tracker.build_snapshot(self.ledger, monitor=revised, service_date="2026-09-21")

    def test_first_cli_run_creates_private_comparison_state(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ledger = root / "ledger.json"
            monitor = root / "monitor.json"
            output = root / "public-snapshot.json"
            four_layer_progress.save(ledger, self.ledger)
            monitor.write_text(json.dumps(self.monitor), encoding="utf-8")
            argv = ["tracker", "--ledger", str(ledger), "--out", str(output),
                    "--source-monitor", str(monitor), "--service-date", "2026-09-20"]
            with patch.object(sys, "argv", argv):
                tracker.main()
            public = output.read_text(encoding="utf-8")
            private = (root / "source-video-state.private.json").read_text(encoding="utf-8")
            self.assertNotIn("abcdefghijk", public)
            self.assertIn("abcdefghijk", private)
            self.assertEqual(json.loads(public)["source"]["videoChange"], "first_seen")

    def test_fingerprint_requires_bound_local_hash_and_http_receipt(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            index = root / "fingerprints" / "index.json"
            index.parent.mkdir()
            index.write_text("{}")
            sha = hashlib.sha256(index.read_bytes()).hexdigest()
            bound = index.with_name(sha[:16] + "-landmarks.json")
            index.rename(bound)
            track_sha = "a" * 64
            week = {"id": self.ledger["pageId"], "tracks": [{"sha256": track_sha}],
                    "audioFingerprint": {"pageId": self.ledger["pageId"],
                                         "indexUrl": "/fingerprints/" + bound.name,
                                         "indexSha256": sha, "trackSha256": track_sha}}
            local = tracker.local_fingerprint(week, root, None)
            self.assertEqual(local["status"], "generated_local")
            receipt = {"status": "pass", "files": [{"path": "fingerprints/" + bound.name,
                                                       "status": 200, "hashMatch": True}]}
            self.assertEqual(tracker.local_fingerprint(week, root, receipt)["status"], "http_verified")
            bound.write_text("changed")
            self.assertEqual(tracker.local_fingerprint(week, root, receipt)["status"], "hash_mismatch")

    def test_legacy_catalog_does_not_promote_other_locales_or_voice_review(self):
        catalog = {"schemaVersion": "sermon-weekly-catalog-v1", "weeks": [{
            "id": self.ledger["pageId"], "tracks": [{"audioUrl": "/media/a.mp3", "sha256": "a" * 64}],
        }]}
        receipt = {"status": "pass", "files": [{"path": "weekly.json", "status": 200,
                                                  "hashMatch": True}]}
        snapshot = tracker.build_snapshot(self.ledger, catalog=catalog, receipt=receipt,
                                          site_url="https://example.web.app")
        by_locale = {item["locale"]: item["delivery"] for item in snapshot["locales"]}
        self.assertEqual(by_locale["zh-Hans"]["pageStatus"], "legacy_catalog_http_verified")
        self.assertFalse(by_locale["zh-Hans"]["voicePublished"])
        self.assertEqual(by_locale["ko"]["pageStatus"], "not_generated")
        self.assertEqual(by_locale["es"]["fingerprint"]["status"], "not_generated")

    def test_snapshot_shows_measured_execution_without_promoting_step(self):
        from scripts import four_layer_measure
        report = four_layer_measure.timing_audit(self.ledger, [
            {"event": "workflow_started", "workflowId": "w1",
             "metadata": {"pageId": self.ledger["pageId"], "target": "dev",
                          "ledgerIdentitySha256": four_layer_progress.ledger_identity(self.ledger)}},
            {"event": "stage_finished", "workflowId": "w1",
             "stage": "four_layer.L2-03:ko", "status": "failed",
             "elapsedSeconds": 12.5, "recordedAt": "2026-09-23T12:00:00+00:00"}])
        snapshot = tracker.build_snapshot(self.ledger, timing_report=report)
        step = next(row for row in snapshot["steps"] if row["id"] == "L2-03@ko")
        self.assertEqual(step["timing"]["measuredExecutionSeconds"], 12.5)
        self.assertEqual(step["timing"]["failedExecutionAttempts"], 1)
        self.assertEqual(step["status"], "pending")
        self.assertEqual(snapshot["timingCoverage"]["measuredStepCount"], 1)

    def test_running_step_shows_bounded_elapsed_at_snapshot_without_exposing_start(self):
        key = "L3-02@ko"
        now = datetime.now(timezone.utc)
        status_start = (now - timedelta(minutes=8)).isoformat()
        execution_start = (now - timedelta(seconds=95)).isoformat()
        self.ledger["steps"][key]["status"] = "running"
        self.ledger["history"] = [
            {"action": "update", "step": key, "status": "running", "at": status_start},
            {"action": "update", "step": key, "status": "running",
             "at": (now - timedelta(minutes=2)).isoformat()},
        ]
        report = {"rows": [{"step": key, "openExecution": True,
                           "attemptHistory": [{"status": "unfinished", "startedAt": execution_start}]}]}
        snapshot = tracker.build_snapshot(self.ledger, timing_report=report)
        timing = next(row["timing"] for row in snapshot["steps"] if row["id"] == key)
        self.assertTrue(479 <= timing["statusElapsedSeconds"] <= 481)
        self.assertTrue(94 <= timing["openExecutionElapsedSeconds"] <= 96)
        self.assertNotIn("startedAt", json.dumps(snapshot))
        self.assertNotIn(execution_start, json.dumps(snapshot))

    def test_status_timer_restarts_after_status_change_and_ignores_missing_history(self):
        key = "L2-02@es"
        now = datetime.now(timezone.utc)
        self.ledger["steps"][key]["status"] = "running"
        snapshot = tracker.build_snapshot(self.ledger)
        timing = next(row["timing"] for row in snapshot["steps"] if row["id"] == key)
        self.assertIsNone(timing["statusElapsedSeconds"])
        self.ledger["history"] = [
            {"action": "update", "step": key, "status": "running",
             "at": (now - timedelta(hours=2)).isoformat()},
            {"action": "update", "step": key, "status": "waiting_review",
             "at": (now - timedelta(minutes=20)).isoformat()},
            {"action": "update", "step": key, "status": "running",
             "at": (now - timedelta(minutes=3)).isoformat()},
        ]
        snapshot = tracker.build_snapshot(self.ledger)
        timing = next(row["timing"] for row in snapshot["steps"] if row["id"] == key)
        self.assertTrue(179 <= timing["statusElapsedSeconds"] <= 181)

    def test_dev_poc_catalog_tracks_are_visible_without_formal_voice_promotion(self):
        catalog = {"schemaVersion": "sermon-weekly-catalog-v1", "weeks": [{
            "id": self.ledger["pageId"], "humanApproval": False,
            "contentReview": "machine_review_pass_human_review_pending",
            "tracks": [{"locale": locale, "scope": "machine_poc_not_production",
                        "audioUrl": f"/media/{locale}.mp3", "sha256": "a" * 64,
                        "machineScreening": {"status": "requires_review" if locale == "vi" else "pass"},
                        "voiceSampleReview": "pending"}
                       for locale in self.ledger["locales"]],
        }]}
        receipt = {"status": "pass", "files": [
            {"path": "weekly.json", "status": 200, "hashMatch": True},
            {"path": "media/ko.mp3", "status": 200, "hashMatch": True,
             "range": {"status": 206, "bytesMatch": True}},
        ]}
        snapshot = tracker.build_snapshot(self.ledger, catalog=catalog, receipt=receipt,
                                          site_url="https://example.web.app")
        rows = {item["locale"]: item["delivery"] for item in snapshot["locales"]}
        self.assertEqual(rows["ko"]["pageStatus"], "poc_catalog_http_verified")
        self.assertEqual(rows["ko"]["voiceStatus"], "poc_track_http_verified")
        self.assertFalse(rows["ko"]["voicePublished"])
        self.assertEqual(rows["es"]["voiceStatus"], "poc_track_listed")
        self.assertEqual(rows["zh-Hans"]["pocCandidateStatus"],
                         "machine_review_pass_human_review_pending")
        self.assertEqual(rows["ko"]["pocScreeningStatus"], "pass")
        self.assertEqual(rows["ko"]["pocVoiceReview"], "pending")
        extra = four_layer_progress.new_ledger(self.ledger["pageId"], ["zh-Hans", "ko", "es", "fr"])
        extra_snapshot = tracker.build_snapshot(extra, catalog=catalog, receipt=receipt,
                                                site_url="https://example.web.app")
        fr = next(item["delivery"] for item in extra_snapshot["locales"] if item["locale"] == "fr")
        self.assertEqual(fr["pageStatus"], "not_generated")

    def test_korean_fingerprint_needs_same_locale_audio_asset(self):
        sha = "b" * 64
        binding = {"schemaVersion": "sermon-tracker-fingerprint-v1",
                   "pageId": self.ledger["pageId"], "targetLocale": "ko",
                   "indexUrl": "/fingerprints/" + "a" * 16 + "-landmarks.json",
                   "indexSha256": "a" * 64, "trackSha256": sha}
        package = {"pageId": self.ledger["pageId"], "targetLocale": "ko",
                   "status": "candidate", "audioStatus": "human_reviewed", "assets": [
                       {"role": "audio", "sha256": sha, "path": "media/ko.mp3"}]}
        snapshot = tracker.build_snapshot(self.ledger, packages={"ko": package},
                                          fingerprints={"ko": binding})
        delivery = next(item["delivery"] for item in snapshot["locales"] if item["locale"] == "ko")
        self.assertEqual(delivery["fingerprint"]["status"], "declared_unchecked")
        self.assertEqual(delivery["pageStatus"], "release_candidate")
        self.assertFalse(delivery["voicePublished"])
        binding["trackSha256"] = "c" * 64
        snapshot = tracker.build_snapshot(self.ledger, packages={"ko": package},
                                          fingerprints={"ko": binding})
        delivery = next(item["delivery"] for item in snapshot["locales"] if item["locale"] == "ko")
        self.assertEqual(delivery["fingerprint"]["status"], "binding_invalid")

    def test_canonical_chinese_release_does_not_inherit_legacy_fingerprint(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            index = root / "fingerprints" / ("a" * 16 + "-landmarks.json")
            index.parent.mkdir()
            index.write_text("{}", encoding="utf-8")
            index_sha = hashlib.sha256(index.read_bytes()).hexdigest()
            legacy_sha = "a" * 64
            week = {"id": self.ledger["pageId"], "tracks": [{"sha256": legacy_sha}],
                    "audioFingerprint": {"pageId": self.ledger["pageId"],
                                         "indexUrl": "/fingerprints/" + index.name,
                                         "indexSha256": index_sha, "trackSha256": legacy_sha}}
            receipt = {"status": "pass", "files": [{"path": "fingerprints/" + index.name,
                                                         "status": 200, "hashMatch": True}]}
            package = {"status": "candidate", "audioStatus": "human_reviewed",
                       "assets": [{"role": "audio", "sha256": "b" * 64}]}
            delivery = tracker.locale_delivery("zh-Hans", package, week, root, receipt,
                                               None, self.ledger["pageId"])
            self.assertEqual(delivery["fingerprint"]["status"], "not_generated")

    def test_withdrawn_release_does_not_expose_page_voice_or_fingerprint(self):
        package = {"status": "withdrawn", "audioStatus": "human_reviewed",
                   "assets": [{"role": "audio", "sha256": "a" * 64}]}
        binding = {"status": "http_verified", "trackSha256": "a" * 64}
        delivery = tracker.locale_delivery("ko", package, None, None, None,
                                           "https://example.web.app", self.ledger["pageId"], binding)
        self.assertEqual(delivery["pageStatus"], "withdrawn")
        self.assertEqual(delivery["voiceStatus"], "withdrawn")
        self.assertEqual(delivery["fingerprint"]["status"], "withdrawn")
        self.assertIsNone(delivery["pageUrl"])
        self.assertFalse(delivery["voicePublished"])

    def test_published_release_requires_human_text_and_http_evidence(self):
        package = {
            "schemaVersion": "sermon-target-language-release-package-v1",
            "pageId": self.ledger["pageId"], "targetLocale": "ko", "sourceLocale": "en",
            "contentLocale": "ko", "audioLocale": "ko", "status": "published_http_verified",
            "contentStatus": "human_reviewed", "audioStatus": "human_reviewed",
            "targetLanguageCandidateJsonSha256": "a" * 64,
            "targetLanguageAudioPackageJsonSha256": "b" * 64,
            "assets": [{"role": "audio", "path": "media/ko.mp3", "sha256": "c" * 64}],
            "httpVerification": {"status": "pass", "evidenceSha256": "d" * 64},
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "release.json"
            path.write_text(json.dumps(package), encoding="utf-8")
            self.assertIn("ko", tracker.release_packages([path], self.ledger["pageId"], self.ledger["locales"]))
            package["httpVerification"]["evidenceSha256"] = None
            path.write_text(json.dumps(package), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "evidence"):
                tracker.release_packages([path], self.ledger["pageId"], self.ledger["locales"])


if __name__ == "__main__":
    unittest.main()
