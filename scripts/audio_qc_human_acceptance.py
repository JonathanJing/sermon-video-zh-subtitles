"""Transition facade: the implementation lives in tongxing_production.review.audio_qc_acceptance.

Existing callers keep importing ``scripts.audio_qc_human_acceptance``. This module
replaces itself in ``sys.modules`` with the package module, so both names are
one object: monkeypatching or reading an attribute through either path sees
the same state. Remove this file once no caller imports the old path.
"""
import sys

from tongxing_production.review import audio_qc_acceptance as _implementation

sys.modules[__name__] = _implementation
