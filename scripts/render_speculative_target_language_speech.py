#!/usr/bin/env python3
"""Pre-render machine-reviewed target text while human translation review is pending.

This is a preview/cache lane outside canonical Layer 3. It creates no speech job,
audio package, synchronized track, human approval, or release eligibility.
"""
from __future__ import annotations

import argparse
import copy
import math
import time
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Callable

try:
    from scripts import prepare_target_language_speech_job as speech
    from scripts import render_formal_target_language_speech as formal
    from scripts import render_multilingual_voice_demos as demos
    from scripts import sermon_sentence_interpretation as identity
    from scripts import validate_target_language_audio_unit as integrity
    from scripts import sermon_accounting as accounting
    from scripts import sermon_local_model_observation as local_observation
    from scripts import sermon_diagnostic_context as diagnostic
    from scripts import sermon_workflow_jobs as jobs
except ImportError:
    import prepare_target_language_speech_job as speech
    import render_formal_target_language_speech as formal
    import render_multilingual_voice_demos as demos
    import sermon_sentence_interpretation as identity
    import validate_target_language_audio_unit as integrity
    import sermon_accounting as accounting
    import sermon_local_model_observation as local_observation
    import sermon_diagnostic_context as diagnostic
    import sermon_workflow_jobs as jobs


MANIFEST_VERSION = "sermon-speculative-target-speech-v1"
UNIT_VERSION = "sermon-speculative-target-speech-unit-v1"
SCOPED_MANIFEST_VERSION = "sermon-speculative-target-speech-v2"
_monotonic = time.monotonic


def _check_deadline(deadline):
    if deadline is None:
        return
    formal.require(type(deadline) in (int, float) and math.isfinite(deadline),
                   "Invalid speculative absolute monotonic deadline")
    if _monotonic() >= deadline:
        raise TimeoutError("Speculative worker original deadline expired")


def _reserve_model_attempt(path, value):
    """One immutable scoped local attempt, durable before loading or inference."""
    data = json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False).encode() + b"\n"
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    except FileExistsError as exc:
        raise ValueError("Unknown speculative model outcome requires reconciliation") from exc
    with os.fdopen(fd, 'wb') as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    jobs._sync_directory_ancestry(path.parent)


def checked_context(paths: dict[str, Path], checkpoint_map_path: Path,
                    operation_policies_path: Path, *, strict_rubric=None,
                    diagnostic_context=None) -> dict[str, Any]:
    required = ("source", "anchor", "candidate", "policy", "adapter", "registry")
    formal.require(all(name in paths and paths[name].is_file() for name in required),
                   "Missing speculative speech input")
    data = {name: formal.package.read_object(paths[name]) for name in required}
    source, anchor, candidate = data["source"], data["anchor"], data["candidate"]
    speech._validate_schema(candidate, "sermon-target-language-candidate-v2.schema.json",
                            "target candidate")
    speech.validate_target_candidate(source, anchor, candidate,
                                     require_human_approval=False, diagnostic_context=diagnostic_context)
    formal.require(candidate["status"] == "machine_review_pass_human_review_pending"
                   and candidate["humanReview"]["translation"] == "pending",
                   "Speculative speech requires machine-pass, human-pending translation")
    speech.validate_policy_binding(candidate, data["policy"], strict_rubric=strict_rubric,
                                   diagnostic_context=diagnostic_context)
    if strict_rubric is not None:
        data["strict_rubric"] = copy.deepcopy(strict_rubric)
    if diagnostic_context is not None:
        formal.require(strict_rubric is not None, "Diagnostic preview requires the frozen strict rubric")
        data["diagnostic_context"] = diagnostic.validate_context(diagnostic_context)
    adapter, registry = data["adapter"], data["registry"]
    speech.validate_adapter(adapter, candidate["targetLocale"], registry,
                            source_package=source, candidate=candidate,
                            preview_only=True)
    formal.require(adapter["adapterId"] == "qwen3_tts_sft"
                   and (adapter["authorizationPurpose"] == "multilingual_voice_demo"
                        or (candidate["targetLocale"] == "zh-Hans"
                            and adapter["authorizationPurpose"] == "chinese_dubbing")),
                   "Speculative speech requires a registered demo/Chinese voice purpose")
    policies = formal.package.read_object(operation_policies_path)
    formal.require(all(isinstance(policies.get(name), dict)
                       and identity.json_sha256(policies[name]) == adapter[field]
                       for name, field in (("normalization", "normalizationPolicySha256"),
                                           ("asrScreening", "asrScreeningPolicySha256"),
                                           ("subtitle", "subtitlePolicySha256"))),
                   "Speculative speech operation policy differs from adapter")
    formal.require(policies["normalization"].get("policy")
                   == "exact_human_approved_target_text_no_rewrite",
                   "Speculative speech may not rewrite target text")
    mapping = demos.read_object(checkpoint_map_path, "checkpoint map")
    formal.require(mapping.get("schemaVersion") == "sermon-speaker-checkpoint-map-v1",
                   "Unsupported checkpoint map")
    speakers = [row for row in registry["speakers"]
                if row["speakerId"] == adapter["speakerId"]]
    entries = [row for row in mapping.get("checkpoints", [])
               if row.get("speakerId") == adapter["speakerId"]]
    formal.require(len(speakers) == len(entries) == 1
                   and entries[0].get("checkpointRef") == adapter["conditioningRef"]
                   == speakers[0]["checkpoint"]["checkpointRef"],
                   "Speculative checkpoint mapping differs from registry")
    checkpoint = demos.validate_checkpoint({
        "checkpointPath": entries[0].get("path"),
        "checkpointSha256": adapter["conditioningSha256"],
        "speakerKey": adapter["speakerKey"], "speakerId": adapter["speakerId"],
    })
    data["checkpoint"] = checkpoint
    data["checkpointMapFileSha256"] = identity.sha256(checkpoint_map_path)
    data["operationPoliciesFileSha256"] = identity.sha256(operation_policies_path)
    return data


