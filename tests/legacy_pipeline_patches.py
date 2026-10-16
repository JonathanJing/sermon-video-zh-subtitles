"""Patch a dual_pdf pipeline name in both modules that call it since W3b.

The Layer 1 English group moved to ``tongxing_production.source.post_live_english``
and the dual_pdf pipeline imports those names back, so a call can resolve the name in
either module. ``patch_both`` installs one mock in both, so ``as fake`` assertions
see every call and a "must not be called" guard still intercepts.
"""
from contextlib import contextmanager
from unittest.mock import patch

from scripts import sermon_pipeline as pipeline
from tongxing_production.source import post_live_english


@contextmanager
def patch_both(name, *arguments, **options):
    with patch.object(post_live_english, name, *arguments, **options) as fake, \
            patch.object(pipeline, name, fake):
        yield fake
