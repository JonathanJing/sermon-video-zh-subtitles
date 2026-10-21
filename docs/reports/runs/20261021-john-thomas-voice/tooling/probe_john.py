#!/usr/bin/env python3
"""Generate John Thomas auditions from the trained checkpoint (zh-Hans, ko, es + one held-out English line).

Fixed text: experiments/sermon-dubbing-poc/multilingual-voice-demo-script-v1.json (staged copy, hash-bound).
Settings match the 2026-09-21 multilingual demos: seed 42, temperature 0.7, repetition penalty 1.05,
max 768 new tokens, whole text per locale, natural rate. Waveforms only; screening runs separately.
"""
import argparse
import hashlib
import json
from pathlib import Path
import time

SCRIPT_SHA = "cbd03468c2f5ce120e1f9b297ab3429d7bf7b8e0d44be1ae90717d72bdcb4c38"  # file bytes; 2026-09-21 manifest recorded a canonical-JSON hash
LOCALES = ["zh-Hans", "ko", "es"]


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--work", type=Path, required=True)
    args = parser.parse_args()
    work = args.work.resolve()
    training = json.loads((work / "training-report.json").read_text())
    checkpoint = work / "checkpoints/checkpoint-epoch-0"
    if sha256(checkpoint / "model.safetensors") != training["checkpointSha256"]:
        raise ValueError("Checkpoint changed")
    script_path = work / "probe-input/multilingual-voice-demo-script-v1.json"
    if sha256(script_path) != SCRIPT_SHA:
        raise ValueError("Demo script changed")
    script = json.loads(script_path.read_text())
    validation = [json.loads(l) for l in (work / "prep/validation.jsonl").read_text().splitlines() if l.strip()]
    held = validation[-1]  # final held-out clip; never used in training
    out = work / "probe"
    if (out / "report.json").exists():
        raise ValueError("Preserve the completed probe")
    out.mkdir(exist_ok=True)
    import numpy as np
    import soundfile as sf
    import torch
    from qwen_tts import Qwen3TTSModel
    model = Qwen3TTSModel.from_pretrained(str(checkpoint), device_map="cuda:0", dtype=torch.bfloat16, attn_implementation="sdpa")
    jobs = [(l["targetLocale"], l["modelLanguage"], l["text"]) for l in script["locales"] if l["targetLocale"] in LOCALES]
    jobs.append(("en-heldout", "English", held["text"]))
    tracks = []
    for locale, language, text in jobs:
        torch.manual_seed(42)
        started = time.monotonic()
        wavs, rate = model.generate_custom_voice(text=text, language=language, speaker=training["speakerKey"], temperature=0.7, repetition_penalty=1.05, max_new_tokens=768)
        wave = np.asarray(wavs[0], dtype=np.float32).reshape(-1)
        path = out / f"{locale}.wav"
        sf.write(path, wave, rate, subtype="PCM_24")
        seconds = len(wave) / rate
        status = "pass" if np.isfinite(wave).all() and 0.5 < seconds < 60 else "suspicious_duration_or_signal"
        tracks.append({"targetLocale": locale, "modelLanguage": language, "text": text, "textSha256": hashlib.sha256(text.encode()).hexdigest(), "file": path.name,
                       "audioSha256": sha256(path), "sampleRate": rate, "durationSeconds": round(seconds, 3), "generationSeconds": round(time.monotonic() - started, 3),
                       "peak": float(np.max(np.abs(wave))), "signalCheck": status,
                       **({"heldOutSource": {"file": held["file"], "sha256": held["sha256"], "sourceStartSeconds": held["sourceStartSeconds"]}} if locale == "en-heldout" else {})})
        print(json.dumps(tracks[-1], ensure_ascii=False), flush=True)
    (out / "report.json").write_text(json.dumps({"status": "generated_waveforms", "scope": "voice_capability_audition_not_sermon_translation", "speakerKey": training["speakerKey"],
        "checkpointSha256": training["checkpointSha256"], "scriptJsonSha256": SCRIPT_SHA, "seed": 42, "temperature": 0.7, "repetitionPenalty": 1.05, "maxNewTokens": 768,
        "ratePolicy": "natural_no_time_stretch", "humanListeningStatus": "pending", "tracks": tracks}, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    main()
