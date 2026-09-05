#!/usr/bin/env python3
"""Create a derivative pronunciation job; reuse only verified unchanged speech.

Keep the parent render and all receipts intact. Each reused WAV carries its
original generation identity and receipt hash; it is not reported as regenerated.
"""
import argparse
from pathlib import Path
import shutil

from poc import sha256, write_json
from render_weekly_audio import render_identity
from spoken_text import spoken_text, VERSION
from weekly_dubbing import read, validate_frozen


def revise(parent, out):
    job = read(parent / "job.json")
    validate_frozen(job)
    original_render = read(parent / "render/report.json")
    if original_render["jobSha256"] != sha256(parent / "job.json") or original_render["sha256"] != sha256(parent / "render/chinese.raw.wav"):
        raise ValueError("Parent render is stale")
    if out.exists():
        raise ValueError("Preserve previous revisions")
    old_units = job["units"]
    units = [{**u, **({"spokenText": spoken_text(u["text"])} if spoken_text(u["text"]) != u["text"] else {})} for u in old_units]
    job = {**job, "units": units, "pronunciationRuleVersion": VERSION, "revisionOf": {"jobSha256": sha256(parent / "job.json"), "path": str(parent), "reason": "Deterministic numeral and divine-pronoun pronunciation; display text unchanged"}}
    write_json(out / "job.json", job)
    identity = render_identity(out / "job.json", job["voice"]["checkpointSha256"])
    write_json(out / "render/identity.json", identity)
    reused, changed = [], []
    for i, (old, new) in enumerate(zip(old_units, units)):
        if old.get("spokenText", old["text"]) != new.get("spokenText", new["text"]):
            changed.append(i)
            continue
        raw = parent / f"render/unit-{i:04d}.wav"
        receipt_path = raw.with_suffix(".json")
        receipt = read(receipt_path)
        if receipt["sha256"] != sha256(raw) or receipt["unit"] != old or receipt["identity"]["jobSha256"] != sha256(parent / "job.json") or receipt["identity"]["checkpointSha256"] != identity["checkpointSha256"]:
            raise ValueError("Parent unit provenance changed")
        shutil.copyfile(raw, out / "render" / raw.name)
        write_json(out / "render" / receipt_path.name, {**receipt, "unit": new, "identity": identity,
            "reusedFrom": {"wavSha256": receipt["sha256"], "receiptSha256": sha256(receipt_path), "path": str(raw), "generationIdentity": receipt["identity"]}})
        screened = parent / f"audio/unit-screening/unit-{i:04d}.json"
        if screened.exists():
            target = out / f"audio/unit-screening/unit-{i:04d}.json"
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(screened, target)
        reused.append(i)
    alignment = read(parent / "source-alignment/report.json")
    if alignment["jobSha256"] != sha256(parent / "job.json") or alignment["sourceAudioSha256"] != job["inputs"]["sourceAudio"]["sha256"]:
        raise ValueError("Cannot reuse changed English acoustic anchors")
    write_json(out / "source-alignment/report.json", {**alignment, "jobSha256": sha256(out / "job.json"),
        "reusedFrom": {"path": str(parent / "source-alignment/report.json"), "sha256": sha256(parent / "source-alignment/report.json"), "reason": "English, source audio and block IDs unchanged"}})
    write_json(out / "revision-report.json", {"parentJobSha256": sha256(parent / "job.json"), "jobSha256": sha256(out / "job.json"), "reusedUnitIds": reused, "regenerateUnitIds": changed, "displayTextChanged": False, "pronunciationRuleVersion": VERSION})
    print(f"Verified reuse: {len(reused)} units; regenerate: {len(changed)} units")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--parent", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    args = p.parse_args()
    revise(args.parent.resolve(), args.out.resolve())
