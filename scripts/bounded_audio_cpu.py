"""Transition facade: the implementation lives in tongxing_production.compute.bounded_audio_cpu.

Existing callers keep importing ``scripts.bounded_audio_cpu`` (or ``bounded_audio_cpu``
from scripts/ on Spark). This module replaces itself in ``sys.modules`` with the
package module, so both names are one object. Remove this file once no caller
imports the old path.
"""
import sys

from tongxing_production.compute import bounded_audio_cpu as _implementation

sys.modules[__name__] = _implementation
