from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.runtime_identity import collect_runtime_identity


class RuntimeIdentityTest(unittest.TestCase):
    def test_identity_is_stable_and_does_not_collect_unknown_or_nested_settings(self) -> None:
        with patch("backend.runtime_identity._git_identity", return_value={"revision": "a" * 40, "dirty": False, "available": True}):
            first = collect_runtime_identity({
                "translationModel": "model-a", "vadMaxSegmentMs": 3000,
                "API_KEY": "secret-marker", "authorization": "secret-marker",
                "asrProvider": {"token": "secret-marker"},
            }, versions={"ollama": "0.33.3", "token": "secret-marker"})
            second = collect_runtime_identity({"vadMaxSegmentMs": 3000, "translationModel": "model-a"}, versions={"ollama": "0.33.3"})
            changed = collect_runtime_identity({"vadMaxSegmentMs": 6000, "translationModel": "model-a"}, versions={"ollama": "0.33.3"})
        self.assertEqual(first["fingerprintSha256"], second["fingerprintSha256"])
        self.assertNotEqual(first["fingerprintSha256"], changed["fingerprintSha256"])
        self.assertNotIn("secret-marker", json.dumps(first, allow_nan=False))
        self.assertNotIn("asrProvider", first["configuration"])

    def test_git_unknown_is_not_mislabeled_as_clean(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            identity = collect_runtime_identity({}, repo_path=Path(temporary))
        self.assertEqual(identity["git"], {"revision": None, "dirty": None, "available": False})

    def test_git_revision_and_untracked_dirty_state_are_captured_without_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)

            def git(*args: str) -> str:
                return subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True, text=True).stdout.strip()

            git("init")
            git("-c", "user.name=Runtime Test", "-c", "user.email=runtime@example.invalid", "commit", "--allow-empty", "-m", "test")
            clean = collect_runtime_identity({}, repo_path=root)
            (root / "private-config-name.txt").write_text("secret-marker", encoding="utf-8")
            dirty = collect_runtime_identity({}, repo_path=root)
            self.assertEqual(clean["git"]["revision"], git("rev-parse", "HEAD"))
        self.assertFalse(clean["git"]["dirty"])
        self.assertTrue(dirty["git"]["dirty"])
        self.assertNotEqual(clean["fingerprintSha256"], dirty["fingerprintSha256"])
        self.assertNotIn("private-config-name", json.dumps(dirty))
        self.assertNotIn("secret-marker", json.dumps(dirty))


if __name__ == "__main__":
    unittest.main()
