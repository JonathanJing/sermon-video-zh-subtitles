"""Transition facade: the implementation lives in tongxing_production.review.contracts.

The generic half (ContractError, canonical JSON and byte hashes, strict JSON,
stable snapshot reads, schema validators) lives in tongxing_production.contracts;
the review module re-exports it, so every old name stays importable here and
both import paths name one module object. Remove once no caller imports this path.
"""
from pathlib import Path
import sys

from tongxing_production.contracts import schemas as _schemas
from tongxing_production.review import contracts as _implementation

# The checkout's schemas/ directory, the same root tongxing_host binds, so a
# caller that imports only this module still validates against it.
_schemas.configure(Path(__file__).resolve().parents[1] / 'schemas')

sys.modules[__name__] = _implementation
