"""Transition facade: the implementation lives in tongxing_production.review.repair_ledger.

Existing callers keep importing ``scripts.machine_repair_ledger``. This module
replaces itself in ``sys.modules`` with the package module, so both names are
one object: monkeypatching or reading an attribute through either path sees
the same state. Remove this file once no caller imports the old path.
"""
import sys

from tongxing_production.review import repair_ledger as _implementation

sys.modules[__name__] = _implementation
