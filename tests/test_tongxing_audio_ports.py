"""A0 of the L3 move: the audio layer's ports are bound late to the scripts implementations.

No Layer 3 module calls these ports yet; each batch (A1-A4) switches its files over
when it moves them. These tests pin that every port reaches the implementation the
callers use today, with the paths and values those callers compute today.
"""
import ast
import hashlib
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

from scripts import tongxing_host as host
from scripts import bounded_audio_cpu, four_layer_measure, ko_spoken_numerals, production_spark_admission
from scripts import dev_audio_test_profile, machine_quality_release_basis as machine_basis
from scripts import machine_quality_waiver as waiver
from scripts import render_formal_target_language_speech as renderer
from scripts import render_multilingual_voice_demos as demos
from scripts import review_target_language_audio as audio_review
from scripts import screen_target_language_audio_units as screening
from scripts import sermon_accounting, sermon_local_model_observation, sermon_workflow_jobs
from scripts import spark_tts_replica_pool, spark_tts_window_scheduler
from scripts import target_audio_auto_qc
from scripts import target_audio_predicted_schedule as predicted
from scripts.language_review_plugins import auto_qc_text_common as plugin_rules
from tongxing_production import path_aliases, ports
from tongxing_production.audio import backend as audio
from tongxing_production.delivery import backend as delivery
from tongxing_production.source import backend as source
from tongxing_production.source import producer_compatibility
from tongxing_production.text import backend as text

# SpokenRules field -> the module object and name it stands in for.
PLUGIN_RULES = {'fold': '_fold', 'ko_pattern': '_ko_pattern', 'book_citations': 'book_citations',
                'english_numbers': 'english_numbers', 'korean_sino': 'korean_sino',
                'korean_native': 'korean_native', 'en_book_codes': '_EN_BOOK_CODES',
                'es_book_codes': '_ES_BOOK_CODES', 'ko_book_codes': '_KO_BOOK_CODES',
                'zh_book_codes': '_ZH_BOOK_CODES', 'ko_citation': '_KO_CITATION',
                'ko_counters': '_KO_COUNTERS', 'zh_measure_words': '_ZH_MEASURE_WORDS'}
KO_NUMERALS = {'ko_rule': 'RULE', 'ko_rule_v2': 'RULE_V2', 'ko_rule_v3': 'RULE_V3',
               'spoken_form': 'spoken_form', 'spoken_form_v2': 'spoken_form_v2',
               'spoken_form_v3': 'spoken_form_v3', 'equivalent': 'equivalent',
               'bare_context_allowed': 'bare_context_allowed', 'bare_citation_matches': 'bare_citation_matches',
               'ko_particles': '_PARTICLES', 'ko_connector': '_CONNECTOR', 'ko_range_particle': '_RANGE_PARTICLE',
               'ko_delimiters': '_DELIMITERS', 'ko_numeric_token': '_NUMERIC_TOKEN', 'ko_citations': '_CITATIONS'}

# Modules the host must not import at load. The other Layer 3 modules and the
# text-waiver rules are excluded: the L2 producers already import them at their
# own load (prepare_target_language_speech_job, the package builder and the
# screening it loads), and the host imports what moved producers loaded eagerly
# so loaded-code identity does not change mid-run.
LAZY_AT_HOST_LOAD = ('render_formal_target_language_speech', 'compact_formal_target_audio',
                     'target_audio_anomaly', 'target_audio_recovery', 'target_audio_predicted_schedule',
                     'target_audio_timing_plan', 'review_target_language_audio',
                     'render_speculative_target_language_speech', 'sermon_unified_audio',
                     'machine_qc_audio_transports', 'target_audio_auto_qc', 'ko_spoken_numerals',
                     'language_review_plugins.auto_qc_text_common', 'spark_tts_replica_pool',
                     'spark_tts_window_scheduler', 'bounded_audio_cpu', 'render_multilingual_voice_demos',
                     'sermon_local_model_observation')


def _sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _attributes(path, alias):
    """Names one file reads off ``alias``."""
    return {node.attr for node in ast.walk(ast.parse(Path(path).read_text(encoding='utf-8')))
            if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == alias}


def _imported_from(path, module):
    return {alias.name for node in ast.walk(ast.parse(Path(path).read_text(encoding='utf-8')))
            if isinstance(node, ast.ImportFrom) and node.module == module for alias in node.names}


