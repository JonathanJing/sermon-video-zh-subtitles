from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).parents[2] / "scripts" / "score-soak-e2e.py"
SPEC = importlib.util.spec_from_file_location("score_soak_e2e", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class ScoreSoakE2ETest(unittest.TestCase):
    def test_scores_live_session_and_marks_integrity_pending(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "manifest.json").write_text(json.dumps({
                "sessionId": "test-session",
                "status": "recording",
                "eventFile": "events.jsonl",
            }), encoding="utf-8")
            events = [
                {"type": "asr.processing", "sequence": 1},
                {"type": "asr.processing", "sequence": 2},
                {"type": "asr.processing", "sequence": 3},
                {"type": "asr.final", "sequence": 4, "sourceTextEn": "The.",
                 "uxMetrics": {"asrQueueWaitMs": 0, "audioEndToAsrFinalMs": 100}},
                {"type": "asr.final", "sequence": 5, "sourceTextEn": "The.",
                 "uxMetrics": {"asrQueueWaitMs": 50, "audioEndToAsrFinalMs": 200}},
                {"type": "asr.final", "sequence": 6, "sourceTextEn": "迷惘。",
                 "uxMetrics": {"asrQueueWaitMs": 100, "audioEndToAsrFinalMs": 150}},
                {"type": "translation.started", "sequence": 7},
                {"type": "translation.final", "sequence": 8,
                 "uxMetrics": {"translationTtftMs": 50,
                               "audioEndToChineseFirstTokenMs": 250,
                               "audioEndToChineseFinalMs": 300}},
                {"type": "caption_rendered", "sequence": 9,
                 "renderKind": "chinese_first_token", "audioEndToBrowserRenderMs": 255},
            ]
            (root / "events.jsonl").write_text(
                "".join(json.dumps(event) + "\n" for event in events), encoding="utf-8"
            )
            telemetry = root / "telemetry.tsv"
            telemetry.write_text(
                "timestamp\telapsed_s\thealth\tgateway_rss_kb\tmlx_rss_kb\tollama_rss_kb\tpcm_bytes\tevent_lines\tswap\n"
                "now\t0\t200\t100\t200\t0\t10\t1\ttotal_=_0.00M__used_=_0.00M__free_=_0.00M__\n"
                "later\t10\t500\t130\t210\t0\t20\t4\ttotal_=_1.00M__used_=_1.00M__free_=_0.00M__\n",
                encoding="utf-8",
            )
            ollama_telemetry = root / "ollama.tsv"
            ollama_telemetry.write_text(
                "timestamp\telapsed_s\tollama_pid\tollama_rss_kb\n"
                "now\t0\t123\t400\n"
                "later\t10\t123\t450\n",
                encoding="utf-8",
            )
            health_telemetry = root / "health.tsv"
            health_telemetry.write_text(
                "timestamp\telapsed_s\thttp_code\tstatus\tasr_available\tlive_available\n"
                "now\t0\t200\tready\ttrue\ttrue\n"
                "later\t10\t500\tdegraded\tfalse\tfalse\n",
                encoding="utf-8",
            )

            result = MODULE.score(root, telemetry, ollama_telemetry, health_telemetry)

            self.assertEqual(result["failureEventCount"], 0)
            self.assertEqual(result["availability"]["gatewayHttp200Rate"], 0.5)
            self.assertEqual(result["availability"]["asrFinalRate"], 1.0)
            self.assertEqual(result["availability"]["translationFinalRate"], 1.0)
            self.assertEqual(result["latency"]["audioEndToAsrFinalMs"]["p50"], 150)
            self.assertEqual(result["latency"]["asrQueueWaitMs"]["max"], 100)
            self.assertEqual(result["telemetry"]["gatewayNon200Samples"], 1)
            self.assertEqual(result["telemetry"]["supplementalHealth"]["readySamples"], 1)
            self.assertEqual(result["telemetry"]["gatewayRss"]["growthKb"], 30)
            self.assertEqual(result["telemetry"]["ollamaRss"]["growthKb"], 50)
            self.assertEqual(result["telemetry"]["mlxProcessMissingSamples"], 0)
            self.assertEqual(result["telemetry"]["swapUsedMb"]["max"], 1.0)
            self.assertEqual(
                result["asr"]["shortRepeatedOutputCandidates"][0]["text"], "the."
            )
            self.assertEqual(result["asr"]["unexpectedCjkOutputCount"], 1)
            self.assertEqual(result["asr"]["unexpectedCjkOutputs"], ["迷惘。"])
            self.assertEqual(result["artifactIntegrity"], {"pending": True})


if __name__ == "__main__":
    unittest.main()
