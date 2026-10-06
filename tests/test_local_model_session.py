"""Fake adapters verify bounded residency without model/GPU execution."""
from dataclasses import replace
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from scripts.experiments.local_model_session import (
    LocalModelSession, ModelKey, cleanup_loaded_gpu,
)


def key(**kwargs):
    fields = dict(stage='tts', model_tree_sha256='a' * 64, checkpoint_sha256='b' * 64,
                  device='cuda:0', dtype='bfloat16', attention='sdpa',
                  runtime_identity_sha256='c' * 64, implementation_sha256='d' * 64)
    fields.update(kwargs)
    return ModelKey(**fields)


class LocalModelSessionTests(unittest.TestCase):
    def test_same_identity_reuses_one_model_and_close_cleans(self):
        model = SimpleNamespace(close=Mock())
        load = Mock(return_value=model); cleanup = Mock()
        session = LocalModelSession(cleanup=cleanup)
        with session:
            for _ in range(3):
                with session.borrow(key(), load) as resident:
                    self.assertIs(resident, model)
            stats = session.stats()
            self.assertEqual(stats['loadCount'], 1)
            self.assertEqual(stats['reuseCount'], 2)
            self.assertEqual(stats['maximumCachedModels'], 1)
            self.assertIsNone(stats['measuredInferenceSpeedup'])
        load.assert_called_once()
        model.close.assert_called_once()
        cleanup.assert_called_once()
        self.assertEqual(session.stats()['cachedModels'], 0)
        self.assertTrue(session.stats()['closed'])

    def test_every_identity_dimension_change_releases_before_loading(self):
        changes = [dict(stage='asr'), dict(model_tree_sha256='e' * 64),
                   dict(checkpoint_sha256='f' * 64), dict(device='cuda:1'),
                   dict(dtype='float32'), dict(attention='flash_attention_2'),
                   dict(runtime_identity_sha256='1' * 64), dict(implementation_sha256='2' * 64)]
        for fields in changes:
            with self.subTest(fields=fields):
                events = []
                old = SimpleNamespace(close=lambda: events.append('old-close'))
                new = SimpleNamespace(close=lambda: events.append('new-close'))
                session = LocalModelSession(cleanup=lambda: events.append('gpu-cleanup'))
                with session.borrow(key(), lambda: old):
                    pass
                def load_new():
                    events.append('new-load')
                    self.assertEqual(session.stats()['cachedModels'], 0)
                    return new
                with session.borrow(replace(key(), **fields), load_new):
                    pass
                self.assertEqual(events, ['old-close', 'gpu-cleanup', 'new-load'])
                self.assertEqual(session.stats()['loadCount'], 2)
                self.assertEqual(session.stats()['releaseCount'], 1)
                session.close()

    def test_active_lease_blocks_another_stage_and_close(self):
        with LocalModelSession(cleanup=Mock()) as session:
            with session.borrow(key(), lambda: object()):
                factory = Mock()
                with self.assertRaisesRegex(ValueError, 'local_model_lease_active'):
                    with session.borrow(key(stage='asr'), factory):
                        pass
                with self.assertRaisesRegex(ValueError, 'local_model_lease_active'):
                    session.close()
                factory.assert_not_called()

    def test_release_failure_closes_session_and_never_loads_second_model(self):
        cleanup = Mock(side_effect=RuntimeError('fake GPU cleanup failure'))
        session = LocalModelSession(cleanup=cleanup)
        with session.borrow(key(), lambda: object()):
            pass
        factory = Mock()
        with self.assertRaisesRegex(RuntimeError, 'fake GPU'):
            with session.borrow(key(stage='asr'), factory):
                pass
        self.assertTrue(session.stats()['closed'])
        self.assertEqual(session.stats()['releaseFailures'], 1)
        with self.assertRaisesRegex(ValueError, 'local_model_session_closed'):
            with session.borrow(key(), factory):
                pass
        factory.assert_not_called()

    def test_failed_load_is_not_automatically_retried(self):
        factory = Mock(side_effect=RuntimeError('fake load failure'))
        session = LocalModelSession(cleanup=Mock())
        with self.assertRaisesRegex(RuntimeError, 'fake load failure'):
            with session.borrow(key(), factory):
                pass
        self.assertEqual(session.stats()['loadFailures'], 1)
        self.assertEqual(session.stats()['cachedModels'], 0)
        with self.assertRaisesRegex(ValueError, 'local_model_session_closed'):
            with session.borrow(key(), factory):
                pass
        factory.assert_called_once()

    def test_body_failure_poisoned_session_rejects_reuse_but_close_cleans(self):
        # Inference attempt/replay admission remains the worker's responsibility.
        cleanup = Mock()
        model = SimpleNamespace(close=Mock())
        session = LocalModelSession(cleanup=cleanup)
        with self.assertRaisesRegex(RuntimeError, 'fake inference failure'):
            with session.borrow(key(), lambda: model):
                raise RuntimeError('fake inference failure')
        self.assertFalse(session.stats()['activeLease'])
        self.assertTrue(session.stats()['closed'])
        next_factory = Mock()
        with self.assertRaisesRegex(ValueError, 'local_model_session_closed'):
            with session.borrow(key(), next_factory):
                pass
        next_factory.assert_not_called()
        session.close()
        model.close.assert_called_once()
        cleanup.assert_called_once()

    def test_sha256_identities_required_and_tts_checkpoint_cannot_be_omitted(self):
        for fields in [dict(model_tree_sha256='unverified'), dict(runtime_identity_sha256=''),
                       dict(implementation_sha256='provider-name'), dict(checkpoint_sha256=None),
                       dict(stage='translation'), dict(device='cuda:0\nother')]:
            with self.subTest(fields=fields), self.assertRaises(ValueError):
                key(**fields)
        self.assertIsNone(key(stage='asr', checkpoint_sha256=None).checkpoint_sha256)

    def test_closed_session_never_reopens_and_double_close_is_safe(self):
        session = LocalModelSession(cleanup=Mock()); session.close(); session.close()
        with self.assertRaisesRegex(ValueError, 'local_model_session_closed'):
            with session:
                pass

    def test_default_gpu_cleanup_only_uses_existing_import(self):
        cuda = SimpleNamespace(is_available=Mock(return_value=True), synchronize=Mock(), empty_cache=Mock())
        with patch.dict('sys.modules', {'torch': SimpleNamespace(cuda=cuda)}):
            cleanup_loaded_gpu()
        cuda.synchronize.assert_called_once(); cuda.empty_cache.assert_called_once()


if __name__ == '__main__':
    unittest.main()