class AudioPortsTests(unittest.TestCase):
    def test_host_binds_a_complete_backend_sharing_records_with_the_other_layers(self):
        backend = audio.current()
        self.assertIsInstance(backend, audio.AudioBackend)
        for name in ('core', 'code', 'compute', 'measure', 'accounting', 'review'):
            self.assertIs(getattr(backend, name), getattr(source.current(), name), name)
        for name in ('schemas', 'diagnostic'):
            self.assertIs(getattr(backend, name), getattr(text.current(), name), name)
        self.assertIs(backend.waivers, delivery.current().waivers)
        for record, kind in ((backend.machine_qc, ports.MachineQc), (backend.spoken_rules, ports.SpokenRules),
                             (backend.tts_runtime, ports.TtsRuntime), (backend.dev_profile, ports.DevProfile),
                             (backend.unmoved, audio.Unmoved)):
            self.assertIsInstance(record, kind)

    def test_implementation_path_reads_closure_keys_where_layer_3_reads_them_today(self):
        code = audio.current().code
        for name in waiver.IMPLEMENTATION_FILES:
            with self.subTest(closure='waiver', name=name):
                self.assertEqual(code.implementation_path(name), waiver.implementation_path(name))
        for name in predicted.RATE_IMPLEMENTATION_FILES:
            with self.subTest(closure='rate', name=name):
                key = name if name.startswith(('packages/', 'scripts/')) else 'scripts/' + name
                self.assertEqual(code.implementation_path(key),
                                 host.ROOT / producer_compatibility.resolve(key))
        for name in screening.SCORING_IMPLEMENTATION_FILES:  # legacy keys, read where each file lives now
            with self.subTest(closure='scoring', name=name):
                self.assertEqual(code.implementation_path(name), host.ROOT / path_aliases.resolve(name))
        self.assertEqual(code.implementation_path('scripts/sermon_sentence_interpretation.py'),
                         host.ROOT / 'packages/production/src/tongxing_production/source/sentence_interpretation.py')

    def test_host_rule_binding_bytes_invalidate_every_affected_identity(self):
        keys = ('packages/production/src/tongxing_production/audio/hosted.py',
                'packages/production/src/tongxing_production/audio/backend.py',
                'scripts/tongxing_host.py')
        baseline = (waiver.implementation_sha256(), screening.implementation_sha256(),
                    predicted.rate_implementation_sha256())
        original = Path.read_bytes
        for key in keys:
            with self.subTest(key=key):
                target = host.ROOT / key
                with patch.object(Path, 'read_bytes',
                                  lambda path: original(path) + b'\n# changed binding\n'
                                  if path == target else original(path)):
                    changed = (waiver.implementation_sha256(), screening.implementation_sha256(),
                               predicted.rate_implementation_sha256())
                self.assertTrue(all(new != old for new, old in zip(changed, baseline)))

    def test_self_hashes_match_the_values_layer_3_records_today(self):
        code, runtime = audio.current().code, audio.current().tts_runtime
        self.assertEqual(code.module_sha256(renderer), _sha256(renderer.__file__))
        self.assertIs(runtime.replica_pool(), spark_tts_replica_pool)
        self.assertIs(runtime.window_scheduler(), spark_tts_window_scheduler)
        self.assertIs(runtime.bounded_cpu(), bounded_audio_cpu)
        # replicaImplementationSha256 inputs (design §4.5): the pool and scheduler files, now in compute/.
        self.assertEqual(code.module_sha256(runtime.replica_pool()), _sha256(spark_tts_replica_pool.__file__))
        self.assertEqual(code.module_sha256(runtime.window_scheduler()),
                         _sha256(host.ROOT / path_aliases.resolve('scripts/spark_tts_window_scheduler.py')))

    def test_paths_are_the_ones_layer_3_resolves_today(self):
        backend = audio.current()
        schemas = Path(host.ROOT) / 'schemas'  # what the scripts/ modules derived from their own file
        for name in ('sermon-clip-timeline-map-v3.schema.json', 'sermon-target-language-audio-package-v1.schema.json'):
            with self.subTest(name=name):
                self.assertEqual(backend.schemas.path(name).resolve(), (schemas / name).resolve())
        self.assertEqual(backend.schemas.path('x.json').parent.resolve(), (audio_review.ROOT / 'schemas').resolve())
        self.assertEqual(backend.dev_profile.default_profile_path().resolve(),
                         dev_audio_test_profile.DEFAULT_PROFILE.resolve())

    def test_spoken_rules_cover_every_name_layer_3_uses(self):
        used = {('plugin', name) for name in _attributes(screening.__file__, 'rules')}
        used |= {('ko', name) for name in _attributes(screening.__file__, '_ko')}
        used |= {('ko', name) for name in _attributes(renderer.__file__, 'ko_spoken_numerals')}
        bound = {('plugin', name) for name in PLUGIN_RULES.values()} | {('ko', name) for name in KO_NUMERALS.values()}
        self.assertEqual(used, bound)
        self.assertEqual(set(PLUGIN_RULES) | set(KO_NUMERALS),
                         set(ports.SpokenRules.__dataclass_fields__))

    def test_spoken_rules_return_the_rule_modules_own_objects_late(self):
        rules = audio.current().spoken_rules
        for module, table in ((plugin_rules, PLUGIN_RULES), (ko_spoken_numerals, KO_NUMERALS)):
            for field, name in table.items():
                port, target = getattr(rules, field), getattr(module, name)
                with self.subTest(field=field):
                    if callable(target):
                        with patch.object(module, name, return_value=field) as patched:
                            self.assertEqual(port('a', rule='r'), field)
                            patched.assert_called_once_with('a', rule='r')
                    else:
                        self.assertIs(port(), target)
                        with patch.object(module, name, 'patched'):
                            self.assertEqual(port(), 'patched')
        self.assertEqual(rules.korean_sino(21), plugin_rules.korean_sino(21))
        self.assertEqual(rules.ko_pattern('일', sino=True), plugin_rules._ko_pattern('일', sino=True))
        self.assertEqual(rules.spoken_form('요한복음 3장 16절'), ko_spoken_numerals.spoken_form('요한복음 3장 16절'))

    def test_wrappers_reach_the_implementation(self):
        backend = audio.current()
        for module, name, port, args, kwargs in (
                (production_spark_admission, 'require_bound_model_session',
                 backend.compute.require_bound_model_session, (), {'verifier': 'v'}),
                (four_layer_measure, 'record_substage_metrics', backend.measure.record_substage_metrics,
                 ({'m': 1},), {}),
                (sermon_accounting, 'orchestration', backend.accounting.orchestration,
                 ('w.dispatch',), {'depends_on': None, 'work_unit_id': 'w.dispatch'}),
                (target_audio_auto_qc, 'screening_asr_settings', backend.machine_qc.screening_asr_settings,
                 ({'s': 1},), {}),
                (demos, 'read_object', backend.tts_runtime.read_checkpoint_map, (Path('/m.json'), 'checkpoint map'), {}),
                (demos, 'validate_checkpoint', backend.tts_runtime.validate_checkpoint, ({'t': 1},), {}),
                (sermon_workflow_jobs, '_sync_directory_ancestry', backend.core.sync_directory_ancestry,
                 (Path('/x'),), {}),
                (sermon_workflow_jobs, '_read', backend.core.read_json, (Path('/x.json'),), {})):
            with self.subTest(name=name), patch.object(module, name, return_value=name) as target:
                self.assertEqual(port(*args, **kwargs), name)
                target.assert_called_once_with(*args, **kwargs)
        self.assertIs(backend.unmoved.local_model_observation(), sermon_local_model_observation)

    def test_waiver_review_kind_matches_the_waiver_rules(self):
        self.assertEqual(audio.current().waivers.review_kind, machine_basis.REVIEW_KIND)

    def test_host_load_does_not_import_the_renderer_audio_qc_or_spoken_rule_modules(self):
        # A moved module is checked under its package name too (path_aliases maps the legacy file).
        names = [f'scripts.{name}' for name in LAZY_AT_HOST_LOAD]
        names += [path_aliases.resolve(f'scripts/{name}.py').removeprefix('packages/production/src/')
                  .removesuffix('.py').replace('/', '.') for name in LAZY_AT_HOST_LOAD
                  if path_aliases.resolve(f'scripts/{name}.py').startswith('packages/')]
        code = ("import sys; from scripts import tongxing_host; "
                f"print([m for m in {names!r} if m in sys.modules])")
        result = subprocess.run([sys.executable, '-c', code], cwd=host.ROOT, capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), '[]')

    def test_unbound_layer_fails_clearly(self):
        previous = audio._current
        try:
            audio._current = None
            with self.assertRaises(ports.Unbound):
                audio.current()
        finally:
            audio._current = previous
        with self.assertRaises(TypeError):
            audio.configure(text.current())


if __name__ == '__main__':
    unittest.main()
