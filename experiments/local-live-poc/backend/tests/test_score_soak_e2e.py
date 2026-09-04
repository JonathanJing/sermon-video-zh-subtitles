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
    def test_delivery_accounting_distinguishes_guard_skips_missing_and_duplicate_mappings(self) -> None:
        events = [{"type": "asr.final", "segmentId": source} for source in ("a", "b", "c", "d")]
        events += [
            {"type": "translation.final", "segmentId": "b", "sourceSegmentIds": ["a", "b"]},
            {"type": "caption_rendered", "segmentId": "b", "renderKind": "readable_partial_first"},
            {"type": "caption_rendered", "segmentId": "b", "renderKind": "readable_final"},
            {"type": "translation.skipped", "segmentId": "c", "reason": "insufficient_lexical_content", "sourceSegmentIds": ["c"]},
            {"type": "translation.skipped", "segmentId": "c", "reason": "insufficient_lexical_content", "sourceSegmentIds": ["c"]},
        ]
        result = MODULE.delivery_accounting(events)
        self.assertEqual(result["rawFinalCount"], 4)
        self.assertEqual(result["visibleMappedRawFinalCount"], 2)
        self.assertEqual(result["lexicalGuardSkippedRawFinalIds"], ["c"])
        self.assertEqual(result["lexicalGuardSkippedRawFinalCount"], 1)
        self.assertEqual(result["otherMissingRawFinalIds"], ["d"])
        self.assertEqual(result["duplicateMappedRawFinalIds"], [])
        self.assertEqual(result["lexicalGuardReviewStatus"], "policy_decision_not_human_reviewed")
        # The original visible coverage still counts the unreviewed policy skip.
        self.assertEqual(MODULE.caption_delivery(events, {})["firstVisibleCoverageRate"], 0.5)
        events += [
            {"type": "translation.final", "segmentId": "d", "sourceSegmentIds": ["a", "d"]},
            {"type": "caption_rendered", "segmentId": "d", "renderKind": "readable_final_first"},
        ]
        duplicate = MODULE.delivery_accounting(events)
        self.assertEqual(duplicate["visibleMappedRawFinalCount"], 3)
        self.assertEqual(duplicate["duplicateMappedRawFinalIds"], ["a"])
        self.assertEqual(duplicate["otherMissingRawFinalIds"], [])

    def test_merged_unit_covers_each_raw_final_and_measures_first_source_wait(self) -> None:
        events = [
            {"type": "asr.final", "segmentId": "one", "audioStartMs": 0, "audioEndMs": 3000},
            {"type": "asr.final", "segmentId": "two", "audioStartMs": 3000, "audioEndMs": 6000},
            {"type": "translation.final", "segmentId": "two", "translationUnitId": "unit-one--two", "sourceSegmentIds": ["one", "two"]},
            # Older frontend logging need not repeat metadata already in the translation event.
            {"type": "caption_rendered", "segmentId": "two", "renderKind": "readable_final_first",
             "audioEndToBrowserRenderMs": 1600, "elapsedMs": 7600},
        ]
        result = MODULE.caption_delivery(events, {"durationMs": 8000})
        self.assertEqual(result["asrFinalSegmentCount"], 2)
        self.assertEqual(result["translationFinalUnitCount"], 1)
        self.assertEqual(result["firstVisibleSegmentCount"], 2)
        self.assertEqual(result["firstVisibleCoverageRate"], 1)
        self.assertEqual(result["missingFirstVisibleSegmentIds"], [])
        self.assertEqual(result["audioEndToBrowserFirstVisibleMs"]["p50"], 1600)
        self.assertEqual(result["firstSourceAudioEndToBrowserFirstVisibleMs"]["p50"], 4600)
        self.assertEqual(result["audioStartToBrowserFirstVisibleMs"]["p50"], 7600)
        evidence = MODULE.measurement_evidence(
            {"status": "completed"}, result, {"recording": {"sha256Matches": True}},
            MODULE.Counter({"asr.processing": 2, "asr.final": 2}), 0, None,
        )
        for check in ("translationCoverage", "firstVisibleCoverage", "finalVisibleCoverage", "firstVisibleTiming", "speechStartTiming", "firstSourceEndTiming"):
            self.assertEqual(evidence["checks"][check], "pass")
        # A claimed but absent source final cannot become delivered evidence.
        events[2]["sourceSegmentIds"].append("missing")
        invalid = MODULE.caption_delivery(events, {"durationMs": 8000})
        self.assertEqual(invalid["unknownSourceSegmentIds"], ["missing"])
        self.assertEqual(invalid["firstVisibleLatencySampleCount"], 0)

    def test_legacy_and_readable_browser_delivery_have_the_same_coverage_contract(self) -> None:
        for first_kind, final_kind in (("chinese_first_token", "chinese_final"), ("readable_partial_first", "readable_final")):
            with self.subTest(first_kind=first_kind):
                events = [
                    {"type": "asr.final", "segmentId": "one", "audioStartMs": 1000, "audioEndMs": 4000},
                    {"type": "asr.final", "segmentId": "two", "audioStartMs": 7000, "audioEndMs": 10000},
                    {"type": "translation.final", "segmentId": "one"},
                    {"type": "translation.final", "segmentId": "two"},
                    {"type": "caption_rendered", "segmentId": "one", "renderKind": first_kind,
                     "audioEndToBrowserRenderMs": 1500, "elapsedMs": 5500},
                    {"type": "caption_rendered", "segmentId": "one", "renderKind": final_kind,
                     "audioEndToBrowserRenderMs": 1700, "elapsedMs": 5700},
                    # A final can be the first visible update, with no token flash.
                    {"type": "caption_rendered", "segmentId": "two", "renderKind": "readable_final_first",
                     "audioEndToBrowserRenderMs": 1600, "elapsedMs": 11600},
                ]
                result = MODULE.caption_delivery(events, {"durationMs": 14000})
                self.assertEqual(result["firstVisibleCoverageRate"], 1)
                self.assertEqual(result["finalVisibleCoverageRate"], 1)
                self.assertEqual(result["audioEndToBrowserFirstVisibleMs"]["p50"], 1550)
                self.assertEqual(result["audioEndToBrowserFinalVisibleMs"]["max"], 1700)
                self.assertEqual(result["audioStartToBrowserFirstVisibleMs"]["max"], 4600)
                self.assertEqual(result["cadence"]["longestNoNewCaptionIntervalMs"], 5900)
                self.assertEqual(result["cadence"]["trailingNoNewCaptionMs"], 2400)

    def test_missing_browser_delivery_is_not_zero_latency_or_a_pass(self) -> None:
        events = [{"type": "asr.final", "segmentId": "missing", "audioStartMs": 0, "audioEndMs": 3000}]
        delivery = MODULE.caption_delivery(events, {"durationMs": 60000})
        self.assertEqual(delivery["missingFirstVisibleSegmentIds"], ["missing"])
        self.assertEqual(delivery["firstVisibleCoverageRate"], 0)
        self.assertIsNone(delivery["audioEndToBrowserFirstVisibleMs"]["max"])
        self.assertIsNone(delivery["cadence"]["longestNoNewCaptionIntervalMs"])
        evidence = MODULE.measurement_evidence(
            {"status": "completed"}, delivery, {"recording": {"sha256Matches": None}},
            MODULE.Counter({"asr.processing": 1, "asr.final": 1}), 0, None,
        )
        self.assertFalse(evidence["passed"])
        self.assertEqual(evidence["checks"]["firstVisibleCoverage"], "fail")
        self.assertEqual(evidence["checks"]["healthReady"], "missing")
        self.assertEqual(evidence["checks"]["cleanRuntimeRevision"], "missing")

    def test_browser_timestamp_fallback_and_incomplete_timeline(self) -> None:
        manifest = {"startedAt": "2026-09-04T12:00:00Z", "durationMs": 1000}
        # Safe drain can render after the recording duration; do not make its gap negative.
        events = [{"type": "caption_rendered", "segmentId": "one", "renderKind": "readable_final_first", "browserRenderedAt": "2026-09-04T12:00:02Z"}]
        result = MODULE.caption_delivery(events, manifest)
        self.assertEqual(result["cadence"]["trailingNoNewCaptionMs"], 0)
        self.assertEqual(result["cadence"]["firstCaptionAfterSessionStartMs"], 2000)
        events.append({"type": "caption_rendered", "segmentId": "two"})
        self.assertFalse(MODULE.caption_delivery(events, manifest)["cadence"]["completeTimeline"])
        self.assertIsNone(MODULE.caption_delivery(events, manifest)["cadence"]["longestNoNewCaptionIntervalMs"])

    def test_resource_sampler_tsv_is_read_directly_and_bad_swap_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "resources.tsv"
            path.write_text(
                "elapsed_s\thttp_code\tstatus\tasr_available\tlive_available\tswap_used_mb\n"
                "0.1\t200\tready\ttrue\ttrue\t0.0\n"
                "10.2\t200\tready\ttrue\t\tfree\n", encoding="utf-8",
            )
            result = MODULE.load_telemetry(path)
        self.assertEqual(result["elapsedSeconds"], 10.2)
        self.assertEqual(result["supplementalHealth"]["liveAvailableSampleCount"], 1)
        self.assertEqual(result["swapUsedMb"]["sampleCount"], 1)
        self.assertEqual(result["swapUsedMb"]["expectedSampleCount"], 2)
        self.assertEqual(MODULE.swap_used_mb("total = 2.00G used = 1.25G free = 0.75G"), 1280)

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
