import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
SCRIPT = HERE / "experiments" / "sentence-first-agent" / "state_check.py"


def make_run(root: Path, label: str = "translate", windows: int = 2) -> Path:
    run = root / "run"
    run.mkdir()
    events = [{"label": label, "model": "deepseek-flash", "effort": "low", "status": "ok",
               "promptTokens": 100, "completionTokens": 100} for _ in range(windows)]
    events.append({"label": label, "status": "finished"})
    (run / "events.jsonl").write_text("".join(json.dumps(row) + "\n" for row in events), encoding="utf-8")
    done = [{"label": label, "context": f"w{number}", "kind": "window", "ids": [f"s{number}"]}
            for number in range(windows)]
    (run / "done.jsonl").write_text("".join(json.dumps(row) + "\n" for row in done), encoding="utf-8")
    (run / "sentences.jsonl").write_text(
        "".join(json.dumps({"id": f"s{number}", "english": "x"}) + "\n" for number in range(windows + 1)),
        encoding="utf-8")
    sys.path.insert(0, str(HERE / "experiments" / "sentence-first-agent"))
    import coherence_core as C
    rebuilt = C.rebuild_state(run)
    (run / f"state-{label}.json").write_text(json.dumps(rebuilt), encoding="utf-8")
    return run


def run_cli(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True, text=True)


class StateCheckCliTest(unittest.TestCase):
    def test_consistent_run_exits_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = make_run(Path(tmp))
            result = run_cli("--run", str(run))
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("consistent", result.stdout)

    def test_mismatch_exits_one_and_write_repairs(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = make_run(Path(tmp))
            state = json.loads((run / "state-translate.json").read_text())
            state["windowsDone"] = 99
            (run / "state-translate.json").write_text(json.dumps(state))
            broken = run_cli("--run", str(run), "--label", "translate")
            self.assertEqual(broken.returncode, 1)
            self.assertIn("MISMATCH", broken.stdout)
            repaired = run_cli("--run", str(run), "--label", "translate", "--write")
            self.assertEqual(repaired.returncode, 0)
            self.assertEqual(run_cli("--run", str(run)).returncode, 0)

    def test_all_labels_and_missing_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = make_run(Path(tmp), windows=2)
            events = (run / "events.jsonl").read_text()
            (run / "events.jsonl").write_text(
                events + json.dumps({"label": "audit", "status": "ok", "promptTokens": 1,
                                     "completionTokens": 1}) + "\n")
            done = (run / "done.jsonl").read_text()
            (run / "done.jsonl").write_text(
                done + json.dumps({"label": "audit", "context": "s0", "kind": "window",
                                   "ids": ["s0"]}) + "\n")
            sys.path.insert(0, str(HERE / "experiments" / "sentence-first-agent"))
            import coherence_core as C
            (run / "state-audit.json").write_text(json.dumps(C.rebuild_state(run, "audit")))
            result = run_cli("--run", str(run), "--all", "--source-run", str(run),
                             "--missing", "--record")
            self.assertIn("audit: consistent", result.stdout)
            self.assertIn("uncovered sentences: 1", result.stdout)
            self.assertEqual(result.returncode, 1)  # one sentence is not covered yet
            recorded = json.loads((run / "state-check.json").read_text())
            self.assertEqual([item["label"] for item in recorded["labels"]], ["audit", "translate"])


if __name__ == "__main__":
    unittest.main()
