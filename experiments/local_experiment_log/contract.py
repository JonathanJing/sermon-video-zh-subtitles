"""Dependency-free contract definitions. No network or model dependencies."""
import hashlib
import json
from pathlib import Path
import sys
import re
from datetime import datetime

VERSION = "sermon-local-experiment-measurement-v1"
EVENTS = ["trial.configured", "span.started", "span.ended", "admission.decided",
          "artifact.manifested", "artifact.verified", "quality.checked",
          "resource.sampled", "trial.completed"]
SPANS = ["request", "admission", "queue", "worker.start", "worker.session",
         "model.load", "warmup", "batch.inference", "artifact.write",
         "artifact.return", "workload.budget"]


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def ident(nullable=False):
    return {"type": ["string", "null"] if nullable else "string", "minLength": 1, "maxLength": 256}


HASH = {"type": "string", "pattern": "^[0-9a-f]{64}$"}
NULL_HASH = {**HASH, "type": ["string", "null"]}
UNITS = {"type": "array", "minItems": 1, "uniqueItems": True,
         "items": {"type": "integer", "minimum": 0}}
RESOURCE_SCHEMA = {
    "type": "object", "minProperties": 1, "additionalProperties": False,
    "properties": {
        **{k: {"type": ["number", "null"], "minimum": 0} for k in
           ["system_available_gib", "worker_rss_mib", "cuda_allocated_mib", "cuda_reserved_mib",
            "cuda_peak_allocated_mib", "gpu_temperature_c", "gpu_util_percent"]},
        "other_compute_pids": {"type": ["array", "null"], "uniqueItems": True,
                               "items": {"type": "integer", "minimum": 1}}
    }
}

CONFIG_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["sample_sha256", "checkpoint_sha256", "code_sha256", "runtime_sha256",
                 "duration_mode", "duration_seconds", "budget_scope", "unit_ids",
                 "load_policy", "batch_size", "device", "dtype", "generation",
                 "output_cache_hit", "dummy_warmup"],
    "properties": {
        **{key: HASH for key in ["sample_sha256", "checkpoint_sha256", "code_sha256", "runtime_sha256"]},
        "duration_mode": {"enum": ["fixed_sample", "wall_budget"]},
        "duration_seconds": {"type": "number", "exclusiveMinimum": 0},
        "budget_scope": {"enum": [None, "generation_and_validation", "including_load"]},
        "unit_ids": UNITS,
        "load_policy": {"enum": ["load_once_per_trial_process", "preload_and_reuse_admitted_worker"]},
        "batch_size": {"type": "integer", "minimum": 1},
        "device": ident(), "dtype": ident(),
        "generation": {"type": "object", "minProperties": 1},
        "output_cache_hit": {"type": "boolean"}, "dummy_warmup": {"type": "boolean"}
    }
}

EVENT_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "title": "Hash-bound experiment measurement sidecar v1; not a production log envelope",
    "type": "object", "additionalProperties": False,
    "required": ["schema_version", "evidence_kind", "event_id", "experiment_id", "trial_id",
                 "trace_id", "span_id", "parent_span_id", "links", "event", "layer_id", "component",
                 "host_role", "host_id", "producer_id", "sequence", "clock_id", "monotonic_ns",
                 "timestamp_utc", "level", "job_id", "attempt", "worker_id", "config_sha256", "payload"],
    "properties": {
        "schema_version": {"enum": [VERSION]},
        "evidence_kind": {"enum": ["real", "synthetic", "replay"]},
        **{key: ident() for key in ["event_id", "experiment_id", "trace_id", "component", "host_role",
                                  "host_id", "producer_id", "clock_id"]},
        **{key: ident(True) for key in ["trial_id", "span_id", "parent_span_id", "job_id", "worker_id"]},
        "links": {"type": "array", "items": {"type": "object", "additionalProperties": False,
                  "required": ["relation", "trace_id", "span_id"],
                  "properties": {"relation": {"enum": ["uses_preloaded_model", "caused_by"]},
                                 "trace_id": ident(), "span_id": ident()}}},
        "event": {"enum": EVENTS}, "layer_id": {"enum": ["L1", "L2", "L3", "L4"]},
        "level": {"enum": ["info", "warning", "error"]},
        "sequence": {"type": "integer", "minimum": 1},
        "monotonic_ns": {"type": "integer", "minimum": 0},
        "timestamp_utc": {"type": "string", "format": "date-time"},
        "attempt": {"type": ["integer", "null"], "minimum": 1},
        "config_sha256": NULL_HASH,
        "payload": {"type": "object"}
    }
}

MANIFEST_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object", "additionalProperties": False,
    "required": ["schema_version", "experiment_id", "evidence_kind", "duration_mode", "duration_seconds",
                 "layer_component_mapping", "admission_design_reference", "artifact_return_reference"],
    "properties": {
        "schema_version": {"enum": ["local.experiment.manifest.v1"]},
        "experiment_id": ident(), "evidence_kind": {"enum": ["real", "synthetic", "replay"]},
        "duration_mode": {"enum": ["fixed_sample", "wall_budget"]},
        "duration_seconds": {"type": "number", "exclusiveMinimum": 0},
        "layer_component_mapping": {"type": "object", "minProperties": 1},
        "required_layers": {"type": "array", "minItems": 1, "uniqueItems": True,
                            "items": {"enum": ["L1", "L2", "L3", "L4"]}},
        "admission_design_reference": ident(), "artifact_return_reference": ident()
    }
}


