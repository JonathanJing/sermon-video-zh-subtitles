"""Checked-in JSON schemas, read from the root the host configures.

The repository's ``schemas/`` directory stays the only editable schema source.
The package never locates it from its own file: the host passes the absolute
directory once, so loading does not depend on the working directory.
"""
from __future__ import annotations

from datetime import datetime
from functools import lru_cache
import json
from pathlib import Path
import re

from jsonschema import Draft202012Validator, FormatChecker, validators

from .canonical import require

_root: Path | None = None


def configure(root) -> None:
    """Bind the absolute schema directory; later lookups read from it."""
    global _root
    root = Path(root)
    if not root.is_absolute():
        raise ValueError('schema root must be absolute')
    if root == _root:
        return
    _root = root
    validator.cache_clear()


def root() -> Path:
    if _root is None:
        from ..ports import Unbound  # contracts imports nothing else at load
        raise Unbound('tongxing_production.contracts.schemas needs a configured schema root')
    return _root


def path(name) -> Path:
    return root() / name


@lru_cache(maxsize=8)
def validator(version):
    """Draft 2020-12 validator for ``<version>.schema.json``: UTC date-times, strict integers."""
    require(isinstance(version, str) and re.fullmatch(r'[a-z0-9][a-z0-9.-]*', version) is not None, 'unsupported_schema_version')
    schema = json.loads(path(version + '.schema.json').read_text())
    Draft202012Validator.check_schema(schema)
    checker = FormatChecker()
    @checker.checks('date-time', raises=(ValueError, TypeError))
    def utc(value):
        return isinstance(value,str) and value.endswith('Z') and datetime.fromisoformat(value).tzinfo is not None
    cls = validators.extend(Draft202012Validator, type_checker=Draft202012Validator.TYPE_CHECKER.redefine('integer', lambda _,v:type(v) is int))
    return cls(schema, format_checker=checker)
