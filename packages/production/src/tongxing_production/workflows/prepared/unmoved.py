"""Host modules the prepared workflow still reaches until their batches move them.

The prepared workflow builds no backend of its own (workflows design section 3,
item 5): it imports orchestration and the layers directly and reaches what is
still in the host checkout through ports those already have. Each proxy looks
its module up at every use, so these modules import without a host, and an
attribute patch on a proxy lands on the host module, as it did when the stages
imported that module by name. Drop a proxy when its module moves into the package.
"""
from __future__ import annotations

from tongxing_production.orchestration.unified import backend as _orchestration
from tongxing_production.text import backend as _text


class _HostModule:
    def __init__(self, get):
        object.__setattr__(self, '_get', get)

    def __getattr__(self, name):
        return getattr(self._get(), name)

    def __setattr__(self, name, value):
        setattr(self._get(), name, value)

    def __delattr__(self, name):
        delattr(self._get(), name)


# Stage implementations still under scripts/, through the engine's stage lookup.
reviews = _HostModule(lambda: _orchestration.stage('reviews'))  # sermon_unified_reviews, review/ batch
audio = _HostModule(lambda: _orchestration.stage('audio'))      # sermon_unified_audio, Layer 3
# Layer 2's host module for canonical package inspection.
packages = _HostModule(lambda: _text.current().unmoved.package_inspection())  # inspect_canonical_packages


def atomic_json(path, value):
    return _orchestration.current().atomic_json(path, value)


def repo_root():
    """The checkout the run binds to; ``schemas/`` is read relative to it."""
    return _orchestration.current().repo_root


def admit(payload, request_limits, *, surface):
    """Strict budget admission of one bounded API payload (``Compute.admit``)."""
    return _text.current().compute.admit(payload, request_limits, surface=surface)
