"""Compatibility import for the API service's Cloud Run job dispatcher.

Keep both import paths on one module object so existing patches reach the
dispatcher used by ``backend.app``.
"""
import sys

from tongxing_api import cloud_run_jobs as _implementation

sys.modules[__name__] = _implementation
