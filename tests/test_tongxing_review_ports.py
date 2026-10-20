"""R0 of the review move: cross-layer review's ports are bound late to the scripts implementations.

Each batch (R1-R4) switches its files over to these ports when it moves them; the
first caller is the audio screening gate (L4 D2a), which reads ``waivers`` and ``schemas``. These tests pin that every port reaches the implementation the
callers use today, with the paths and values those callers compute today, and that
binding them imports no waiver-closure file.
"""
import builtins
import dataclasses
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

from scripts import tongxing_host as host
from tongxing_production.source import english_source_package as english_package
from scripts import cuv_scripture, english_scripture_coverage, scripture_candidate_queue, scripture_editions
from tongxing_production.source import english_source_judge_cache as judge_cache
from tools.development import export_run_digest
from tongxing_production.compute.transports import codex_cli as sermon_codex_transport
from tongxing_production.compute import transcription_request as sermon_transcription_request
from tongxing_production.text import human_ruling
from tongxing_production.compute import qc_audio_transports as audio_transports
from tongxing_production.review import waiver
from tongxing_production.audio import speech_job as handoff
from tongxing_production.text import candidate
from tongxing_production.compute import spark_admission as production_spark_admission
from tongxing_production.compute import spark_exclusive_session
from tongxing_production.audio import renderer
from tongxing_production.source import sentence_interpretation_models as interpretation_models
from tongxing_production.audio import screening
from tongxing_production.review import scripture_machine
from scripts import sermon_production_supervisor as supervisor
from tongxing_production.source import sentence_interpretation as interpretation
from tongxing_production.source import budget as source_budget
from tongxing_production.source import text_review
from tongxing_production.delivery import study_artifacts
from tongxing_production.audio import predicted_schedule as predicted
from tongxing_production.text import policy
from tongxing_production import ports
from tongxing_production.delivery import backend as delivery
from tongxing_production.review import backend as review
from tongxing_production.text import backend as text


def assert_reaches(case, calls):
    """Each (module, name, port, args, kwargs) port call lands once on module.name with the same arguments."""
    for module, name, port, args, kwargs in calls:
        with case.subTest(name=name), patch.object(module, name, return_value=name) as target:
            case.assertEqual(port(*args, **kwargs), name)
            target.assert_called_once_with(*args, **kwargs)


