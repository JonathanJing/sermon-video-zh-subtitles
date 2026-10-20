"""T0 of the L2 move: the text layer's ports are bound late to the scripts implementations.

No Layer 2 module calls these ports yet; each batch (T1-T4) switches its files over
when it moves them. These tests pin that every port reaches the implementation the
callers use today, with the values those callers compute today.
"""
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

from scripts import tongxing_host as host
from tongxing_production.text import controller
from scripts import series_terminology
from tongxing_production.compute import api_concurrency as layer2_api_concurrency
from tongxing_production.observability import accounting as sermon_accounting
from tongxing_production.observability import measure as four_layer_measure
from tongxing_production.text import candidate
from scripts import four_layer_measure, sermon_accounting, series_terminology
from tongxing_production.compute import api_concurrency as layer2_api_concurrency
from scripts import prepare_target_language_speech_job as handoff
from tongxing_production.compute import concurrency_profile as production_concurrency_profile
from tongxing_production.compute import openai_runtime as sermon_openai_runtime
from tongxing_production.compute import budget_capability as strict_budget_capability
from scripts import sermon_diagnostic_context
from tongxing_production.review import source_meaning as meaning
from tongxing_production.text import policy
from tongxing_production import path_aliases, ports
from tongxing_production.source import backend as source
from tongxing_production.source import producer_compatibility
from tongxing_production.text import backend as text


