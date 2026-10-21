#!/usr/bin/env python3
"""Back-transcribe John Thomas auditions with Qwen3-ASR-0.6B (Spark speech runtime) as a content screen.

Character error rate for zh-Hans/ko, word error rate for es/en, after removing punctuation and case.
A screen only: it cannot prove pronunciation, naturalness or speaker similarity.
"""
import argparse
import hashlib
import json
import re
import unicodedata
from pathlib import Path

ASR = ("Qwen/Qwen3-ASR-0.6B", "5eb144179a02acc5e5ba31e748d22b0cf3e303b0")


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def strip(text):
    return "".join(c for c in unicodedata.normalize("NFKC", text).lower() if not unicodedata.category(c).startswith(("P", "S", "Z")) or c == " ")


def edit_distance(a, b):
    prev = list(range(len(b) + 1))
    for i, x in enumerate(a, 1):
        cur = [i]
        for j, y in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (x != y)))
        prev = cur
    return prev[-1]


def units(text, char_level):
    text = strip(text)
    return [c for c in text if c != " "] if char_level else text.split()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--work", type=Path, required=True)
    work = parser.parse_args().work.resolve()
    probe = json.loads((work / "probe/report.json").read_text())
    import soundfile as sf
    import torch
    from huggingface_hub import snapshot_download
    from qwen_asr import Qwen3ASRModel
    model = Qwen3ASRModel.from_pretrained(snapshot_download(repo_id=ASR[0], revision=ASR[1], local_files_only=True), max_new_tokens=1024,
                                          max_inference_batch_size=1, dtype=torch.bfloat16, device_map="cuda:0")
    rows = []
    for t in probe["tracks"]:
        path = work / "probe" / t["file"]
        if sha256(path) != t["audioSha256"]:
            raise ValueError("Audition audio changed")
        wave, rate = sf.read(path, dtype="float32")
        heard = model.transcribe(audio=(wave, rate), language=t["modelLanguage"])[0].text
        char_level = t["modelLanguage"] in ("Chinese", "Korean")
        ref, hyp = units(t["text"], char_level), units(heard, char_level)
        rows.append({"targetLocale": t["targetLocale"], "file": t["file"], "audioSha256": t["audioSha256"], "asrText": heard,
                     "metric": "cer" if char_level else "wer", "errorRate": round(edit_distance(ref, hyp) / max(1, len(ref)), 4),
                     "referenceUnits": len(ref), "hypothesisUnits": len(hyp)})
        print(json.dumps(rows[-1], ensure_ascii=False), flush=True)
    (work / "probe/asr-screening.json").write_text(json.dumps({"asr": list(ASR), "probeReportSha256": sha256(work / "probe/report.json"),
        "status": "machine_screened", "humanListeningStatus": "pending", "rows": rows}, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    main()