def sound_identity(context: dict[str, Any], index: int, *, seed: int,
                   dtype: str, attention: str | None,
                   instruct: str | None) -> dict[str, Any]:
    adapter, candidate = context["adapter"], context["candidate"]
    group = candidate["groups"][index]
    all_fields = {
        "unitIndex": index,
        "sourceJsonSha256": identity.json_sha256(context["source"]),
        "anchorJsonSha256": identity.json_sha256(context["anchor"]),
        "translationPolicySha256": candidate["translationPolicySha256"],
        "adapterId": adapter["adapterId"], "model": adapter["model"],
        "modelRevision": adapter["modelRevision"],
        "conditioningRef": adapter["conditioningRef"],
        "checkpointMapFileSha256": context["checkpointMapFileSha256"],
        "operationPoliciesFileSha256": context["operationPoliciesFileSha256"],
        "checkpointSha256": adapter["conditioningSha256"],
        "speakerId": adapter["speakerId"], "speakerKey": adapter["speakerKey"],
        "targetLocale": candidate["targetLocale"],
        "languageParameter": adapter["languageParameter"],
        "groupId": group["translationGroupId"],
        "sourceUnitIds": group["sourceUnitIds"],
        "textSha256": hashlib.sha256(group["targetText"].encode()).hexdigest(),
        "rendererSha256": identity.sha256(Path(formal.__file__)),
        "seed": seed, "temperature": 0.7, "repetitionPenalty": 1.05,
        "maxNewTokens": 768, "dtype": dtype, "attention": attention,
        "deliveryInstruction": instruct, "ratePolicy": "natural_no_time_stretch",
    }
    return {key: all_fields[key] for key in formal.SPECULATIVE_MATCH_FIELDS}


