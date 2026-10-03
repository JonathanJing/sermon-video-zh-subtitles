#!/usr/bin/env python3
"""Render a source-bound podcast speech job with two concurrent Qwen workers.

Each worker loads one authorized speaker checkpoint and synthesizes only that
speaker's units in full batches of eight. Per-unit WAV and receipt files make a
failed run resumable. This command creates Layer 3 render evidence only; it
does not perform audio screening, human listening approval, or publication.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import multiprocessing as mp
import os
from pathlib import Path
import socket
import tempfile
import time
from typing import Any


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def json_sha(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":")).encode()).hexdigest()


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = json.dumps(value, ensure_ascii=False, indent=2).encode() + b"\n"
    with tempfile.NamedTemporaryFile(dir=path.parent, prefix="." + path.name,
                                     delete=False) as f:
        temp = Path(f.name)
        f.write(data)
        f.flush()
        os.fsync(f.fileno())
    os.replace(temp, path)


def validate(job: dict[str, Any], route: dict[str, Any], source: dict[str, Any],
             candidate: dict[str, Any], approval: dict[str, Any] | None,
             workers: list[dict[str, Any]], source_file_sha256: str,
             review_waiver: dict[str, Any] | None = None) -> None:
    require(job.get("schemaVersion") in {"sermon-target-language-speech-job-v3-podcast",
                                         "sermon-target-language-speech-job-v4-multilingual-podcast"}
            and job.get("synthesisEligible") is True and job.get("releaseEligible") is False,
            "Job is not a prepared podcast Layer 3 job")
    require(source.get("status") == "ready_for_translation"
            and source.get("review", {}).get("humanApproval") is True,
            "English source package is not human approved")
    if review_waiver is None:
        require(candidate.get("status") == "human_translation_approved"
                and candidate.get("humanReview", {}).get("translation") == "approved"
                and approval is not None
                and approval.get("schemaVersion") == "sermon-target-language-human-review-receipt-v1"
                and approval.get("decision") == "approved"
                and approval.get("candidateJsonSha256") == json_sha(candidate),
                "Target-language candidate approval is missing or mismatched")
    else:
        require(approval is None
                and candidate.get("status") == "machine_review_pass_human_review_pending"
                and candidate.get("releaseEligible") is False
                and candidate.get("humanReview", {}).get("translation") == "pending",
                "A review waiver requires a machine-passed, human-review-pending candidate")
        require(review_waiver.get("schemaVersion") == "sermon-podcast-layer2-user-review-waiver-v1"
                and review_waiver.get("decision") == "user_authorized_skip_content_review"
                and review_waiver.get("humanApproval") is False
                and review_waiver.get("releaseEligible") is False
                and review_waiver.get("audioHumanReviewRequired") is True
                and review_waiver.get("targetLocale") == candidate.get("targetLocale")
                and review_waiver.get("englishSourcePackageJsonSha256") == candidate.get("englishSourcePackageJsonSha256")
                and review_waiver.get("anchorManifestSha256") == candidate.get("anchorManifestSha256")
                and review_waiver.get("translationPolicySha256") == candidate.get("translationPolicySha256"),
                "Content-review waiver is missing or bound to different evidence")
    require(job.get("targetLocale") == candidate.get("targetLocale")
            and job.get("inputs", {}).get("targetLanguageCandidate", {}).get("jsonSha256") == json_sha(candidate),
            "Speech job is bound to a different target-language candidate")
    require(route.get("status") == "approved" and len(workers) == 2
            and route.get("sourcePackageFileSha256") == source_file_sha256
            and route.get("targetCandidateCanonicalJsonSha256") == json_sha(candidate),
            "Speaker route or worker plan is not approved")
    if approval is not None:
        require(approval.get("englishSourcePackageJsonSha256") == json_sha(source),
                "Human approval is bound to a different English source")
    else:
        inputs = job.get("inputs", {})
        require(inputs.get("englishSourcePackage", {}).get("jsonSha256") == json_sha(source)
                and inputs.get("targetLanguageCandidate", {}).get("jsonSha256") == json_sha(candidate)
                and inputs.get("contentReviewWaiver", {}).get("jsonSha256") == json_sha(review_waiver),
                "Speech job inputs do not bind source, candidate, and waiver")
    groups = {row["translationGroupId"]: row for row in candidate.get("groups", [])}
    route_rows = {row["translationGroupId"]: row for row in route.get("groups", [])}
    units = job.get("units", [])
    require(len(units) == len(groups) == len(route_rows) == 839,
            "Podcast job, candidate, and route must cover the same complete 839 groups")
    require(set(groups) == set(route_rows) == {u["translationGroupId"] for u in units},
            "Job/candidate/route group coverage differs")
    worker_by_id = {w["workerId"]: w for w in workers}
    require(len(worker_by_id) == 2, "Worker IDs are not unique")
    for u in units:
        group = groups[u["translationGroupId"]]
        target = group.get("targetText")
        route_row = route_rows[u["translationGroupId"]]
        w = worker_by_id.get(u["workerId"])
        require(isinstance(target, str) and target == u.get("text")
                and route_row.get("speakerId") == u.get("speakerId")
                and w and w["speakerId"] == u["speakerId"]
                and w["checkpointSha256"] == u["checkpointSha256"],
                "Unit text or speaker/checkpoint route differs from approved evidence")
    for w in workers:
        checkpoint = Path(w["checkpointPath"])
        require(checkpoint.is_dir() and sha256(checkpoint / "model.safetensors") == w["checkpointSha256"],
                "Speaker checkpoint hash mismatch: " + w["workerId"])


def require(ok: bool, message: str) -> None:
    if not ok:
        raise ValueError(message)


def _render_worker(worker: dict[str, Any], units: list[dict[str, Any]], out: str,
                   base_seed: int, device: str, dtype: str, result_path: str) -> None:
    import numpy as np
    import soundfile as sf
    import torch
    from qwen_tts import Qwen3TTSModel

    checkpoint = worker["checkpointPath"]
    model = Qwen3TTSModel.from_pretrained(
        checkpoint, device_map=device,
        dtype=torch.bfloat16 if dtype == "bfloat16" else torch.float32,
        attn_implementation="sdpa")
    root = Path(out)
    rows = []
    own = [u for u in units if u["workerId"] == worker["workerId"]]
    for pos in range(0, len(own), 8):
        batch = own[pos:pos + 8]
        batch_seed = base_seed + batch[0]["unitIndex"]
        missing = []
        for u in batch:
            wav = root / u["outputRelativePath"]
            receipt = wav.with_suffix(".render.json")
            expected = {"groupId": u["translationGroupId"],
                        "textSha256": hashlib.sha256(u["text"].encode()).hexdigest(),
                        "speakerId": u["speakerId"], "checkpointSha256": worker["checkpointSha256"],
                        "workerId": worker["workerId"], "batchSize": len(batch),
                        "batchSeed": batch_seed, "seedPolicy": "base_plus_global_batch_start_v1"}
            if wav.exists() or receipt.exists():
                require(wav.is_file() and receipt.is_file(), "Partial/orphan audio requires inspection")
                previous = json.loads(receipt.read_text())
                require(previous.get("identity") == expected and previous.get("audioSha256") == sha256(wav),
                        "Existing unit does not match frozen render identity")
                rows.append({**expected, "audioPath": str(wav), "audioSha256": sha256(wav),
                             "durationSeconds": float(sf.info(str(wav)).duration), "reused": True})
            else:
                missing.append(u)
        if not missing:
            continue
        require(len(missing) == len(batch),
                "Partial cached batch cannot be replayed with the original batch membership")
        torch.manual_seed(batch_seed)
        torch.cuda.manual_seed_all(batch_seed)
        started = time.time()
        wavs, rate = model.generate_custom_voice(
            text=[u["text"] for u in missing], language=[worker["languageParameter"]] * len(missing),
            speaker=[worker["speakerKey"]] * len(missing), temperature=0.7,
            repetition_penalty=1.05, max_new_tokens=768)
        require(len(wavs) == len(missing) and int(rate) > 0,
                "TTS batch output cardinality/sample rate mismatch")
        for u, audio in zip(missing, wavs):
            wav = root / u["outputRelativePath"]
            wav.parent.mkdir(parents=True, exist_ok=True)
            array = audio.detach().float().cpu().numpy() if hasattr(audio, "detach") else np.asarray(audio)
            sf.write(str(wav), array, int(rate), subtype="PCM_16", format="WAV")
            identity = {"groupId": u["translationGroupId"],
                        "textSha256": hashlib.sha256(u["text"].encode()).hexdigest(),
                        "speakerId": u["speakerId"], "checkpointSha256": worker["checkpointSha256"],
                        "workerId": worker["workerId"], "batchSize": len(batch),
                        "batchSeed": batch_seed, "seedPolicy": "base_plus_global_batch_start_v1"}
            audio_hash = sha256(wav)
            write_json(wav.with_suffix(".render.json"), {"identity": identity,
                       "audioSha256": audio_hash, "sampleRate": int(rate),
                       "durationSeconds": float(sf.info(str(wav)).duration),
                       "batchStartUnitIndex": batch[0]["unitIndex"],
                       "batchUnitIndices": [x["unitIndex"] for x in batch],
                       "renderSeconds": time.time() - started})
            rows.append({**identity, "audioPath": str(wav), "audioSha256": audio_hash,
                         "durationSeconds": float(sf.info(str(wav)).duration), "reused": False})
    write_json(Path(result_path), {"workerId": worker["workerId"], "units": rows})


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--job", type=Path, required=True)
    p.add_argument("--route", type=Path, required=True)
    p.add_argument("--source", type=Path, required=True)
    p.add_argument("--candidate", type=Path, required=True)
    p.add_argument("--approval", type=Path)
    p.add_argument("--review-waiver", type=Path,
                   help="Source-bound authorization to synthesize a pending candidate without human content approval")
    p.add_argument("--workers", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--device", default="cuda:0")
    p.add_argument("--dtype", choices=("bfloat16", "float32"), default="bfloat16")
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--preflight-only", action="store_true",
                    help="Validate exact source, candidate, route, and checkpoint bindings without loading models")
    args = p.parse_args()
    load = lambda path: json.loads(path.read_text(encoding="utf-8"))
    require((args.approval is None) != (args.review_waiver is None),
            "Provide exactly one of --approval or --review-waiver")
    job, route, source, candidate = map(load, (args.job, args.route, args.source, args.candidate))
    approval = load(args.approval) if args.approval else None
    review_waiver = load(args.review_waiver) if args.review_waiver else None
    worker_data = load(args.workers)
    workers = worker_data.get("workers", [])
    if job.get("schemaVersion") == "sermon-target-language-speech-job-v4-multilingual-podcast":
        require(worker_data.get("schemaVersion") == "podcast-dual-worker-runtime-plan-v1"
                and worker_data.get("targetLocale") == job.get("targetLocale")
                and worker_data.get("jobJsonSha256") == json_sha(job)
                and review_waiver is not None
                and worker_data.get("reviewWaiverJsonSha256") == json_sha(review_waiver),
                "Runtime worker plan differs from the frozen locale job or review waiver")
    validate(job, route, source, candidate, approval, workers, sha256(args.source), review_waiver)
    if args.preflight_only:
        unit_label = "frozen" if review_waiver is not None else "approved"
        print(f"Preflight passed: {len(job['units'])} {unit_label} units, "
              f"{len(workers)} checkpoint-bound workers, batch size 8")
        return
    args.out.mkdir(parents=True, exist_ok=True)
    identity = {"jobJsonSha256": json_sha(job), "routeJsonSha256": json_sha(route),
                "candidateJsonSha256": json_sha(candidate), "sourceJsonSha256": json_sha(source),
                "workerPlanJsonSha256": json_sha(worker_data), "device": args.device,
                "reviewWaiverJsonSha256": json_sha(review_waiver) if review_waiver else None,
                "dtype": args.dtype, "seed": args.seed, "hostname": socket.gethostname(),
                "ratePolicy": "natural_no_time_stretch", "videoSyncPolicy": "not_applicable_audio_only"}
    identity_path = args.out / "render-identity.json"
    if identity_path.exists():
        require(load(identity_path) == identity, "Output directory is bound to different inputs")
    else:
        write_json(identity_path, identity)
    context = mp.get_context("spawn")
    processes = []
    for worker in workers:
        result = args.out / f"{worker['workerId']}.result.json"
        proc = context.Process(target=_render_worker,
            args=(worker, job["units"], str(args.out), args.seed, args.device,
                  args.dtype, str(result)), name=worker["workerId"])
        proc.start()
        processes.append((proc, result))
    for proc, _ in processes:
        proc.join()
    failures = [(proc.name, proc.exitcode) for proc, _ in processes if proc.exitcode != 0]
    require(not failures, f"One or more TTS workers failed: {failures}")
    rendered = []
    for _, path in processes:
        result = load(path)
        rendered.extend(result["units"])
    rendered.sort(key=lambda row: next(u["unitIndex"] for u in job["units"]
                                      if u["translationGroupId"] == row["groupId"]))
    require(len(rendered) == len(job["units"]) and
            {r["groupId"] for r in rendered} == {u["translationGroupId"] for u in job["units"]},
            "Rendered unit coverage is incomplete or duplicated")
    write_json(args.out / "rendered-units.json", {"schemaVersion": "podcast-dual-worker-rendered-units-v1",
               **identity, "status": "candidate", "workers": [w["workerId"] for w in workers],
               "batchSizePerWorker": 8, "units": rendered})
    print(f"Rendered {len(rendered)} units using {len(workers)} concurrent workers")


if __name__ == "__main__":
    main()