class TextPortsTests(unittest.TestCase):
    def test_host_binds_a_complete_backend_sharing_records_with_layer_1(self):
        backend, layer1 = text.current(), source.current()
        self.assertIsInstance(backend, text.TextBackend)
        for name in ('core', 'provider', 'code', 'snapshot', 'compute', 'resources',
                     'terminology', 'measure', 'accounting', 'workspace'):
            self.assertIs(getattr(backend, name), getattr(layer1, name), name)
        for record, kind in ((backend.plugins, ports.Plugins), (backend.transports, ports.Transports),
                             (backend.schemas, ports.Schemas), (backend.diagnostic, ports.Diagnostic),
                             (backend.unmoved, text.Unmoved)):
            self.assertIsInstance(record, kind)

    def test_paths_are_the_ones_layer_2_resolves_today(self):
        backend = text.current()
        builtins = (Path(host.ROOT) / 'scripts/language_review_plugins').resolve()  # plugins stay in scripts/ (decision 1)
        self.assertEqual(backend.plugins.root().resolve(), builtins)
        self.assertEqual(backend.plugins.implementation_file('cuv_scripture.py').resolve(),
                         builtins.parent / 'cuv_scripture.py')
        self.assertEqual(backend.terminology.table_path().resolve(), policy.SERIES_TABLE.resolve())
        self.assertEqual(backend.schemas.path('sermon-target-language-policy-v1.schema.json').resolve(),
                         policy.SCHEMA_PATH.resolve())
        self.assertEqual(backend.schemas.source_package_schema(), handoff.SOURCE_PACKAGE_SCHEMA)

    def test_worker_command_keeps_the_recorded_argv(self):
        config = type('Config', (), {'path': Path('/run/config.json'), 'sha256': 'a' * 64})()
        recorded = controller._worker_command(config, 'ko', 'b' * 64, 'c' * 64)
        self.assertEqual(text.current().worker_command(*recorded[3:]), recorded)
        self.assertEqual(recorded[0], sys.executable)
        # The D closure window removed the scripts/ facade; requests name the package entry.
        self.assertEqual(Path(recorded[1]), Path(host.ROOT) / 'tools/ops/run.py')
        self.assertEqual(recorded[2], 'text.controller')

    def test_compute_limits_and_wrappers_reach_the_implementation(self):
        compute = text.current().compute
        self.assertEqual(compute.max_in_flight_api_calls, layer2_api_concurrency.MAX_IN_FLIGHT_API_CALLS)
        self.assertEqual(compute.max_group_workers_per_locale, layer2_api_concurrency.MAX_GROUP_WORKERS_PER_LOCALE)
        with patch.object(production_concurrency_profile, 'load_profile', return_value={'p': 1}) as load:
            self.assertEqual(compute.load_profile('profile.json'), {'p': 1})
            load.assert_called_once_with('profile.json')
        with patch.object(strict_budget_capability, 'require_bounded_api_payload', return_value='ok') as admit:
            self.assertEqual(compute.admit({'m': 1}, {'l': 1}, surface='x'), 'ok')
            admit.assert_called_once_with({'m': 1}, {'l': 1}, surface='x')
        with patch.object(strict_budget_capability, 'reject_codex_cli_transport') as reject:
            compute.reject_cli_transport('caller')
            reject.assert_called_once_with('caller')
        with patch.object(layer2_api_concurrency, 'request_slot', return_value='slot') as slot:
            self.assertEqual(compute.request_slot('/jobs'), 'slot')
            slot.assert_called_once_with('/jobs')

    def test_accounting_measure_and_route_wrappers_reach_the_implementation(self):
        backend = text.current()
        with patch.object(sermon_accounting, 'stage', return_value='span') as stage:
            self.assertEqual(backend.accounting.stage('s', cache_hit=True, billing='api'), 'span')
            stage.assert_called_once_with('s', cache_hit=True, billing='api')
        for name, port, args, kwargs in (
                ('record_workload', backend.accounting.record_workload, ('w', {'n': 1}), {}),
                ('record_log', backend.accounting.record_log, ('code',), {'level': 'WARN'}),
                ('bounded_dependencies', backend.accounting.bounded_dependencies, ('d', ['a']), {'work_unit_id': 'u'}),
                ('_finalize', backend.accounting.finalize, ('a', None), {}),
                ('request_metadata', backend.provider.request_metadata, ({'temperature': 0},), {})):
            with self.subTest(name=name), patch.object(sermon_accounting, name, return_value=name) as target:
                self.assertEqual(port(*args, **kwargs), name)
                target.assert_called_once_with(*args, **kwargs)
        with patch.object(four_layer_measure, 'producer_substage', return_value='sub') as substage:
            self.assertEqual(backend.measure.producer_substage('n', billing='local'), 'sub')
            substage.assert_called_once_with('n', billing='local')
        with patch.object(sermon_openai_runtime, 'project_headers', return_value={'h': 1}) as headers:
            self.assertEqual(backend.provider.route.project_headers('key'), {'h': 1})
            headers.assert_called_once_with('key')
        with patch.object(series_terminology, 'parse_table', return_value=['row']) as parse:
            self.assertEqual(backend.terminology.parse_table('text'), ['row'])
            parse.assert_called_once_with('text')

    def test_diagnostic_schema_and_review_wrappers_reach_the_implementation(self):
        backend = text.current()
        with patch.object(sermon_diagnostic_context, 'validate_source', return_value='v') as validate:
            self.assertEqual(backend.diagnostic.validate_source('s', 'a', 'c'), 'v')
            validate.assert_called_once_with('s', 'a', 'c')
        with patch.object(handoff, '_validate_schema') as schema:
            backend.schemas.validate({'v': 1}, 'f.schema.json', 'label')
            schema.assert_called_once_with({'v': 1}, 'f.schema.json', 'label')
        with patch.object(meaning, 'repair_instruction', return_value='fix') as repair:
            self.assertEqual(backend.unmoved.repair_instruction({'n': {}}, ['u1']), 'fix')
            repair.assert_called_once_with({'n': {}}, ['u1'])
        self.assertIs(backend.unmoved.speech_handoff(), handoff)

    def test_unknown_transport_backend_is_refused_without_constructing_one(self):
        with self.assertRaisesRegex(ValueError, 'unknown Layer 2 transport backend'):
            text.current().transports.caller('other')

    def test_shared_alias_table_is_the_one_layer_1_resolves_through(self):
        self.assertIs(producer_compatibility.resolve, path_aliases.resolve)
        self.assertIs(producer_compatibility.recorded, path_aliases.recorded)
        self.assertIs(producer_compatibility.PATH_ALIASES, path_aliases.PATH_ALIASES)
        self.assertEqual(path_aliases.resolve('scripts/mfa_spark.py'),
                         'packages/production/src/tongxing_production/source/mfa_spark.py')
        self.assertEqual(path_aliases.resolve('scripts/sermon_unified_audio.py'),
                         'packages/production/src/tongxing_production/audio/unified_stage.py')
        root = Path(host.ROOT)
        # Keys outlive their import facades: frozen records still name the legacy path.
        for legacy, current in path_aliases.PATH_ALIASES.items():
            with self.subTest(legacy=legacy):
                self.assertTrue((root / current).is_file())

    def test_unbound_layer_fails_clearly(self):
        previous = text._current
        try:
            text._current = None
            with self.assertRaises(ports.Unbound):
                text.current()
        finally:
            text._current = previous


if __name__ == '__main__':
    unittest.main()