def render(paths: dict[str, Path], checkpoint_map_path: Path,
           operation_policies_path: Path, out: Path, *,
           group_ids: list[str] | None = None, seed: int = 42,
           device: str = "cuda:0", dtype: str = "bfloat16",
           attention: str | None = "sdpa", instruct: str | None = None,
           synth_factory: Callable[..., Any] = formal.QwenSynthesizer,
           strict_rubric=None, diagnostic_context=None,
           deadline_monotonic: float | None = None,
           predecessor_spans: list[str] | None = None) -> dict[str, Any]:
    """Preview only, with one original absolute deadline for diagnostic workers.

    Deadline checks surround validation, loading, synthesis and commit; the
    caller MUST also enforce a subprocess timeout to terminate a native model
    call that cannot return to Python. A late result is never committed as pass.
    Diagnostic/rubric-scoped outputs use v2 and are not automatically admitted by
    the production preview-reuse consumer. All original pending flags are saved.
    """
    formal.require(diagnostic_context is None or deadline_monotonic is not None,
                   "Diagnostic preview requires original absolute deadline")
    _check_deadline(deadline_monotonic)
    with accounting.stage("preview.validate_inputs", work_unit_id="preview.validate_inputs",
                          depends_on=predecessor_spans) as inputs_span:
        context = checked_context(paths, checkpoint_map_path, operation_policies_path,
                                  strict_rubric=strict_rubric, diagnostic_context=diagnostic_context)
        _check_deadline(deadline_monotonic)
    candidate = context["candidate"]
    groups = candidate["groups"]
    available = {group["translationGroupId"] for group in groups}
    selected = set(group_ids) if group_ids is not None else available
    formal.require(bool(selected) and selected <= available
                   and (group_ids is None or len(group_ids) == len(selected)),
                   "Unknown, empty, or duplicate speculative group selection")
    out = out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    manifest_path = out / "manifest.json"
    snapshot_path = out / "candidate.json"
    evidence_snapshots = {name: out / f"{name}.json" for name in
                          ("source", "anchor", "policy", "adapter", "registry")}
    scoped = strict_rubric is not None or diagnostic_context is not None
    for name in ("strict_rubric", "diagnostic_context"):
        if name in context: evidence_snapshots[name] = out / (name + ".json")
    manifest = {
        "schemaVersion": SCOPED_MANIFEST_VERSION if scoped else MANIFEST_VERSION,
        "status": "preview_only", "synthesisEligible": False, "releaseEligible": False,
        "targetLocale": candidate["targetLocale"],
        "candidateJsonSha256": identity.json_sha256(candidate),
        "sourceJsonSha256": identity.json_sha256(context["source"]),
        "anchorJsonSha256": identity.json_sha256(context["anchor"]),
        "translationPolicySha256": candidate["translationPolicySha256"],
    }
    if scoped:
        manifest.update(previewRendererSha256=identity.sha256(Path(__file__)),
            strictRubricSha256=identity.json_sha256(context['strict_rubric']) if 'strict_rubric' in context else None,
            diagnosticContextSha256=identity.json_sha256(context['diagnostic_context']) if 'diagnostic_context' in context else None,
            humanAcceptance='pending', productionEligible=False)
    with accounting.stage("preview.freeze_inputs", work_unit_id="preview.freeze_inputs",
                          depends_on=[inputs_span]) as previous_span:
        if manifest_path.exists():
            formal.require(formal.package.read_object(manifest_path) == manifest
                           and snapshot_path.is_file()
                           and identity.json_sha256(formal.package.read_object(snapshot_path))
                           == manifest["candidateJsonSha256"]
                           and all(path.is_file()
                                   and formal.package.read_object(path) == context[name]
                                   for name, path in evidence_snapshots.items()),
                           "Existing speculative output belongs to another candidate")
        else:
            formal.require(not snapshot_path.exists() and not (out / "units").exists()
                           and not (out / "receipts").exists()
                           and not any(path.exists() for path in evidence_snapshots.values()),
                           "Uncommitted speculative output cannot be adopted")
            formal.write_json_atomic(snapshot_path, candidate)
            for name, path in evidence_snapshots.items():
                formal.write_json_atomic(path, context[name])
            formal.write_json_atomic(manifest_path, manifest)
    context_binding = {'previewContextSha256': identity.json_sha256(manifest)} if scoped else {}
    model = None
    load_span = None
    rendered = []
    for index, group in enumerate(groups):
        if group["translationGroupId"] not in selected:
            continue
        _check_deadline(deadline_monotonic)
        work = f"preview.{candidate['targetLocale']}.{index:04d}"
        with accounting.orchestration(work + '.dispatch', work_unit_id=work + '.dispatch',
                                      depends_on=[previous_span]) as dispatch_span:
            expected = sound_identity(context, index, seed=seed, dtype=dtype,
                                      attention=attention, instruct=instruct)
            wav_path = out / f"units/unit-{index:04d}.wav"
            receipt_path = out / f"receipts/unit-{index:04d}.json"
            attempt_path = out / f"receipts/unit-{index:04d}.attempt.json"
            partial = wav_path.with_suffix(".partial.wav")
            cache_hit = wav_path.exists() or receipt_path.exists()
        with accounting.stage(work, cache_hit=cache_hit):
            with accounting.stage(work + '.cache_admission', work_unit_id=work + '.cache_admission',
                                  depends_on=[dispatch_span], cache_hit=cache_hit) as admission_span:
                if cache_hit:
                    formal.require(receipt_path.is_file(), "Uncommitted speculative unit cannot be reused")
                    receipt = formal.package.read_object(receipt_path)
                    formal.require(receipt.get("schemaVersion") == UNIT_VERSION
                                   and receipt.get("status") == "preview_only"
                                   and receipt.get("candidateJsonSha256") == manifest["candidateJsonSha256"]
                                   and receipt.get("soundIdentity") == expected
                                   and all(receipt.get(k) == v for k, v in context_binding.items()),
                                   "Speculative unit identity changed")
                    if not wav_path.exists():
                        formal.require(partial.is_file() and receipt.get("audioSha256") == identity.sha256(partial),
                                       "Committed speculative partial audio is missing or changed")
                        integrity.probe_full_decode(partial)
                        _check_deadline(deadline_monotonic)
                        os.replace(partial, wav_path)
                    formal.require(not partial.exists() and receipt.get("audioSha256") == identity.sha256(wav_path),
                                   "Speculative unit identity or audio changed")
                    decoded = integrity.probe_full_decode(wav_path)
                    formal.require(type(receipt.get("durationSeconds")) in (int, float)
                                   and receipt["durationSeconds"] == decoded["durationSeconds"],
                                   "Speculative cached duration differs from decoded audio; requires reconciliation")
                else:
                    formal.require(not partial.exists(), "Uncommitted speculative audio exists")
                    formal.require(not scoped or not attempt_path.exists(),
                                   "Unknown speculative model outcome requires reconciliation")
                _check_deadline(deadline_monotonic)
            if not cache_hit:
                wav_path.parent.mkdir(parents=True, exist_ok=True)
                receipt_path.parent.mkdir(parents=True, exist_ok=True)
                model_name = context['adapter']['model']
                input_hash = identity.json_sha256(expected)
                # Validate identity before spending local model time.
                local_observation.safe_observation(dict(schemaVersion=local_observation.SCHEMA,
                    model=model_name, checkpointSha256=context['adapter']['conditioningSha256'],
                    inputSha256=input_hash, outputSha256=None, status='started', elapsedSeconds=None,
                    usageProvenance='local_execution_no_provider_receipt', providerTokens=None, providerCostUsd=None))
                if scoped:
                    _reserve_model_attempt(attempt_path, dict(context_binding,
                        soundIdentitySha256=input_hash, status='model_attempt_reserved'))
                if model is None:
                    with accounting.stage(work + '.model_load', work_unit_id=work + '.model_load',
                                          depends_on=[admission_span]) as load_span:
                        _check_deadline(deadline_monotonic)
                        model = synth_factory(context["checkpoint"], device=device, dtype=dtype,
                                              attention=attention, instruct=instruct)
                        _check_deadline(deadline_monotonic)
                with accounting.stage(work + '.synthesis', work_unit_id=work + '.synthesis', billing='local',
                                      executor_type='production_model', depends_on=[admission_span, load_span]) as synth_span:
                    _check_deadline(deadline_monotonic)
                    local_observation.record(model_name, context['adapter']['conditioningSha256'],
                                             input_hash, status='started', span_id=synth_span)
                    started = _monotonic()
                    try:
                        samples, rate = model(group["targetText"], context["adapter"]["languageParameter"],
                                              context["adapter"]["speakerKey"], seed=seed + index)
                        elapsed = _monotonic() - started
                        _check_deadline(deadline_monotonic)
                    except BaseException as exc:
                        accounting._finalize(lambda: local_observation.record(model_name, context['adapter']['conditioningSha256'], input_hash,
                            status='failed', elapsed_seconds=max(0, _monotonic() - started), span_id=synth_span), exc)
                        raise
                    local_observation.record(model_name, context['adapter']['conditioningSha256'], input_hash,
                        status='completed', elapsed_seconds=elapsed, span_id=synth_span)
                with accounting.stage(work + '.audio_write', work_unit_id=work + '.audio_write',
                                      depends_on=[synth_span]) as write_span:
                    _check_deadline(deadline_monotonic)
                    formal.write_pcm16(partial, samples, int(rate))
                with accounting.stage(work + '.validation', work_unit_id=work + '.validation',
                                      depends_on=[write_span]) as validation_span:
                    decoded = integrity.probe_full_decode(partial)
                    _check_deadline(deadline_monotonic)
                with accounting.stage(work + '.commit', work_unit_id=work + '.commit',
                                      depends_on=[validation_span]) as completed_span:
                    receipt = {'schemaVersion': UNIT_VERSION, 'status': 'preview_only',
                        'candidateJsonSha256': manifest['candidateJsonSha256'], **context_binding,
                        'soundIdentity': expected, 'audioSha256': identity.sha256(partial),
                        'durationSeconds': decoded['durationSeconds'], 'fullDecode': 'pass'}
                    _check_deadline(deadline_monotonic)
                    formal.write_json_atomic(receipt_path, receipt)
                    os.replace(partial, wav_path)
            else:
                completed_span = admission_span
            accounting.record_workload(work, {'unitIndex': index, 'cacheHit': cache_hit,
                'modelExecutedCurrentAttempt': not cache_hit, 'previewOnly': True,
                'productionEligible': False, 'humanAcceptancePending': True, 'fullDecodePassed': True,
                'inputTextCodePoints': len(group['targetText']), 'audioSeconds': decoded['durationSeconds'],
                'checkpointSha256': context['adapter']['conditioningSha256'],
                'modelIdentitySha256': identity.json_sha256({'model': context['adapter']['model'],
                                                            'revision': context['adapter']['modelRevision']}),
                'soundIdentitySha256': identity.json_sha256(expected), 'audioSha256': identity.sha256(wav_path),
                'cacheUnitReceiptSha256': identity.sha256(receipt_path),
                'cacheManifestSha256': identity.sha256(manifest_path),
                'diagnosticContextSha256': manifest.get('diagnosticContextSha256'),
                'providerTokensApplicable': False, 'providerInputTokens': None, 'providerOutputTokens': None,
                'providerCachedInputTokens': None, 'providerCostUsd': None})
            rendered.append(group['translationGroupId'])
        previous_span = completed_span
    _check_deadline(deadline_monotonic)
    return {'status': 'preview_only', 'targetLocale': candidate['targetLocale'],
            'renderedGroupIds': rendered, 'out': str(out)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("source", "anchor", "candidate", "policy", "adapter", "registry"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    parser.add_argument("--checkpoint-map", type=Path, required=True)
    parser.add_argument("--audio-operation-policies", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--group-id", action="append", dest="group_ids")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--device", default="cuda:0")
    parser.add_argument("--dtype", choices=("bfloat16", "float32"), default="bfloat16")
    parser.add_argument("--attention", default="sdpa")
    parser.add_argument("--instruct")
    parser.add_argument("--strict-rubric", type=Path)
    parser.add_argument("--diagnostic-context", type=Path)
    parser.add_argument("--deadline-monotonic", type=float)
    args = parser.parse_args()
    paths = {name: getattr(args, name) for name in
             ("source", "anchor", "candidate", "policy", "adapter", "registry")}
    print(json.dumps(render(paths, args.checkpoint_map,
                            args.audio_operation_policies, args.out,
                            group_ids=args.group_ids, seed=args.seed,
                            device=args.device, dtype=args.dtype,
                            attention=args.attention, instruct=args.instruct,
                            strict_rubric=formal.package.read_object(args.strict_rubric) if args.strict_rubric else None,
                            diagnostic_context=formal.package.read_object(args.diagnostic_context) if args.diagnostic_context else None,
                            deadline_monotonic=args.deadline_monotonic),
                     ensure_ascii=False))


if __name__ == "__main__":
    main()
