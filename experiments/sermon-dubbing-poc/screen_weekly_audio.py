#!/usr/bin/env python3
"""Screen every rendered unit, avoiding long-audio transcription truncation."""
import argparse
import difflib
from pathlib import Path
import subprocess
import json

from poc import sha256, write_json
from speech_backend import same_identity, SpeechModel, ASR, add_batch_argument, bounded_batches, require_resolved_dispatches
from screen_audio import normalize
from weekly_dubbing import read, validate_frozen


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--work", type=Path, required=True)
    add_batch_argument(p)
    args = p.parse_args()
    work = args.work.resolve()
    job, render = read(work / "job.json"), read(work / "render/report.json")
    validate_frozen(job)
    dispatch_dir = work / 'audio/unit-screening/speech-dispatch'
    require_resolved_dispatches(dispatch_dir)
    if render["jobSha256"] != sha256(work / "job.json"):
        raise ValueError("Audio belongs to another weekly job")
    mp3 = work / "audio/zh-natural.mp3"
    track = read(work / "audio/library.json")["tracks"][0]
    if sha256(mp3) != track["sha256"]:
        raise ValueError("MP3 changed")
    subprocess.run(["ffmpeg", "-v", "error", "-i", str(mp3), "-f", "null", "-"], check=True)
    job_sha = sha256(work / 'job.json')
    checks, issues, pending = [None] * len(job['units']), [], []
    out = work / "audio/unit-screening"
    out.mkdir(exist_ok=True)
    # Inspect every current unit and cached result before constructing a model.
    for i, unit in enumerate(job['units']):
        raw = work / f'render/unit-{i:04d}.wav'
        saved = read(raw.with_suffix('.json'))
        if saved['unit'] != unit or saved['sha256'] != sha256(raw) or saved['identity']['jobSha256'] != job_sha:
            raise ValueError('Changed or unbound audio unit')
        expected_text = unit.get('spokenText', unit['text'])
        identity = {'audioSha256': sha256(raw), 'expected': expected_text, 'model': ASR[0], 'revision': ASR[1]}
        receipt = out / f'unit-{i:04d}.json'
        if receipt.exists():
            check = read(receipt)
            if (not same_identity(check['identity'], identity) or check.get('unitId') != i
                    or check.get('blockId') != unit['blockId']):
                raise ValueError('Stale ASR screening')
            matcher = difflib.SequenceMatcher(None, normalize(expected_text), normalize(check['recognized']), autojunk=False)
            expected, actual = normalize(expected_text), normalize(check['recognized'])
            differences = [{'kind': op, 'expected': expected[a:b], 'recognized': actual[c:d]}
                           for op, a, b, c, d in matcher.get_opcodes() if op != 'equal']
            if check['differences'] != differences or abs(check['similarity'] - matcher.ratio()) > 1e-9:
                raise ValueError('Cached ASR screening evidence changed')
            checks[i] = check
        else:
            pending.append({'unitId': i, 'path': raw, 'language': 'Chinese', 'max_tokens': 1024, 'locale': 'zh-Hans'})

    def save(unit_id, result, inference):
        if sha256(work / 'job.json') != job_sha:
            raise ValueError('Frozen screening job changed')
        unit = job['units'][unit_id]
        raw = work / f'render/unit-{unit_id:04d}.wav'
        expected_text = unit.get('spokenText', unit['text'])
        identity = {'audioSha256': sha256(raw), 'expected': expected_text,
                    'model': inference['model'], 'revision': inference['revision']}
        expected, actual = normalize(expected_text), normalize(result.text)
        matcher = difflib.SequenceMatcher(None, expected, actual, autojunk=False)
        differences = [{'kind': op, 'expected': expected[a:b], 'recognized': actual[c:d]}
                       for op, a, b, c, d in matcher.get_opcodes() if op != 'equal']
        check = {'unitId': unit_id, 'blockId': unit['blockId'], 'identity': identity,
                 'recognized': result.text, 'similarity': matcher.ratio(), 'differences': differences,
                 'inferenceReceipt': inference}
        receipt = out / f'unit-{unit_id:04d}.json'
        if receipt.exists():
            raise ValueError('ASR screening receipt appeared during inference; preserve it')
        write_json(receipt, check)
        checks[unit_id] = check

    if pending:
        model = SpeechModel(ASR)
        for batch in bounded_batches(pending, args.speech_batch_size):
            model.generate_batch(batch, on_result=save, dispatch_dir=dispatch_dir, job_sha256=job_sha)
    if sha256(work / 'job.json') != job_sha or any(check is None for check in checks):
        raise ValueError('Incomplete or changed screening coverage')
    for i, check in enumerate(checks):
        issues.extend({'unitId': i, 'blockId': job['units'][i]['blockId'],
                       'audioStart': render['cues'][i]['start'], **difference} for difference in check['differences'])
        print(f"Screened {i + 1}/{len(job['units'])}; differences {len(check['differences'])}", flush=True)
    models = []
    for check in checks:
        used = [check["identity"]["model"], check["identity"]["revision"]]
        if used not in models:
            models.append(used)
    measure = subprocess.run(["ffmpeg", "-hide_banner", "-i", str(mp3), "-af", "loudnorm=I=-18:TP=-1.5:LRA=11:print_format=json", "-f", "null", "-"], capture_output=True, text=True, check=True)
    loud, _ = json.JSONDecoder().raw_decode(measure.stderr[measure.stderr.rfind("{"):])
    write_json(work / "audio/asr-screening.json", {"status": "machine_screening_only", "model": models[0][0], "revision": models[0][1], "modelIdentities": models, "modelIdentityScope": "representative_first_result_with_complete_model_list", "jobSha256": sha256(work / "job.json"), "humanListeningStatus": "pending",
        "warning": "ASR differences can be homophones or recognition errors; matching text is not listening acceptance.",
        "results": [{"id": track["id"], "sha256": sha256(mp3), "fullDecode": "pass", "durationSeconds": render["durationSeconds"], "screenedUnits": len(checks), "expectedUnits": len(job["units"]),
            "reviewCandidates": issues, "integratedLufs": float(loud["input_i"]), "truePeakDbtp": float(loud["input_tp"])}]})
    print(json.dumps({"screenedUnits": len(checks), "differences": len(issues)}), flush=True)


if __name__ == "__main__":
    main()
