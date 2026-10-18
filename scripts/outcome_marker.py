"""Compatibility alias for the orchestration outcome marker implementation."""
import sys

from tongxing_production.orchestration import outcome_marker as _implementation

sys.modules[__name__] = _implementation
