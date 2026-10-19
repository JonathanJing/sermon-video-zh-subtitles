"""Patch a durable job store file primitive in both modules that call it.

The primitives (``_persist``, ``_sync_directory``, ...) live in
``tongxing_production.storage.files`` since the closure window G1; the job store
(``scripts/sermon_workflow_jobs.py`` -> ``orchestration.jobs``) imports them back, and
the primitives also call each other inside ``storage.files``. ``patch_job_store``
installs one mock in both modules, so ``as fake`` sees every call and a fault
injection reaches every caller.
"""
from contextlib import contextmanager
from unittest.mock import patch

from scripts import tongxing_host  # noqa: F401  binds the production package ports
from tongxing_production.orchestration import jobs
from tongxing_production.storage import files


@contextmanager
def patch_job_store(name, *arguments, **options):
    with patch.object(files, name, *arguments, **options) as fake, patch.object(jobs, name, fake):
        yield fake
