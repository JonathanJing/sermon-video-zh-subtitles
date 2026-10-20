"""The checkout a diagnostic run is bound to, and where its legacy identity keys live.

Diagnostic identities hash their own and their siblings' files under the legacy
``scripts/<name>`` keys they were recorded with. The host supplies the checkout
root (never derived from a module file) and ``path_aliases`` the current file.
"""
from __future__ import annotations

from pathlib import Path

from ... import path_aliases
from ...source import backend as _source


def root() -> Path:
    return _source.current().core.repo_root


def legacy(name: str) -> Path:
    """The file the legacy key ``scripts/<name>`` names today."""
    return root() / path_aliases.resolve('scripts/' + name)


def entry() -> Path:
    """The package command entry: ``python tools/ops/run.py <module>`` binds the host first."""
    return root() / 'tools/ops/run.py'
