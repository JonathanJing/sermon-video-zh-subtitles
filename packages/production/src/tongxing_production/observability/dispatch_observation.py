"""Observed synchronous dispatch, never an inferred resource queue or admission.

Only this process's durably logged terminal spans establish local readiness.
Unknown external dependencies stay unknown; the caller's explicit [] is a root.
The ready timestamp is when dispatch observes readiness, not earliest readiness.
"""
import os
import threading

MAX_TERMINALS = 32768
_lock = threading.Lock()
_terminals = set()


def _reset():
    global _lock, _terminals
    _lock, _terminals = threading.Lock(), set()


if hasattr(os, 'register_at_fork'):
    os.register_at_fork(after_in_child=_reset)


def _scope(identity):
    return (os.getpid(), *map(str, identity)) if identity and all(identity) else None


def observe(identity, dependencies, now):
    scope = _scope(identity)
    with _lock:
        ready = bool(scope is not None and dependencies is not None and
                     all((scope, dep) in _terminals for dep in dependencies))
    # Actual control entry observations: no max(dependency.finishedAt) inference.
    ready_at = now() if ready else None
    return ready_at, now()


def finished(identity, span):
    scope = _scope(identity)
    if scope is not None:
        with _lock:
            if len(_terminals) >= MAX_TERMINALS:
                _terminals.clear()  # Losing a witness degrades to unknown.
            _terminals.add((scope, span))
