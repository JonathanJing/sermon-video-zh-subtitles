"""Offline concurrency/barrier tests; no model or API calls."""
import json
import subprocess
import tempfile
import threading
import unittest
from types import SimpleNamespace
from pathlib import Path
from unittest.mock import patch

from scripts import sermon_pipeline as pipeline
from scripts import run_post_live_subtitle_generation as production
from scripts import sermon_accounting as accounting


class ParallelReadingTest(unittest.TestCase):
    def test_source_fingerprint_overlaps_asr_and_join_checks_failure(self):
        barrier = threading.Barrier(2)
        args = SimpleNamespace(fingerprint_precompute=True, input=Path("source"), reference_model="gpt-transcribe")
        def fingerprint(*args):
            barrier.wait(timeout=3)
            raise RuntimeError("fingerprint failed")
        def transcribe(*args, **kwargs):
            barrier.wait(timeout=3)
            return [{"text": "frozen"}]
        with patch.object(pipeline, "precompute_source_fingerprint", side_effect=fingerprint), \
             patch.object(pipeline, "transcribe_reference", side_effect=transcribe):
            with self.assertRaisesRegex(RuntimeError, "fingerprint failed"):
                pipeline.transcribe_with_fingerprint(args, "unused", Path("clip"), Path("out"), 10, {}, 3, 23)

    def test_asr_chunks_overlap_keep_order_and_accounting_context(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            clip = root / "clip.m4a"
            clip.write_bytes(b"audio")
            barrier = threading.Barrier(2)
            contexts = []

            def cut(_clip, dest, _start, _length):
                dest.parent.mkdir(exist_ok=True)
                dest.write_bytes(b"chunk")

            def transcribe(_key, _model, _prompt, audio, **kwargs):
                contexts.append(accounting.subprocess_environment()["SERMON_ACCOUNTING_STAGE"])
                barrier.wait(timeout=3)
                return {"text": audio.stem}

            with patch.object(pipeline, "ffprobe_duration", return_value=20), \
                 patch.object(pipeline, "cut_chunk", side_effect=cut), \
                 patch.object(pipeline, "transcribe_openai_audio", side_effect=transcribe), \
                 accounting.accounting_session(root / "accounting", "test"), \
                 accounting.stage("pipeline.transcribe"):
                chunks = pipeline.transcribe_reference_chunks("unused", clip, root, 10, "gpt-transcribe", {}, workers=2)
            self.assertEqual([c["text"] for c in chunks], ["chunk_0000", "chunk_0001"])
            self.assertEqual(contexts, ["pipeline.transcribe"] * 2)
            self.assertEqual(json.loads((root / "asr_reference_chunks.json").read_text()), chunks)

    def test_failed_asr_does_not_publish_aggregate_and_retains_successful_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            barrier = threading.Barrier(2)

            def cut(_clip, dest, _start, _length):
                dest.parent.mkdir(exist_ok=True)
                dest.write_bytes(b"chunk")

            def transcribe(_key, _model, _prompt, audio, **kwargs):
                barrier.wait(timeout=3)
                if audio.stem.endswith("0000"):
                    raise RuntimeError("provider unavailable")
                return {"text": "retained"}

            with patch.object(pipeline, "ffprobe_duration", return_value=20), \
                 patch.object(pipeline, "cut_chunk", side_effect=cut), \
                 patch.object(pipeline, "transcribe_openai_audio", side_effect=transcribe):
                with self.assertRaisesRegex(RuntimeError, "provider unavailable"):
                    pipeline.transcribe_reference_chunks("unused", root / "clip", root, 10, "gpt-transcribe", {}, workers=2)
            self.assertFalse((root / "asr_reference_chunks.json").exists())
            self.assertEqual(json.loads((root / "chunks_reference/chunk_0001.json").read_text())["text"], "retained")

    def test_pdf_branches_overlap_with_distinct_child_accounting_spans(self):
        with tempfile.TemporaryDirectory() as tmp:
            barrier = threading.Barrier(2)
            environments = {}

            def runner(command, *, check, env):
                environments[command[0]] = env
                barrier.wait(timeout=3)

            with accounting.accounting_session(Path(tmp), "test"):
                durations, wall = production.run_pdf_branches(["reading"], ["interpretation"], runner)
            self.assertEqual(environments["reading"]["SERMON_ACCOUNTING_STAGE"], "reading_pdf")
            self.assertEqual(environments["interpretation"]["SERMON_ACCOUNTING_STAGE"], "interpretation")
            self.assertNotEqual(environments["reading"]["SERMON_ACCOUNTING_SPAN"], environments["interpretation"]["SERMON_ACCOUNTING_SPAN"])
            self.assertEqual(environments["reading"]["SERMON_ACCOUNTING_RUN_ID"], environments["interpretation"]["SERMON_ACCOUNTING_RUN_ID"])
            self.assertGreaterEqual(wall, max(durations.values()))

    def test_notes_retry_preserves_frozen_hash_and_corruption_stops_without_api(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            english, chinese = root / "en.srt", root / "zh.srt"
            english.write_text("English")
            chinese.write_text("中文")
            notes = root / "insights/openai-notes.json"
            raw = root / "model/openai-notes-output.jsonl"
            command = ["python", "notes", "--out-dir", str(notes.parent), "--model-output-dir", str(raw.parent),
                       "--srt-input", str(chinese), "--secondary-srt-input", str(english), "--model", "gpt-6-astra"]
            calls = []
            def runner(command, **kwargs):
                calls.append(command)
                notes.parent.mkdir()
                raw.parent.mkdir()
                notes.write_text('{"status":"ready"}')
                raw.write_text('{}')
            production.run_frozen_interpretation_notes(command, runner)
            original = notes.read_bytes()
            production.run_frozen_interpretation_notes(command, runner)
            self.assertEqual(len(calls), 1)
            self.assertEqual(notes.read_bytes(), original)
            notes.write_text('{"status":"ready","changed":true}')
            with self.assertRaisesRegex(RuntimeError, "outputs changed"):
                production.run_frozen_interpretation_notes(command, runner)
            self.assertEqual(len(calls), 1)
            notes.write_bytes(original)
            english.write_text("Changed English")
            with self.assertRaisesRegex(RuntimeError, "inputs or outputs changed"):
                production.run_frozen_interpretation_notes(command, runner)
            self.assertEqual(len(calls), 1)

    def test_dubbing_waits_for_notes_and_overlaps_pdf_render(self):
        notes_done = threading.Event()
        rendering = threading.Barrier(2)
        candidate_done = threading.Event()
        interpretation = ["notes", "--out-dir", "/tmp/insights", "--pdf-out", "/tmp/outline.pdf", "--pdf-qa-out", "/tmp/outline.qa.json"]

        def runner(command, **kwargs):
            if command[0] == "notes":
                self.assertNotIn("--pdf-out", command)
                notes_done.set()
            elif "--input" in command:
                rendering.wait(timeout=3)

        def hook(config, week, run, executor):
            self.assertTrue(notes_done.is_set())
            def candidate():
                rendering.wait(timeout=3)
                candidate_done.set()
                return {"status": "waiting_conversation_review", "published": False}
            return executor.submit(candidate)

        with patch.object(production, "run_frozen_interpretation_notes", side_effect=lambda command, runner: runner(command)):
            durations, wall, candidate = production.run_pdf_and_dubbing_branches(
                ["reading"], interpretation, runner, config_path=Path("config.json"),
                week="2026-09-20", run_root=Path("run"), producer_hook=hook,
            )
        self.assertTrue(candidate_done.is_set())
        self.assertFalse(candidate["published"])
        self.assertGreaterEqual(durations["pdf_dubbing_wall"], wall)

    def test_missing_voice_configuration_does_not_block_pdf_branch(self):
        class NotReady(Exception):
            status, reason = "waiting_voice_config", "No configured voice for this week"
        def hook(*args):
            raise NotReady()
        hook.not_ready_exception = NotReady
        calls = []
        with patch.object(production, "run_frozen_interpretation_notes"):
            _, _, candidate = production.run_pdf_and_dubbing_branches(
                ["reading"], ["notes", "--out-dir", "/tmp/insights", "--pdf-out", "/tmp/pdf", "--pdf-qa-out", "/tmp/qa"],
                lambda command, **kwargs: calls.append(command), config_path=Path("config"), week="2026-09-20",
                run_root=Path("run"), producer_hook=hook,
            )
        self.assertEqual(candidate["status"], "waiting_voice_config")
        self.assertFalse(candidate["published"])
        self.assertEqual(len(calls), 2)

    def test_dubbing_failure_blocks_join(self):
        def hook(config, week, run, executor):
            def fail():
                raise RuntimeError("candidate failure")
            return executor.submit(fail)

        with patch.object(production, "run_frozen_interpretation_notes"), self.assertRaisesRegex(RuntimeError, "candidate failure"):
            production.run_pdf_and_dubbing_branches(
                ["reading"], ["notes", "--out-dir", "/tmp/insights", "--pdf-out", "/tmp/pdf", "--pdf-qa-out", "/tmp/qa"],
                lambda *args, **kwargs: None, config_path=Path("config"), week="2026-09-20",
                run_root=Path("run"), producer_hook=hook,
            )

    def test_failed_pdf_waits_for_running_sibling_before_propagating(self):
        barrier = threading.Barrier(2)
        sibling_done = threading.Event()

        def runner(command, **kwargs):
            barrier.wait(timeout=3)
            if command == ["reading"]:
                raise subprocess.CalledProcessError(1, command)
            sibling_done.set()

        with self.assertRaises(subprocess.CalledProcessError):
            production.run_pdf_branches(["reading"], ["interpretation"], runner)
        self.assertTrue(sibling_done.is_set())


if __name__ == "__main__":
    unittest.main()
