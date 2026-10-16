"""D0 of the L4 move: the delivery layer's ports are bound late to the scripts implementations.

No Layer 4 module calls these ports yet; each batch (D1-D9) switches its files over
when it moves them. These tests pin that every port reaches the implementation the
callers use today, with the paths and values those callers compute today.
"""
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

from scripts import tongxing_host as host
from scripts import build_full_video_app_release as builder
from scripts import guarded_hosting_publish as publisher
from scripts import machine_audio_waiver_acceptance as audio_waivers
from scripts import machine_quality_release_basis as machine_basis
from scripts import sermon_app_delivery_workflow as app_workflow
from scripts import sermon_unified_delivery as unified_delivery
from scripts import sermon_unified_reviews as reviews
from scripts import stage_formal_multilingual_dev as formal_stage
from tongxing_production import ports
from tongxing_production.delivery import backend as delivery
from tongxing_production.source import backend as source
from tongxing_production.text import backend as text


class DeliveryPortsTests(unittest.TestCase):
    def test_host_binds_a_complete_backend_sharing_records_with_the_other_layers(self):
        backend = delivery.current()
        self.assertIsInstance(backend, delivery.DeliveryBackend)
        for name in ('core', 'contracts', 'code', 'workspace', 'review'):
            self.assertIs(getattr(backend, name), getattr(source.current(), name), name)
        self.assertIs(backend.schemas, text.current().schemas)
        for record, kind in ((backend.runtime_web, ports.RuntimeWeb), (backend.hosting, ports.Hosting),
                             (backend.waivers, ports.Waivers)):
            self.assertIsInstance(record, kind)

    def test_runtime_web_is_the_shell_releases_freeze_today(self):
        root = delivery.current().runtime_web.root()
        self.assertEqual(root.resolve(), builder.runtime_web_root().resolve())
        self.assertEqual(builder.runtime_web_files(root), builder.runtime_web_files())
        self.assertIn('catalog.mjs', builder.runtime_web_files(root))

    def test_worker_command_keeps_the_recorded_app_workflow_argv(self):
        config = type('Config', (), {'path': Path('/run/app.json'), 'sha256': 'a' * 64})()
        import inspect
        parameters = list(inspect.signature(app_workflow._worker_command).parameters)
        recorded = app_workflow._worker_command(*[config if name == 'config' else 'b' * 64 for name in parameters])
        self.assertEqual(delivery.current().worker_command(*recorded[2:]), recorded)
        self.assertEqual(recorded[0], sys.executable)

    def test_hosting_wrappers_reach_the_implementation(self):
        hosting = delivery.current().hosting
        with patch.object(publisher, 'authenticated_transport', return_value='request') as transport:
            self.assertEqual(hosting.authorized_request(), 'request')
            transport.assert_called_once_with()
        with patch.object(unified_delivery, '_reader', return_value=(200, b'ok')) as reader:
            self.assertEqual(hosting.public_reader('https://example.test/x', timeout=5), (200, b'ok'))
            reader.assert_called_once_with('https://example.test/x', timeout=5)
        with patch.object(publisher, 'RemoteLease', return_value='lease') as lease:
            self.assertEqual(hosting.lease('request', 'bucket', 'site'), 'lease')
            lease.assert_called_once_with('request', 'bucket', 'site')
        with patch.object(subprocess, 'run', return_value='done') as run:
            self.assertEqual(hosting.run(['firebase', 'deploy'], check=True), 'done')
            run.assert_called_once_with(['firebase', 'deploy'], check=True)

    def test_review_and_waiver_wrappers_reach_the_implementation(self):
        backend = delivery.current()
        with patch.object(reviews, 'validate_review', return_value='ok') as validate:
            self.assertEqual(backend.review.validate_review('release_basis', '/r.json', inputs={'a': 1}), 'ok')
            validate.assert_called_once_with('release_basis', '/r.json', inputs={'a': 1})
        with patch.object(formal_stage, 'validate_audio_screening_review', return_value='screened') as screen:
            self.assertEqual(backend.review.audio_screening({'a': 1}, {'r': 1}, {'s': 1}), 'screened')
            screen.assert_called_once_with({'a': 1}, {'r': 1}, {'s': 1})
        for module, name, port, args, kwargs in (
                (machine_basis, 'is_text_waiver', backend.waivers.is_text_waiver, ({'r': 1},), {}),
                (machine_basis, 'validate_text_waiver', backend.waivers.validate_text_waiver, ({'r': 1},), {'candidate': {}}),
                (machine_basis, 'disclosure', backend.waivers.disclosure, ('ko',), {}),
                (audio_waivers, 'is_audio_waiver', backend.waivers.is_audio_waiver, ({'r': 1},), {}),
                (audio_waivers, 'validate_audio_waiver', backend.waivers.validate_audio_waiver, ({'p': 1}, {'r': 1}, None), {})):
            with self.subTest(name=name), patch.object(module, name, return_value=name) as target:
                self.assertEqual(port(*args, **kwargs), name)
                target.assert_called_once_with(*args, **kwargs)

    def test_waiver_schema_names_match_the_waiver_rules(self):
        waivers = delivery.current().waivers
        self.assertEqual(waivers.audio_waiver_schema, machine_basis.AUDIO_WAIVER_SCHEMA)
        self.assertEqual(waivers.condensation_binding_schema, machine_basis.CONDENSATION_BINDING_SCHEMA)

    def test_host_load_does_not_import_layer_4_modules(self):
        # The host does load what the moved producers imported at load time (see
        # tongxing_host.EAGER_PRODUCER_IMPORTS), which reaches the waiver release
        # basis as it did before the move; it must not load Layer 4 itself.
        code = ("import sys; from scripts import tongxing_host; "
                "loaded = [m for m in ('scripts.build_full_video_app_release', 'scripts.guarded_hosting_publish', "
                "'scripts.machine_audio_waiver_acceptance', 'scripts.sermon_unified_delivery', "
                "'scripts.sermon_app_delivery_workflow') if m in sys.modules]; print(loaded)")
        result = subprocess.run([sys.executable, '-c', code], cwd=host.ROOT, capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), '[]')

    def test_unbound_layer_fails_clearly(self):
        previous = delivery._current
        try:
            delivery._current = None
            with self.assertRaises(ports.Unbound):
                delivery.current()
        finally:
            delivery._current = previous


if __name__ == '__main__':
    unittest.main()
