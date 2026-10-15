"""Transition facade: the implementation lives in tongxing_production.compute.provider_limits.

Existing callers keep importing ``scripts.sermon_provider_limits``. This module
replaces itself in ``sys.modules`` with the package module, so both names are
one object: monkeypatching or reading an attribute through either path sees
the same state. Remove this file once no caller imports the old path.
"""
import sys

from tongxing_production.compute import provider_limits as _implementation

sys.modules[__name__] = _implementation
