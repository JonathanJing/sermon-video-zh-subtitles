"""Export completed accounting v2 spans to local OTLP/JSON; never send telemetry."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sys

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.sermon_accounting import SCHEMA, read_events

# Export only known application labels. Unknown labels retain a hash, never text.
LABELS = frozenset("""
weekly_dubbing job_validation cache_validation transfer_upload render render_recovery
transfer_download render_validation assemble candidate_validation screening source_alignment local_asr timing sync_assembly
saturday_timeline saturday_generation sermon_pipeline sermon_reading_edition
sermon_interpretation_notes post_live_multistage_timeline dubbing_sync_assembly
same_video_intake same_video_handoff pipeline source_metadata download mobile_pdf
reading_edition reading_pdf interpretation context_pack publication
pipeline.clip pipeline.transcribe pipeline.segment pipeline.source_review pipeline.translate
transcription.cache english_correction.cache translation.cache translation.segment_cache
api.retry_backoff chat.retry_backoff notes.generate notes.render_pdf
reading.batch_cache reading.edit_pass_1 reading.edit_pass_2 reading.codex_call
timeline.upload timeline.metadata timeline.review_cache timeline.download_handoff
timeline.download_archive timeline.probe same_video.validate_source same_video.archive
same_video.validate_reviewed same_video.render_reviewed_pdfs same_video.seal
""".split())
PAIRS = {"run_started": ("run", "start"), "run_finished": ("run", "end"),
         "workflow_started": ("workflow", "start"), "workflow_finished": ("workflow", "end"),
         "stage_started": ("stage", "start"), "stage_finished": ("stage", "end")}
HASH_KEYS = ("jobSha256", "checkpointSha256", "inputManifestSha256", "timingReportSha256")
TOKEN_KEYS = ("inputTokens", "outputTokens", "cachedInputTokens", "reasoningTokens")


def hashed(*parts):
    return hashlib.sha256(json.dumps(parts, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()


def trace_id(run):
    return hashed("sermon-trace-v1", run)[:32]


def span_id(key):
    return hashed("sermon-span-v1", *key)[:16]


def nanos(value):
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ValueError("timezone required")
    delta = parsed.astimezone(timezone.utc) - datetime(1970, 1, 1, tzinfo=timezone.utc)
    ns = (delta.days * 86400 + delta.seconds) * 1_000_000_000 + delta.microseconds * 1000
    if not 0 < ns < 2**64:
        raise ValueError("timestamp outside OTLP range")
    return ns


def attribute(key, value):
    if type(value) is bool:
        encoded = {"boolValue": value}
    elif type(value) is int:
        encoded = {"intValue": str(value)}
    else:
        encoded = {"stringValue": value}
    return {"key": key, "value": encoded}


def export(directory):
    events, damaged = read_events(directory)
    diagnostics = [{"code": "damaged_event", "line": d["line"], "sha256": d["sha256"]} for d in damaged]
    pairs = defaultdict(lambda: {"start": [], "end": []})
    accepted, seen = [], set()

    def diagnostic(code, key=None):
        row = {"code": code}
        if key is not None:
            row.update(traceId=trace_id(key[0]), spanId=span_id(key))
        diagnostics.append(row)

    for event in events:
        if event.get("schemaVersion") != SCHEMA:
            diagnostic("unsupported_event_schema")
            continue
        identity = (event["runId"], event["eventId"])
        if identity in seen:
            diagnostic("duplicate_event_id")
            continue
        seen.add(identity)
        accepted.append(event)
        if event["event"] not in PAIRS:
            continue
        kind, edge = PAIRS[event["event"]]
        ident = event["runId"] if kind == "run" else event.get("workflowId" if kind == "workflow" else "spanId")
        if not isinstance(ident, str) or not ident:
            diagnostic("missing_span_identity")
            continue
        pairs[(event["runId"], kind, ident)][edge].append(event)

    spans, parents = {}, {}
    for key, edges in sorted(pairs.items()):
        if len(edges["start"]) != 1 or len(edges["end"]) != 1:
            diagnostic("unfinished_span" if len(edges["start"]) == 1 and not edges["end"] else "missing_or_ambiguous_span_edges", key)
            continue
        start, end = edges["start"][0], edges["end"][0]
        match_fields = ("workflow",) if key[1] == "run" else (("workflow", "parentWorkflowId") if key[1] == "workflow" else ("stage", "workflowId", "parentSpanId"))
        # workflow_finished does not repeat parentWorkflowId in accounting v2.
        match_fields = tuple(field for field in match_fields if field != "parentWorkflowId")
        if any(start.get(field) != end.get(field) for field in match_fields):
            diagnostic("span_identity_mismatch", key)
            continue
        if end.get("status") not in {"completed", "failed"}:
            diagnostic("unknown_finished_status", key)
            continue
        try:
            begin = nanos(start.get("startedAt", start["recordedAt"]))
            finish = nanos(end["recordedAt"])
            if finish < begin:
                raise ValueError("clock moved backwards")
        except (ValueError, TypeError, OverflowError):
            diagnostic("invalid_span_time", key)
            continue
        run, kind, ident = key
        raw_label = start.get("stage") if kind == "stage" else start.get("workflow")
        label = raw_label if raw_label in LABELS else "redacted_label"
        attrs = [attribute("sermon.accounting.run.sha256", hashed(run)),
                 attribute("sermon.accounting.identity.sha256", hashed(kind, ident)),
                 attribute("sermon.accounting.kind", kind)]
        if isinstance(raw_label, str):
            attrs.append(attribute("sermon.accounting.label.sha256", hashed(raw_label)))
        if isinstance(start.get("workflowId"), str):
            attrs.append(attribute("sermon.accounting.workflow.sha256", hashed(start["workflowId"])))
        if type(end.get("cacheHit")) is bool:
            attrs.append(attribute("sermon.cache_hit", end["cacheHit"]))
        metadata = start.get("metadata", {})
        if isinstance(metadata, dict):
            for field in HASH_KEYS:
                value = metadata.get(field)
                if isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value):
                    attrs.append(attribute("sermon." + field, value))
        spans[key] = {"traceId": trace_id(run), "spanId": span_id(key), "name": "sermon." + kind + "." + label,
                      "kind": 1, "startTimeUnixNano": str(begin), "endTimeUnixNano": str(finish),
                      "attributes": attrs, "status": {"code": 2 if end["status"] == "failed" else 1}}
        if any(start.get(field) is not None and (not isinstance(start[field], str) or not start[field])
               for field in ("parentWorkflowId", "parentSpanId")):
            diagnostic("invalid_parent_identity", key)
            continue
        if kind == "workflow":
            parents[key] = (run, "workflow", start["parentWorkflowId"]) if start.get("parentWorkflowId") else (run, "run", run)
        elif kind == "stage":
            if start.get("parentSpanId"):
                parents[key] = (run, "stage", start["parentSpanId"])
            elif start.get("workflowId"):
                parents[key] = (run, "workflow", start["workflowId"])

    for key, parent in parents.items():
        if parent not in spans:
            diagnostic("parent_not_exported", key)
            continue
        chain, cursor = {key}, parent
        while cursor in parents and cursor not in chain:
            chain.add(cursor)
            cursor = parents[cursor]
        if cursor in chain:
            diagnostic("parent_cycle", key)
            continue
        spans[key]["parentSpanId"] = span_id(parent)

    # API usage is counted only within its recorded stage, never summed into ancestors.
    counters = defaultdict(Counter)
    for event in accepted:
        if event["event"] != "api_attempt":
            continue
        key = (event["runId"], "stage", event.get("spanId"))
        if key not in spans:
            diagnostic("api_without_exported_stage")
            continue
        counters[key]["apiAttempts"] += 1
        if event.get("status") == "failed":
            counters[key]["failedApiAttempts"] += 1
        for field in TOKEN_KEYS:
            value = event.get("usage", {}).get(field)
            if type(value) is int and 0 <= value < 2**63:
                counters[key][field] += value
    for key, counts in counters.items():
        for field, value in sorted(counts.items()):
            if value < 2**63:
                spans[key]["attributes"].append(attribute("sermon." + field, value))
            else:
                diagnostic("counter_overflow", key)

    payload = {"resourceSpans": [{"resource": {"attributes": [attribute("service.name", "sermon-saturday-offline")]},
                "scopeSpans": [{"scope": {"name": "sermon.accounting.otlp_export", "version": "1"},
                                "spans": list(spans.values())}]}]}
    report = {"schemaVersion": "sermon-trace-export-diagnostics-v1", "status": "partial" if diagnostics else "exported",
              "sourceSchema": SCHEMA, "readableEvents": len(events), "exportedSpans": len(spans),
              "traceCount": len({span["traceId"] for span in spans.values()}), "diagnostics": diagnostics,
              "qaAcceptance": "not_evaluated", "costCompleteness": "not_evaluated", "networkExported": False}
    return payload, report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--accounting-dir", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--diagnostics", type=Path, required=True)
    args = parser.parse_args()
    try:
        source = (args.accounting_dir / "events.jsonl").resolve()
        outputs = (args.out.resolve(), args.diagnostics.resolve())
        aliases = any(path.exists() and source.exists() and path.samefile(source) for path in outputs)
        aliases = aliases or (all(path.exists() for path in outputs) and outputs[0].samefile(outputs[1]))
        if aliases or len({source, *outputs}) != 3:
            raise ValueError("output paths must be distinct from the source")
        payload, report = export(args.accounting_dir)
        for path, value in ((args.out, payload), (args.diagnostics, report)):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
            path.chmod(0o600)
    except (ValueError, OSError, TypeError) as exc:
        print(json.dumps({"status": "input_error", "errorType": type(exc).__name__}))
        return 2
    print(json.dumps({"status": report["status"], "exportedSpans": report["exportedSpans"]}))
    return 1 if report["status"] == "partial" else 0


if __name__ == "__main__":
    sys.exit(main())
