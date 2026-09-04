from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from backend.retention import apply_retention, retention_plan


class RetentionTest(unittest.TestCase):
    def _session(self, root: Path, name: str, stopped_at: str, status: str = "completed") -> Path:
        directory = root / name
        directory.mkdir()
        (directory / "manifest.json").write_text(json.dumps({"status": status, "stoppedAt": stopped_at}))
        (directory / "recording.webm").write_bytes(b"audio")
        return directory

    def test_preview_protects_recent_latest_and_recording_sessions(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            old = self._session(root, "old", "2026-01-01T00:00:00Z")
            self._session(root, "new", "2026-09-03T00:00:00Z")
            self._session(root, "active", "2026-01-01T00:00:00Z", "recording")
            plan = retention_plan(root, retention_days=30, keep_latest=1, now=datetime(2026, 9, 4, tzinfo=timezone.utc))
            self.assertEqual([item["sessionId"] for item in plan["delete"]], ["old"])
            self.assertTrue(old.is_dir())

    def test_apply_deletes_only_planned_direct_child(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            old = self._session(root, "old", "2026-01-01T00:00:00Z")
            plan = retention_plan(root, retention_days=30, keep_latest=0, now=datetime(2026, 9, 4, tzinfo=timezone.utc))
            self.assertEqual(apply_retention(plan), ["old"])
            self.assertFalse(old.exists())


if __name__ == "__main__":
    unittest.main()
