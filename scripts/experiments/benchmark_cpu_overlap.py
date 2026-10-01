#!/usr/bin/env python3
"""Prepare/read CPU0/1/2 experiments; run explicitly invokes the real renderer.

No model imports occur during prepare/summarize. Run needs a separately reserved
GPU slot and invokes three fresh processes with identical batch=4 and seeds.
Sample audio remains experiment-only, with independent listening still pending.
"""
from __future__ import annotations
import argparse
import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time
import wave

SCRIPT = Path(__file__).resolve()
# Repository layout during prepare; flat staged layout during remote run.
ROOT = SCRIPT.parents[2] if len(SCRIPT.parents) > 2 else SCRIPT.parent
LEGACY = ROOT / "experiments/sermon-dubbing-poc"
FILES = ("render_weekly_audio.py", "bounded_cpu_pipeline.py", "sentence_synthesis_policy.py", "run_qwen_training_smoke.py")
SCHEMA = "sermon-cpu-overlap-experiment-v2"


def require(ok, message):
    if not ok:
        raise ValueError(message)


def digest(path):
    value = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def canonical(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write("\n")


def prepare(speech_job_path, out, checkpoint_manifest_path, indices=None):
    # Reuse real human/source validators without manufacturing a subset source
    # package or changing its approval identity.
    from scripts import prepare_target_language_speech_job as speech
    original = read(speech_job_path)
    require(original.get("schemaVersion") == speech.SPEECH_JOB_SCHEMA
            and original.get("targetLocale") == "zh-Hans" and original.get("synthesisEligible") is True,
            "Requires an approved Chinese canonical speech job")
    bound = {}
    for name, ref in original["inputs"].items():
        path = Path(ref["path"])
        if name == "speakerRegistry" and not path.is_file():
            path = ROOT / "config/speaker-voice-registry.json"
        value = read(path)
        require(canonical(value) == ref["jsonSha256"]
                and (name == "speakerRegistry" or digest(path) == ref["sha256"]),
                f"Changed canonical upstream input: {name}")
        bound[name] = value
    source, anchor, candidate = (bound[name] for name in
        ("englishSourcePackage", "anchorManifest", "targetLanguageCandidate"))
    speech.validate_target_candidate(source, anchor, candidate)
    speech.validate_policy_binding(candidate, bound["targetLanguagePolicy"])
    speech.validate_human_review_receipt(source, anchor, candidate, bound["humanReviewReceipt"])
    adapter = {**original["adapter"], "targetLocale": "zh-Hans"}
    speech.validate_source_voice_authorization(bound["sourceVoiceAuthorization"], source, candidate, adapter)
    checkpoint_manifest = read(checkpoint_manifest_path)
    config_sha = checkpoint_manifest.get("checkpointConfigSha256", "")
    require(checkpoint_manifest.get("checkpointSha256") == adapter["conditioningSha256"]
            and len(config_sha) == 64 and all(c in "0123456789abcdef" for c in config_sha),
            "Checkpoint manifest must bind formal weights and actual model config SHA")
    if indices is None:
        indices = [i for i, unit in enumerate(original["units"])
                   if len(unit["text"]) >= 12 and unit["text"].endswith(("。", "！", "？"))
                   and sum(unit["text"].count(mark) for mark in "。！？") == 1][:8]
    require(4 <= len(indices) <= 8 and indices == sorted(set(indices))
            and all(type(i) is int and 0 <= i < len(original["units"]) for i in indices),
            "Choose 4..8 intact reviewed Chinese units in source order")
    groups = {group["translationGroupId"]: group for group in candidate["groups"]}
    selected = []
    for index in indices:
        unit = copy.deepcopy(original["units"][index])
        group = groups[unit["translationGroupId"]]
        require(unit["text"] == group["targetText"] and unit["sourceUnitIds"] == group["sourceUnitIds"]
                and sum(unit["text"].count(mark) for mark in "。！？") == 1
                and unit["text"].endswith(("。", "！", "？")), "Selected unit is not one intact approved sentence")
        selected.append(unit)
    job = {"schemaVersion": "sermon-weekly-dubbing-job-v1", "experimentOnly": True,
        "releaseEligible": False, "humanReviewStatus": "new_audio_listening_pending",
        "voice": {"checkpointSha256": adapter["conditioningSha256"], "speakerKey": adapter["speakerKey"]},
        "blocks": [{"id": i, "zh": unit["text"]} for i, unit in enumerate(selected)],
        "units": [{"id": i, "blockId": i, "text": unit["text"], "gapAfterSeconds": .45,
                   "originTranslationGroupId": unit["translationGroupId"], "originSourceUnitIds": unit["sourceUnitIds"],
                   "originUnitIndex": origin} for i, (origin, unit) in enumerate(zip(indices, selected))],
        "originCanonicalSpeechJobJsonSha256": canonical(original)}
    # These are existing natural sentences; no upstream grouping or source
    # identity is altered. Legacy renderer's flow mode consumes them intact.
    manifest = {"schemaVersion": SCHEMA, "experimentOnly": True, "dispatchEnabled": False,
        "job": "job.json", "jobSha256": None, "batchSize": 4, "seed": 42,
        "seedPolicy": "42 plus fixed batch start index", "selectedOriginUnitIndices": indices,
        "originSpeechJob": {"path": str(Path(speech_job_path).resolve()), "sha256": digest(speech_job_path),
                            "jsonSha256": canonical(original)},
        "upstreamInputs": original["inputs"], "adapter": original["adapter"],
        "voice": job["voice"], "producerFiles": {name: digest(LEGACY / name) for name in FILES},
        "checkpointConfigSha256": config_sha,
        "checkpointManifest": {"path": str(checkpoint_manifest_path.resolve()),
                               "sha256": digest(checkpoint_manifest_path)},
        "acceptance": "experiment_only_no_release_no_listening_approval",
        "timingBoundary": "fresh subprocess launch through completed renderer exit; includes import/hash/load/save/assembly",
        "comparison": "Report PCM/cue equality; separate processes and backend precision can differ. No equality assumption."}
    require(not out.exists(), "Frozen sample requires a new directory")
    out.mkdir(parents=True)
    save(out / "job.json", job)
    manifest["jobSha256"] = digest(out / "job.json")
    save(out / "manifest.json", manifest)
    return manifest


def checked_manifest(path, renderer):
    manifest = read(path)
    require(manifest.get("schemaVersion") == SCHEMA and manifest.get("experimentOnly") is True,
            "Unsupported CPU experiment")
    job_path = path.parent / manifest["job"]
    require(digest(job_path) == manifest["jobSha256"] and read(job_path)["voice"] == manifest["voice"],
            "Frozen sample changed")
    require(all(digest(renderer.parent / name) == expected for name, expected in manifest["producerFiles"].items()),
            "Producer/helper bytes changed since sample freeze")
    return manifest, job_path


def pcm(path):
    hashed = hashlib.sha256()
    with wave.open(str(path), "rb") as audio:
        require(audio.getnchannels() == 1 and audio.getframerate() == 24000
                and audio.getsampwidth() == 3 and audio.getcomptype() == "NONE", "Unexpected PCM format")
        frames = audio.getnframes()
        count = 0
        while data := audio.readframes(24000):
            count += len(data)
            hashed.update(data)
    require(frames > 0 and count == frames * 3, "Truncated or empty PCM")
    return {"wavSha256": digest(path), "pcmSha256": hashed.hexdigest(), "frames": frames,
            "audioSeconds": frames / 24000, "decode": "pass"}


def summarize(out):
    rows = [read(path) for path in sorted(out.glob("cpu-*/measurement.json"))]
    require(len(rows) == 3 and sorted(row["cpuWorkers"] for row in rows) == [0, 1, 2]
            and all(row["exitCode"] == 0 for row in rows), "CPU matrix is incomplete or failed")
    require(len({row["jobSha256"] for row in rows}) == 1
            and len({canonical(row["renderIdentity"]) for row in rows}) == 1,
            "Matrix input/device/generation identities differ")
    return {"schemaVersion": SCHEMA, "experimentOnly": True, "runs": rows,
            "sameTrackPcm": len({row["track"]["pcmSha256"] for row in rows}) == 1,
            "sameUnitPcm": len({canonical(row["units"]) for row in rows}) == 1,
            "sameCues": len({row["cuesSha256"] for row in rows}) == 1,
            "humanListening": "not_run", "qualityAcceptance": "not_evaluated",
            "notes": ["Fresh renderer processes each load the model; filesystem/driver caches may be warm.",
                      "CPU time overlaps synthesis; do not add stage sums to infer elapsed wall time.",
                      "Bit equality is measured, not promised across isolated runtime sampling or MPS/CUDA."]}


def run(manifest_path, checkpoint, renderer, python, device, out, order=(0, 1, 2), timeout=1800):
    manifest, job_path = checked_manifest(manifest_path, renderer)
    require(tuple(sorted(order)) == (0, 1, 2), "CPU order must contain 0,1,2 exactly once")
    require(digest(checkpoint / "model.safetensors") == manifest["voice"]["checkpointSha256"], "Wrong formal checkpoint")
    require(digest(checkpoint / "config.json") == manifest["checkpointConfigSha256"], "Checkpoint config identity changed")
    require(not out.exists(), "Run matrix requires a new directory; preserve prior results")
    out.mkdir(parents=True)
    for workers in order:
        arm = out / f"cpu-{workers}"
        arm.mkdir()
        output = arm / "render"
        argv = [str(python), str(renderer), "--job", str(job_path.resolve()), "--checkpoint", str(checkpoint.resolve()),
                "--device", device, "--batch-size", "4", "--cpu-workers", str(workers),
                "--cpu-queue-batches", "2", "--out", str(output.resolve())]
        started = time.perf_counter()
        with (arm / "renderer.log").open("xb") as log:
            try:
                process = subprocess.run(argv, stdout=log, stderr=subprocess.STDOUT, timeout=timeout, check=False)
                code = process.returncode
            except subprocess.TimeoutExpired:
                code = 124
        wall = time.perf_counter() - started
        row = {"cpuWorkers": workers, "device": device, "batchSize": 4, "jobSha256": manifest["jobSha256"],
               "checkpointSha256": manifest["voice"]["checkpointSha256"], "exitCode": code,
               "wallSeconds": wall, "executionArgv": argv}
        if code == 0:
            report = read(output / "report.json")
            row.update(synthesisSeconds=report["synthesisSeconds"], rendererGenerationSeconds=report["generationSeconds"],
                cpuPipeline=report["cpuPipeline"], renderIdentity=read(output / "identity.json"),
                track=pcm(output / "chinese.raw.wav"), cuesSha256=canonical(report["cues"]),
                units=[pcm(output / f"unit-{i:04d}.wav") for i in range(len(read(job_path)["units"]))])
        save(arm / "measurement.json", row)
        require(code == 0, f"CPU{workers} renderer failed ({code}); inspect {arm / 'renderer.log'}")
    result = summarize(out)
    save(out / "comparison.json", result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    prep = commands.add_parser("prepare")
    prep.add_argument("--speech-job", required=True, type=Path)
    prep.add_argument("--out-dir", required=True, type=Path)
    prep.add_argument("--checkpoint-manifest", required=True, type=Path,
                      help="Frozen manifest with checkpointSha256 and checkpointConfigSha256")
    prep.add_argument("--indices", help="4..8 original unit indices, comma separated; default first 8 complete sentences")
    execute = commands.add_parser("run", help="Explicit GPU execution; reserve the host before using")
    execute.add_argument("--manifest", required=True, type=Path)
    execute.add_argument("--checkpoint", required=True, type=Path)
    execute.add_argument("--renderer", type=Path, default=LEGACY / "render_weekly_audio.py")
    execute.add_argument("--python", type=Path, default=Path(sys.executable))
    execute.add_argument("--device", required=True, choices=("mps", "cuda:0"))
    execute.add_argument("--out-dir", required=True, type=Path)
    execute.add_argument("--order", default="0,1,2")
    execute.add_argument("--timeout", type=int, default=1800)
    inspect = commands.add_parser("summarize")
    inspect.add_argument("--out-dir", required=True, type=Path)
    args = parser.parse_args()
    if args.command == "prepare":
        result = prepare(args.speech_job, args.out_dir, args.checkpoint_manifest,
                         [int(i) for i in args.indices.split(",")] if args.indices else None)
    elif args.command == "run":
        result = run(args.manifest, args.checkpoint, args.renderer, args.python, args.device, args.out_dir,
                     tuple(int(i) for i in args.order.split(",")), args.timeout)
    else:
        result = summarize(args.out_dir)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