def validate_schema(value, schema, path="$"):
    """Validate the explicit JSON-Schema subset used by the exported contract."""
    kinds = {"null": value is None, "boolean": type(value) is bool,
             "integer": type(value) is int, "number": type(value) in (int, float),
             "string": isinstance(value, str), "array": isinstance(value, list),
             "object": isinstance(value, dict)}
    wanted = schema.get("type")
    if wanted and not any(kinds[k] for k in ([wanted] if isinstance(wanted, str) else wanted)):
        raise ValueError(f"{path}: wrong type")
    if "enum" in schema and not any(type(value) is type(x) and value == x for x in schema["enum"]):
        raise ValueError(f"{path}: value outside enum")
    if value is None:
        return
    if isinstance(value, dict):
        for key in schema.get("required", []):
            if key not in value:
                raise ValueError(f"{path}: missing {key}")
        if len(value) < schema.get("minProperties", 0):
            raise ValueError(f"{path}: too few properties")
        props = schema.get("properties", {})
        if schema.get("additionalProperties") is False and set(value) - set(props):
            raise ValueError(f"{path}: unknown properties {sorted(set(value) - set(props))}")
        for key, item in value.items():
            if key in props:
                validate_schema(item, props[key], f"{path}.{key}")
    elif isinstance(value, list):
        if len(value) < schema.get("minItems", 0):
            raise ValueError(f"{path}: too few items")
        if schema.get("uniqueItems") and len({canonical(x) for x in value}) != len(value):
            raise ValueError(f"{path}: duplicate items")
        for i, item in enumerate(value):
            validate_schema(item, schema.get("items", {}), f"{path}[{i}]")
    elif isinstance(value, str):
        if len(value) < schema.get("minLength", 0) or len(value) > schema.get("maxLength", float("inf")):
            raise ValueError(f"{path}: string length invalid")
        if "pattern" in schema and not re.fullmatch(schema["pattern"], value):
            raise ValueError(f"{path}: pattern mismatch")
        if schema.get("format") == "date-time":
            if not value.endswith(("Z", "+00:00")):
                raise ValueError(f"{path}: UTC timestamp required")
            datetime.fromisoformat(value.replace("Z", "+00:00"))
    elif type(value) in (int, float):
        if value < schema.get("minimum", -float("inf")) or value <= schema.get("exclusiveMinimum", -float("inf")):
            raise ValueError(f"{path}: numeric bound violated")


def need(payload, fields):
    for key, schema in fields.items():
        if key not in payload:
            raise ValueError(f"payload: missing {key}")
        validate_schema(payload[key], schema, f"payload.{key}")


def validate_event(event):
    canonical(event)  # Reject nonfinite JSON values, including nested payload values.
    validate_schema(event, EVENT_SCHEMA)
    p, name = event["payload"], event["event"]
    if name.startswith("span."):
        if not event["span_id"]:
            raise ValueError("span event requires span_id")
        need(p, {"name": {"enum": SPANS}})
        if name == "span.ended":
            need(p, {"status": {"enum": ["succeeded", "failed", "cancelled", "timeout"]}})
        if p["name"] == "batch.inference":
            need(p, {"unit_ids": UNITS, "cuda_synchronized": {"type": "boolean"},
                     "worker_pid": {"type": "integer", "minimum": 1}})
            if name == "span.ended":
                need(p, {"actual_batch_size": {"type": "integer", "minimum": 1},
                         "returned_wave_count": {"type": "integer", "minimum": 0}})
        if p["name"] == "model.load":
            need(p, {"identity": {"type": "object", "required": ["checkpoint_sha256", "code_sha256", "runtime_sha256"],
                     "properties": {k: HASH for k in ["checkpoint_sha256", "code_sha256", "runtime_sha256"]}},
                     "worker_pid": {"type": "integer", "minimum": 1}})
    elif name == "trial.configured":
        need(p, {"config": CONFIG_SCHEMA})
        if not event["trial_id"] or digest(p["config"]) != event["config_sha256"]:
            raise ValueError("trial config identity mismatch")
    elif name == "admission.decided":
        need(p, {"decision": {"enum": ["admitted", "rejected"]}, "reference": ident()})
    elif name in ("artifact.manifested", "artifact.verified"):
        need(p, {"artifact_id": ident(), "sha256": HASH,
                 "size_bytes": {"type": "integer", "minimum": 0}, "unit_ids": UNITS})
        if name == "artifact.verified":
            need(p, {"bytes_verified": {"type": "boolean"}})
    elif name == "quality.checked":
        need(p, {"batch_span_id": ident(), "unit_ids": UNITS,
                 **{k: {"type": "boolean"} for k in ["finite_signal", "duration_valid", "truncation_detected"]},
                 "sample_rate_hz": {"type": "integer", "minimum": 1},
                 "generated_audio_seconds": {"type": "number", "exclusiveMinimum": 0},
                 "human_listening_status": {"enum": ["pending", "passed", "failed"]}})
    elif name == "trial.completed":
        need(p, {"status": {"enum": ["succeeded", "failed", "cancelled", "timeout", "budget_exhausted"]},
                 "receipt_reference": ident()})
    elif name == "resource.sampled":
        need(p, {"metrics": RESOURCE_SCHEMA, "source": ident()})


def validate_manifest(manifest):
    canonical(manifest)
    validate_schema(manifest, MANIFEST_SCHEMA)
    layers = set(manifest["layer_component_mapping"].values())
    if not layers or not layers.issubset({"L1", "L2", "L3", "L4"}) or not set(manifest.get("required_layers", layers)).issubset(layers):
        raise ValueError("manifest has invalid logical layer mapping")


def template():
    result = {key: None for key in EVENT_SCHEMA["required"]}
    result.update(schema_version=VERSION, links=[], payload={})
    return result
