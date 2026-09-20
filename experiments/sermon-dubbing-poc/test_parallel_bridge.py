"""No models: prove deferred package gates and producer/PDF overlap."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from poc import write_json
import continue_saturday_dubbing as bridge
import weekly_dubbing as weekly
import test_saturday_bridge as fixtures


class ParallelBridgeTests(unittest.TestCase):
    def test_candidate_starts_before_pdf_and_completed_package_cannot_be_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixture = fixtures.SaturdayBridgeTests()
            cfg, _, _, run = fixture.fixture(root)
            run = run.resolve()
            for key in ('readingPdf', 'companionPdf', 'readingPdfQa', 'companionPdfQa'):
                (run / bridge.INPUTS[key]).unlink()
            started, finish = threading.Event(), threading.Event()
            def runner(command, **kwargs):
                started.set()
                if not finish.wait(5):
                    raise AssertionError('PDF branch did not overlap candidate')
                return SimpleNamespace(returncode=0)
            with patch('weekly_dubbing.probe', return_value={'durationSeconds': 10}), ThreadPoolExecutor(max_workers=1) as pool:
                future = bridge.start_producer_candidate(cfg, fixture.week, run, pool, root=root,
                    media_probe=lambda _: {'durationSeconds': 10}, runner=runner, validator=lambda _: {'synthetic': True})
                try:
                    self.assertTrue(started.wait(5))
                    jobs = list((root / 'bridge-output').rglob('job.json'))
                    self.assertEqual(len(jobs), 1)
                    job = weekly.read(jobs[0])
                    self.assertEqual(job['schemaVersion'], 'sermon-weekly-dubbing-job-v2')
                    self.assertFalse(weekly.PDF_PACKAGE_KEYS.intersection(job['inputs']))
                    weekly.validate_frozen(job)
                    with self.assertRaisesRegex(ValueError, 'not complete'):
                        weekly.completed_package_job(job)
                    # PDF completion does not require rewriting job.json or regenerating audio.
                    for key in ('readingPdf', 'companionPdf'):
                        (run / bridge.INPUTS[key]).write_bytes(b'finished PDF')
                    for key in ('readingPdfQa', 'companionPdfQa'):
                        write_json(run / bridge.INPUTS[key], {'status': 'pass'})
                    write_json(run / 'agent-generation-report.json', {'status': 'completed'})
                    with patch('continue_saturday_dubbing.probe', return_value={'durationSeconds': 10}):
                        # Default probe was bound at function definition; pass verified fixture inputs.
                        inputs, _ = bridge.validate_live_inputs(run, fixture.week, root=root,
                            media_probe=lambda _: {'durationSeconds': 10})
                        with patch('continue_saturday_dubbing.validate_live_inputs', return_value=(inputs, None)):
                            completed = weekly.completed_package_job(job)
                    self.assertIn('readingPdf', completed['inputs'])
                    self.assertNotIn('readingPdf', job['inputs'])
                finally:
                    finish.set()
                self.assertEqual(future.result()['status'], 'waiting_conversation_review')
                config = weekly.read(cfg)
                report, plan = bridge.plan_candidate(config, cfg, fixture.week, {}, None, run,
                    fixture.source, inputs, {}, route='live_archive', root=root, validator=lambda _: {})
                self.assertEqual(plan['work'].resolve(), jobs[0].parent.resolve())
                self.assertEqual(len(list((root / 'bridge-output').rglob('job.json'))), 1)

    def test_real_producer_loader_separates_readiness_wait_from_invalid_evidence(self):
        from scripts.run_post_live_subtitle_generation import load_dubbing_producer_hook
        hook, not_ready = load_dubbing_producer_hook()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixture = fixtures.SaturdayBridgeTests()
            cfg, _, config, run = fixture.fixture(root)
            with ThreadPoolExecutor(max_workers=1) as pool:
                with self.assertRaises(not_ready) as missing:
                    hook(root / "missing.json", fixture.week, run, pool)
                self.assertEqual(missing.exception.status, "waiting_configuration")
                self.assertTrue(missing.exception.reason)
                config["voiceRuns"] = {}
                write_json(cfg, config)
                with self.assertRaises(not_ready) as voice:
                    hook(cfg, fixture.week, run, pool, root=root, media_probe=lambda _: {"durationSeconds": 10})
                self.assertEqual(voice.exception.status, "waiting_voice")
                (run / "pipeline/source_clip.m4a.cache.json").write_text('{"source":{"sha256":"changed"},"startSeconds":10,"endSeconds":20}')
                with self.assertRaises(ValueError):
                    hook(cfg, fixture.week, run, pool, root=root, media_probe=lambda _: {"durationSeconds": 10})
                write_json(cfg, {"schemaVersion": "invalid"})
                with self.assertRaises(ValueError):
                    hook(cfg, fixture.week, run, pool)

    def test_source_identity_supports_both_producer_run_prefixes(self):
        self.assertEqual(weekly.source_id_from_run(Path('/tmp/mariners_abc-123')), 'abc-123')
        self.assertEqual(weekly.source_id_from_run(Path('/tmp/sermon_abc-123')), 'abc-123')
        with self.assertRaises(ValueError):
            weekly.source_id_from_run(Path('/tmp/unknown_abc'))

    def test_deferred_flag_cannot_relabel_a_v1_job(self):
        with self.assertRaisesRegex(ValueError, 'explicit v2'):
            weekly.validate_frozen({'schemaVersion': 'sermon-weekly-dubbing-job-v1',
                'pdfPackagePolicy': 'deferred_until_release', 'inputs': {}})
