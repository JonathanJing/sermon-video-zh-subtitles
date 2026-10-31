import json
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE / "tools" / "development"))

import export_run_digest as E  # noqa: E402


class DigestStateSectionTest(unittest.TestCase):
    def make(self, root: Path, consistent: bool) -> Path:
        dest = root / "digest"
        run = dest / "run-a"
        run.mkdir(parents=True)
        payload = {
            "consistent": consistent,
            "missing": ["s7"] if not consistent else [],
            "labels": [{"label": "translate",
                        "rebuilt": {"status": "finished", "windowsDone": 4, "unitsDone": 48,
                                    "calls": 6, "hits": 0, "failed": 0},
                        "mismatches": [] if consistent else ["windowsDone: live=9 rebuilt=4"]}],
        }
        (run / "state-check.json").write_text(json.dumps(payload), encoding="utf-8")
        return dest

    def test_consistent_state_appears_in_index(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest = self.make(Path(tmp), True)
            text = E.index_markdown("t", dest, [], [{"label": "run-a", "source": "src", "skipped": {}}])
            self.assertIn("DeepSeek 状态", text)
            self.assertIn("**一致**", text)
            self.assertIn("窗口 4", text)
            self.assertIn("句 48", text)

    def test_mismatch_and_missing_are_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest = self.make(Path(tmp), False)
            text = E.index_markdown("t", dest, [], [{"label": "run-a", "source": "src", "skipped": {}}])
            self.assertIn("**不一致**", text)
            self.assertIn("未覆盖句子 1", text)
            self.assertIn("windowsDone: live=9 rebuilt=4", text)


if __name__ == "__main__":
    unittest.main()
