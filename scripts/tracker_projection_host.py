"""Bind Tracker read-only projections to the remaining legacy report modules."""
from importlib import import_module

from tongxing_production.observability.projections import backend


backend.configure(backend.TrackerProjectionBackend(
    timeline=lambda: import_module("scripts.build_four_layer_timeline"),
    run_progress=lambda: import_module("tongxing_production.observability.run_progress"),
    weekly_report=lambda: import_module("tongxing_production.observability.weekly_projection"),
))
