"""Read explicit Dev audio settings without changing production defaults."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


DEFAULT_PROFILE = (Path(__file__).resolve().parents[1] / "data/benchmarks/"
                   "local-layer-latency/2026-10-01/next-dev-test-profile.json")
SCHEMA = "local-production-next-dev-test-profile-v2"
_STAGES = {"tts": ("formalTts", 2, {1, 2}),
           "back-asr": ("formalBackAsr", 4, {1, 4, 8})}
_BATCHES = {1, 2, 4, 8}


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--dev-test", action="store_true",
                        help="Use the explicit Dev audio test profile")
    parser.add_argument("--dev-test-profile", type=Path, default=None,
                        help="Dev test profile; requires --dev-test")


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        _require(key not in result, "Duplicate key in Dev audio profile")
        result[key] = value
    return result


def _invalid_constant(_value):
    raise ValueError("Invalid JSON constant in Dev audio profile")


def resolve(stage: str, *, enabled: bool = False, profile_path: Path | None = None,
            batch_size: int | None = None) -> dict:
    """Return batch size and raw-byte profile identity; never dispatch or write.

    Production keeps batch1 and its existing explicit batch choices. Dev mode
    validates both audio sections and their conservative baseline before using
    a default or an explicit candidate, so an override cannot bypass admission.
    """
    _require(stage in _STAGES, "Unknown Dev audio stage")
    _require(type(enabled) is bool, "Dev test flag must be boolean")
    _require(batch_size is None or type(batch_size) is int and batch_size in _BATCHES,
             "Batch size must be one of 1, 2, 4, 8")
    if not enabled:
        _require(profile_path is None, "--dev-test-profile requires --dev-test")
        return {"batchSize": 1 if batch_size is None else batch_size, "profile": None}

    path = (DEFAULT_PROFILE if profile_path is None else Path(profile_path)).resolve()
    try:
        raw = path.read_bytes()
        profile = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_pairs,
                             parse_constant=_invalid_constant)
    except (OSError, UnicodeError, ValueError) as exc:
        raise ValueError("Cannot read a valid Dev audio test profile") from exc
    _require(type(profile) is dict and profile.get("schemaVersion") == SCHEMA,
             "Unsupported Dev audio profile schema")
    _require(profile.get("status") == "not_run", "Unsafe Dev audio profile status")
    _require(all(profile.get(key) is False for key in
                 ("productionDefaultsChanged", "humanApproval", "releaseEligible")),
             "Dev audio profile must preserve production defaults and pending approval")
    defaults = profile.get("devTestBatchSize")
    _require(type(defaults) is dict, "Missing Dev audio batch defaults")
    admitted = {}
    for name, expected_default, safe_sizes in _STAGES.values():
        section = profile.get(name)
        _require(type(section) is dict and type(section.get("primaryBatchSize")) is int
                 and section["primaryBatchSize"] == 1, "Dev audio baseline must remain batch1")
        candidates = section.get("candidateBatchSizes")
        _require(type(candidates) is list and bool(candidates)
                 and all(type(value) is int and value in safe_sizes - {1} for value in candidates)
                 and len(candidates) == len(set(candidates)), "Invalid Dev audio batch candidates")
        default = defaults.get(name)
        _require(type(default) is int and default == expected_default and default in candidates,
                 "Invalid Dev audio batch default")
        admitted[name] = {1, *candidates}

    name, default, _ = _STAGES[stage]
    selected = default if batch_size is None else batch_size
    _require(selected in admitted[name], "Batch size is not admitted by the Dev audio profile")
    return {"batchSize": selected, "profile": {
        "path": str(path), "sha256": hashlib.sha256(raw).hexdigest(), "stage": stage,
        "requestedBatchSize": selected, "defaultBatchSize": default,
        "mode": "dev_test" if batch_size is None else "dev_test_override",
        "explicitBatchSize": batch_size is not None}}
