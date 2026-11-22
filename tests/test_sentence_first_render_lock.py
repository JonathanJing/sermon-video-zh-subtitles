"""One renderer at a time: the advisory lock refuses a second render and lets the next one in."""

import json
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE / "experiments" / "sentence-first-agent"))

import render_lock  # noqa: E402


class RenderLockTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.lock = Path(self.tmp.name) / "render.lock"

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_second_acquire_is_refused_while_held(self) -> None:
        handle = render_lock.acquire("zh-Hans", path=self.lock, label="test")
        try:
            with self.assertRaises(SystemExit) as caught:
                render_lock.acquire("ko", path=self.lock)
            self.assertIn("one model copy", str(caught.exception))
        finally:
            render_lock.release(handle)

    def test_release_allows_the_next_render(self) -> None:
        first = render_lock.acquire("zh-Hans", path=self.lock)
        render_lock.release(first)
        second = render_lock.acquire("ko", path=self.lock)
        render_lock.release(second)
        self.assertEqual(render_lock.holder(self.lock)["out"], "ko")

    def test_holder_reports_pid_and_out(self) -> None:
        handle = render_lock.acquire("es", path=self.lock, label="tts:mps")
        try:
            holder = render_lock.holder(self.lock)
            self.assertEqual(holder["out"], "es")
            self.assertEqual(holder["label"], "tts:mps")
            self.assertIsInstance(holder["pid"], int)
        finally:
            render_lock.release(handle)

    def test_allow_concurrent_skips_the_lock(self) -> None:
        handle = render_lock.acquire("zh-Hans", path=self.lock)
        try:
            self.assertIsNone(render_lock.acquire("ko", path=self.lock, allow_concurrent=True))
        finally:
            render_lock.release(handle)

    def test_context_manager_releases(self) -> None:
        with render_lock.locked("zh-Hans", path=self.lock):
            with self.assertRaises(SystemExit):
                render_lock.acquire("ko", path=self.lock)
        again = render_lock.acquire("ko", path=self.lock)
        render_lock.release(again)

    def test_missing_file_has_no_holder(self) -> None:
        self.assertIsNone(render_lock.holder(self.lock))


if __name__ == "__main__":
    unittest.main()
