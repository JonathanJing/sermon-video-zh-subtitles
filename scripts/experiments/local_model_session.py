"""Single-slot, process-local model reuse for explicitly bounded diagnostics.

No daemon, dispatch, model import or production configuration is provided here.
Callers compute/freeze identities before borrowing and must not retain a borrowed
model outside its context. Exact identity reuse is configuration evidence; it does
not prove a measured speed improvement or validate the model's generated content.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import asdict, dataclass
import gc
import re
import sys
import threading
import time
from typing import Callable, Any


@dataclass(frozen=True)
class ModelKey:
    stage: str
    model_tree_sha256: str
    device: str
    dtype: str
    attention: str | None
    runtime_identity_sha256: str
    implementation_sha256: str
    checkpoint_sha256: str | None = None

    def __post_init__(self):
        if self.stage not in {'tts', 'asr'}:
            raise ValueError('unsupported_local_model_stage')
        for value in (self.model_tree_sha256, self.runtime_identity_sha256, self.implementation_sha256):
            if not isinstance(value, str) or re.fullmatch(r'[a-f0-9]{64}', value) is None:
                raise ValueError('local_model_identity_requires_sha256')
        if self.checkpoint_sha256 is not None and (
                not isinstance(self.checkpoint_sha256, str) or
                re.fullmatch(r'[a-f0-9]{64}', self.checkpoint_sha256) is None):
            raise ValueError('local_model_checkpoint_requires_sha256')
        if self.stage == 'tts' and self.checkpoint_sha256 is None:
            raise ValueError('tts_checkpoint_identity_required')
        for value in (self.device, self.dtype):
            if not isinstance(value, str) or re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}', value) is None:
                raise ValueError('invalid_local_model_setting')
        if self.attention is not None and (
                not isinstance(self.attention, str) or
                re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}', self.attention) is None):
            raise ValueError('invalid_local_model_attention')


def dispose_model(model):
    """Invoke explicit cleanup if the adapter supplies it; cache drops refs next."""
    closer = getattr(model, 'close', None)
    if callable(closer):
        closer()


def cleanup_loaded_gpu():
    """Clean an already-imported CUDA runtime; never import/load it ourselves."""
    torch = sys.modules.get('torch')
    cuda = getattr(torch, 'cuda', None)
    if cuda is not None and cuda.is_available():
        cuda.synchronize()
        cuda.empty_cache()


class LocalModelSession:
    """At most one cached model and one active lease, with explicit close.

    Usage::
        with LocalModelSession() as session:
            with session.borrow(key, lambda: Adapter(...)) as model:
                run_diagnostic(model)

    Borrow ends before switching keys. A failed release permanently closes this
    session so a second GPU model cannot be admitted after unknown cleanup.
    A failed/interrupted lease body poisons reuse; close still disposes its model.
    """
    def __init__(self, *, disposer: Callable[[Any], None] = dispose_model,
                 cleanup: Callable[[], None] = cleanup_loaded_gpu,
                 clock: Callable[[], float] = time.perf_counter):
        self._model = None
        self._key = None
        self._active = False
        self._closed = False
        self._mutex = threading.RLock()
        self._disposer, self._cleanup, self._clock = disposer, cleanup, clock
        self._stats = {'loadAttempts': 0, 'loadCount': 0, 'loadFailures': 0,
                       'reuseCount': 0, 'releaseCount': 0, 'releaseFailures': 0,
                       'loadSeconds': 0.0, 'maximumCachedModels': 0}

    def _release(self):
        if self._model is None:
            return
        previous = self._model
        self._model, self._key = None, None
        try:
            self._disposer(previous)
            del previous
            gc.collect()
            self._cleanup()
        except BaseException:
            self._closed = True
            self._stats['releaseFailures'] += 1
            raise
        self._stats['releaseCount'] += 1

    @contextmanager
    def borrow(self, key: ModelKey, factory: Callable[[], Any]):
        if not isinstance(key, ModelKey) or not callable(factory):
            raise ValueError('local_model_key_and_factory_required')
        with self._mutex:
            if self._closed:
                raise ValueError('local_model_session_closed')
            if self._active:
                raise ValueError('local_model_lease_active')
            if self._model is not None and key == self._key:
                self._stats['reuseCount'] += 1
            else:
                # This must finish successfully before any new model load.
                self._release()
                self._stats['loadAttempts'] += 1
                began = self._clock()
                try:
                    model = factory()
                    if model is None:
                        raise ValueError('local_model_factory_returned_none')
                except BaseException:
                    self._stats['loadFailures'] += 1
                    # The failed factory may have partially initialized CUDA.
                    # Require a fresh session rather than retrying an unknown load.
                    self._closed = True
                    raise
                finally:
                    self._stats['loadSeconds'] += max(0.0, self._clock() - began)
                self._model, self._key = model, key
                self._stats['loadCount'] += 1
                self._stats['maximumCachedModels'] = 1
            self._active = True
        try:
            yield self._model
        except BaseException:
            # A failed/interrupted inference may leave an unsafe runtime. Keep
            # its object only for close/disposal; never admit another borrow.
            with self._mutex:
                self._closed = True
            raise
        finally:
            with self._mutex:
                self._active = False

    def stats(self):
        with self._mutex:
            return {'schemaVersion': 'diagnostic-local-model-session-v1',
                    'diagnosticOnly': True, 'formalEligible': False,
                    **self._stats, 'cachedModels': int(self._model is not None),
                    'activeLease': self._active, 'closed': self._closed,
                    'currentKey': asdict(self._key) if self._key is not None else None,
                    'timingScope': 'factory_load_wall_including_factory_synchronization_if_supplied',
                    'measuredInferenceSpeedup': None}

    def close(self):
        with self._mutex:
            if self._active:
                raise ValueError('local_model_lease_active')
            self._release()
            self._closed = True

    def __enter__(self):
        with self._mutex:
            if self._closed:
                raise ValueError('local_model_session_closed')
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()