class ReviewPortsTests(unittest.TestCase):
    def test_host_binds_a_complete_backend_sharing_records_with_the_stages(self):
        backend = review.current()
        self.assertIsInstance(backend, review.ReviewBackend)
        self.assertEqual([field.name for field in dataclasses.fields(review.ReviewBackend)],
                         ['core', 'code', 'snapshot', 'schemas', 'provider', 'compute', 'plugins',
                          'transports', 'audio', 'text', 'source', 'gates', 'scripture', 'qc_runtime', 'waivers'])
        # The audio screening gate (L4 D2a) accepts the machine audio waiver the release discloses.
        self.assertIs(backend.waivers, delivery.current().waivers)
        for name in ('core', 'code', 'snapshot', 'schemas', 'provider', 'compute', 'plugins',
                     'transports'):
            self.assertIs(getattr(backend, name), getattr(text.current(), name), name)
        for record, kind in ((backend.audio, ports.AudioRules), (backend.text, ports.TextRules),
                             (backend.source, ports.SourceEvidence), (backend.gates, ports.StageGates),
                             (backend.scripture, ports.Scripture), (backend.qc_runtime, ports.QcRuntime)):
            self.assertIsInstance(record, kind)

    def test_implementation_path_reads_every_closure_key_where_the_waiver_reads_it(self):
        code = review.current().code
        for name in waiver.IMPLEMENTATION_FILES:
            with self.subTest(name=name):
                self.assertEqual(code.implementation_path(name), waiver.implementation_path(name, host.ROOT))
                self.assertTrue(code.implementation_path(name).is_file())
        # The scripture generator will locate its siblings by their legacy keys (R2):
        # every input must resolve, or the generator hash silently records None.
        for name in scripture_machine.GENERATOR_MODULES:
            with self.subTest(name=name):
                self.assertTrue(code.implementation_path('scripts/' + name).is_file())

    def test_review_proxy_and_backend_bytes_invalidate_waiver_identity(self):
        keys = ('packages/production/src/tongxing_production/review/unmoved.py',
                'packages/production/src/tongxing_production/review/backend.py')
        baseline = waiver.implementation_sha256()
        original = Path.read_bytes
        for key in keys:
            with self.subTest(key=key):
                target = host.ROOT / key
                with patch.object(Path, 'read_bytes',
                                  lambda path: original(path) + b'\n# changed binding\n'
                                  if path == target else original(path)):
                    self.assertNotEqual(waiver.implementation_sha256(), baseline)

    def test_audio_rules_reach_layer_3(self):
        audio = review.current().audio
        assert_reaches(self, (
            (predicted, 'synthesis_identity', audio.synthesis_identity, ({'j': 1},), {}),
            (predicted, '_check_identity', audio.check_identity, ({'i': 1}, 'ko'), {}),
            (predicted, 'policy_texts', audio.policy_texts, (['a'], 'ko', None), {}),
            (predicted, 'speech_units', audio.speech_units, ('a', 'ko'), {}),
            (predicted, 'budget', audio.budget, (1.0, [], {}), {'synthesis_identity': {}}),
            (screening, 'score', audio.score, ('a', 'b', 'ko', 0.9), {'scoring': 'x'}),
            (screening, 'current_scoring_identity_problems', audio.current_scoring_identity_problems, ({},), {}),
            (screening, 'korean_number_spans', audio.korean_number_spans, ('일',), {}),
            (renderer, 'registered_normalization_policy', audio.registered_normalization_policy, ({'j': 1},), {})))
        for value, expected in ((audio.predicted_schema(), predicted.SCHEMA),
                                (audio.synthesis_identity_fields(), predicted.SYNTHESIS_IDENTITY_FIELDS),
                                (audio.scoring(), screening.SCORING), (audio.scoring_v3(), screening.SCORING_V3),
                                (audio.known_scorings(), screening.KNOWN_SCORINGS),
                                (audio.negations(), screening.NEGATIONS), (audio.zh_numerals(), screening.ZH_NUMERALS),
                                (audio.es_numbers(), screening.ES_NUMBERS)):
            self.assertIs(value, expected)
        with patch.object(screening, 'SCORING', 'patched'):
            self.assertEqual(audio.scoring(), 'patched')

    def test_text_rules_reach_layer_2(self):
        rules = review.current().text
        assert_reaches(self, (
            (policy, 'canonical_sha256', rules.canonical_sha256, ({'a': 1},), {}),
            (policy, 'validate_policy', rules.validate_policy, ({'p': 1},), {'series_table': None}),
            (policy, 'validate_source_scope', rules.validate_source_scope, ({'p': 1}, {'s': 1}, {'a': 1}), {}),
            (candidate, 'validate_source_for_translation', rules.validate_source_for_translation,
             ({'s': 1}, {'a': 1}), {}),
            (human_ruling, 'load', rules.load_human_ruling, ('/r.json',), {'source': {}, 'anchor': {}})))
        self.assertEqual(rules.human_ruling_schema(), human_ruling.SCHEMA)
        self.assertEqual(rules.canonical_sha256({'b': [1, 'é']}), policy.canonical_sha256({'b': [1, 'é']}))

    def test_source_evidence_reaches_layer_1(self):
        source = review.current().source
        assert_reaches(self, (
            (text_review, 'text_sha256', source.text_sha256, ('a',), {}),
            (judge_cache, 'cached_call', source.judge_cached_call, (), {'out': '/o', 'stage': 's', 'payload': {},
                                                                       'api_key': 'k', 'requested_model': 'm',
                                                                       'caller': None}),
            (judge_cache, 'reconcile_returned_response', source.reconcile_returned_response, (),
             {'marker_path': '/m', 'response': {}, 'expected_request_sha256': 'a' * 64, 'requested_model': 'm'}),
            (judge_cache, '_atomic', source.atomic_json, ('/p', {'a': 1}), {}),
            (interpretation_models, '_model_result', source.model_result, ({'r': 1}, 'm'), {}),
            (interpretation, 'sha256', source.sha256, ('/p',), {}),
            (interpretation, 'json_sha256', source.json_sha256, ({'a': 1},), {})))
        self.assertIs(source.text_review(), text_review)
        self.assertEqual(source.text_review().MACHINE_RECEIPT_SCHEMA, text_review.MACHINE_RECEIPT_SCHEMA)
        self.assertEqual(source.judge_run_schema(), judge_cache.RUN_SCHEMA)
        self.assertIs(source.source_budget(), source_budget.SourceBudget)
        self.assertEqual(source.budget_metrics(), source_budget.METRICS)

    def test_stage_gates_reach_the_stage_checks(self):
        gates = review.current().gates
        assert_reaches(self, (
            (supervisor, 'validate_window_approval', gates.window_approval, ({'a': 1},),
             {'sunday': '2026-10-18', 'live_url': None}),
            (supervisor, 'parse_timecode', gates.parse_timecode, ('00:01:00',), {}),
            (supervisor, 'stable_hash', gates.stable_hash, ('https://example.test/live',), {}),
            (english_package, '_review_payload', gates.english_review, ('/r.json',),
             {'aligned_sha256': 'a' * 64, 'anchor_json_sha256': 'b' * 64, 'source_unit_ids': ['u1']}),
            (handoff, 'validate_text_release_basis', gates.text_release_basis, ({'s': 1}, {'a': 1}, {'c': 1}, {'r': 1}),
             {}),
            (study_artifacts, 'ingest_review', gates.study_ingest, ({'a': 1}, {'r': 1}), {})))

    def test_scripture_library_is_the_one_the_generator_hashes(self):
        library = review.current().scripture
        for port, module in ((library.cuv, cuv_scripture), (library.editions, scripture_editions),
                             (library.coverage, english_scripture_coverage),
                             (library.candidate_queue, scripture_candidate_queue)):
            self.assertIs(port(), module)
        # (label, path) pairs since R2; the data files are the last two.
        generator_data = [path for _, path in scripture_machine._generator_paths()[-2:]]
        self.assertEqual([library.coverage_data_path(), library.library_path()], generator_data)

    def test_qc_runtime_and_transports_reach_compute_and_observability(self):
        backend = review.current()
        assert_reaches(self, (
            (export_run_digest, 'write_report', backend.qc_runtime.write_report, (['/run'], 'label'), {}),
            (handoff, 'validate_target_candidate', backend.qc_runtime.validate_target_candidate,
             ({'s': 1}, {'a': 1}, {'c': 1}), {'require_human_approval': False})))
        self.assertIs(backend.qc_runtime.codex_text_transport(), sermon_codex_transport)
        self.assertIs(backend.transports.audio_qc(), audio_transports)
        limits = backend.provider.transcription_limits()
        for name in ('MAX_RESPONSE_BYTES', 'WALL_TIME_MS', 'MICROUSD_PER_MINUTE'):
            self.assertEqual(getattr(limits, name), getattr(sermon_transcription_request, name), name)

    def test_compute_session_ports_reach_spark_admission(self):
        compute = review.current().compute
        assert_reaches(self, ((production_spark_admission, 'require_bound_model_session',
                               compute.require_bound_model_session, (), {'verifier': None}),))
        self.assertIs(compute.session_error(), spark_exclusive_session.SessionError)

    def test_building_the_review_records_imports_nothing(self):
        imported = []
        real_import = builtins.__import__

        def recording(name, *args, **kwargs):
            imported.append(name)
            return real_import(name, *args, **kwargs)

        with patch.object(builtins, '__import__', recording):
            for factory in (host.audio_rules, host.text_rules, host.source_evidence, host.stage_gates,
                            host.scripture, host.qc_runtime):
                factory()
        self.assertEqual(imported, [])

    def test_host_load_does_not_import_the_closure_files_review_reaches_lazily(self):
        # The host still loads what the moved producers imported at load time
        # (tongxing_host.EAGER_PRODUCER_IMPORTS), which reaches part of the waiver
        # closure as before; the review binding must not load anything more.
        lazy = ('scripts.sermon_production_supervisor', 'scripts.cuv_scripture', 'scripts.scripture_editions',
                'scripts.english_scripture_coverage', 'scripts.scripture_candidate_queue',
                'tongxing_production.text.human_ruling', 'tongxing_production.source.english_source_judge_cache',
                'tongxing_production.source.sentence_interpretation_models', 'tools.development.export_run_digest',
                'tongxing_production.compute.transports.codex_cli', 'tongxing_production.compute.spark_exclusive_session',
                'tongxing_production.audio.predicted_schedule', 'tongxing_production.audio.renderer',
                'tongxing_production.compute.qc_audio_transports')
        code = ("import sys; from scripts import tongxing_host; "
                f"print([m for m in {lazy!r} if m in sys.modules])")
        result = subprocess.run([sys.executable, '-c', code], cwd=host.ROOT, capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), '[]')

    def test_unbound_layer_fails_clearly(self):
        previous = review._current
        try:
            review._current = None
            with self.assertRaises(ports.Unbound):
                review.current()
            with self.assertRaises(TypeError):
                review.configure(text.current())
        finally:
            review._current = previous


if __name__ == '__main__':
    unittest.main()
