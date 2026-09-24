"""Run the checked-in main promotion job against a local Git remote."""

import os
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
import textwrap
import unittest


WORKFLOW = Path(__file__).resolve().parents[1] / ".github/workflows/branch-promotion.yml"
REPOSITORY = "JonathanJing/sermon-video-zh-subtitles"


class PromotionPolicyTest(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.repo = root / "repo"
        self.remote = root / "remote.git"
        self.repo.mkdir()
        self.git("init", "-q", "-b", "main")
        self.git("config", "user.email", "ci@example.test")
        self.git("config", "user.name", "CI")
        (self.repo / "baseline").write_text("base")
        self.git("add", "-A")
        self.git("commit", "-qm", "base")
        self.git("switch", "-qc", "dev")
        (self.repo / "feature").write_text("reviewed")
        self.git("add", "-A")
        self.git("commit", "-qm", "reviewed")
        self.dev_sha = self.git("rev-parse", "HEAD").strip()
        subprocess.run(["git", "init", "--bare", "-q", str(self.remote)], check=True)
        self.git("remote", "add", "origin", str(self.remote))
        self.git("push", "-q", "origin", "main", "dev")
        text = WORKFLOW.read_text()
        self.script = textwrap.dedent(text.split("        run: |\n", 1)[1])

    def git(self, *args):
        return subprocess.check_output(["git", *args], cwd=self.repo, text=True)

    def check(self, branch, sha, head_repository=REPOSITORY):
        env = {**os.environ, "HEAD_BRANCH": branch, "HEAD_REPOSITORY": head_repository,
               "EXPECTED_REPOSITORY": REPOSITORY, "HEAD_SHA": sha}
        return subprocess.run(["bash", "-c", self.script], cwd=self.repo, env=env,
                              capture_output=True, text=True)

    def test_dev_and_frozen_reviewed_release_are_admitted(self):
        self.assertEqual(self.check("dev", self.dev_sha).returncode, 0)
        self.assertEqual(self.check("release/2026-W39", self.dev_sha).returncode, 0)

    def test_unreviewed_release_commit_and_other_repository_are_rejected(self):
        self.git("switch", "-qc", "release/2026-W39")
        (self.repo / "unreviewed").write_text("not in dev")
        self.git("add", "-A")
        self.git("commit", "-qm", "unreviewed")
        self.assertNotEqual(self.check("release/2026-W39", self.git("rev-parse", "HEAD").strip()).returncode, 0)
        self.assertNotEqual(self.check("dev", self.dev_sha, "fork/example").returncode, 0)
        self.assertNotEqual(self.check("feature/skip", self.dev_sha).returncode, 0)


if __name__ == "__main__":
    unittest.main()
