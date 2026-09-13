"""Usage allowlists must remain bound to the explicitly verified release."""
import tempfile
from pathlib import Path
import unittest

import deploy_feedback as deploy
from poc import write_json
from test_feedback_rollout import release_fixture, refresh_report, read


class UsageRolloutTests(unittest.TestCase):
    def test_usage_allowlists_survive_compatible_feedback_only_release(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            current = release_fixture(root, "current")
            old = release_fixture(root, "old", b"old")
            weekly = read(current / "public/weekly.json")
            weekly["weeks"].append({"id": "2026-09-06", "tracks": []})
            weekly["voiceBank"] = {"speakers": [{"id": "jared_kirkwood"}]}
            write_json(current / "public/weekly.json", weekly)
            catalog = read(current / "feedback-catalog.json")
            catalog.update(weekIds=["2026-08-30", "2026-09-06"], voiceIds=["jared_kirkwood"])
            write_json(current / "feedback-catalog.json", catalog)
            refresh_report(current)
            merged, _, _ = deploy.merge_release_catalogs(current, [old])
            self.assertEqual(merged["weekIds"], ["2026-08-30", "2026-09-06"])
            self.assertEqual(merged["voiceIds"], ["jared_kirkwood"])
            self.assertEqual(len(merged["sources"]), 2)

    def test_rehashed_unknown_usage_context_is_rejected(self):
        for field, values in [("weekIds", ["2026-08-30", "2026-09-06"]), ("voiceIds", ["unknown"]), ("weekIds", ["2026-08-30", "2026-08-30"])]:
            with self.subTest(field=field, values=values), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                release = release_fixture(root, "current")
                catalog = read(release / "feedback-catalog.json")
                catalog.update(weekIds=["2026-08-30"], voiceIds=[])
                catalog[field] = values
                write_json(release / "feedback-catalog.json", catalog)
                refresh_report(release)
                with self.assertRaisesRegex(ValueError, "Usage allowlist"):
                    deploy.prepare(release, root / "api")
                self.assertFalse((root / "api").exists())
