"""Blind A/B: does a unit rendered alone sound like the same unit rendered in a batch? (DEV-GRP-005)

Decision 1 of docs/design/per-group-independent-pipeline.zh.md takes batch membership out
of the sound identity only after a real A/B passes: at least ten groups per locale,
each rendered by the formal batch renderer and again alone by the per-group preview
renderer, compared blind. Any audible difference in timbre, rate or volume keeps batch
membership in the key. The result binds the synthesis identity it tested and stops
applying as soon as that identity changes.

This module renders nothing and calls no model. ``select`` picks the groups from a
formal speech job and prints the preview render to run on Spark; ``pack`` pairs the
preview WAVs with the formal ones in a blind packet; ``record`` turns a listener's
verdicts into the result receipt; ``applies`` is the check DEV-GRP-005 makes before
leaving batch membership out of a key.
"""
from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
import math
from pathlib import Path
import secrets
import shutil
import struct
import sys
from typing import Any
import wave

SELECTION_SCHEMA = "sermon-batch-identity-ab-selection-v1"
PACKET_SCHEMA = "sermon-batch-identity-ab-packet-v1"
KEY_SCHEMA = "sermon-batch-identity-ab-key-v1"
RESULT_SCHEMA = "sermon-batch-identity-ab-result-v1"
MINIMUM_GROUPS_PER_LOCALE = 10
PREVIEW_UNIT_SCHEMA = "sermon-speculative-target-speech-unit-v2"
INTENT_SCHEMA = "sermon-formal-target-speech-render-v2"
# The formal renderer's sound and batch behaviour under test. A change to any of these
# means a different synthesis stack, which needs its own A/B (decision 1).
TESTED_FIELDS = ("schemaVersion", "adapterId", "adapterFileSha256", "model", "modelRevision", "conditioningRef",
                 "checkpointSha256", "speakerId", "speakerKey", "targetLocale", "languageParameter",
                 "operationPoliciesFileSha256", "rendererSha256", "seed", "temperature", "repetitionPenalty",
                 "maxNewTokens", "dtype", "attention", "deliveryInstruction", "ratePolicy", "batchSize",
                 "batchSeedPolicy", "batchImplementationSha256", "batchCachedUnitPolicy", "replicaPolicy",
                 "replicaImplementationSha256")
VERDICTS = ("no_audible_difference", "audible_difference")
# Voice fields the preview arm must share with the formal arm.
SAME_VOICE_FIELDS = ("targetLocale", "adapterId", "model", "modelRevision", "conditioningRef", "checkpointSha256",
                     "speakerId", "speakerKey", "languageParameter", "operationPoliciesFileSha256")
# Everything but batching: the alone arm must also use the formal arm's seed and decoding.
PREVIEW_MATCH_FIELDS = SAME_VOICE_FIELDS + ("seed", "temperature", "repetitionPenalty", "maxNewTokens", "dtype",
                                            "attention", "deliveryInstruction", "ratePolicy")


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def json_sha256(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                                     allow_nan=False).encode("utf-8")).hexdigest()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _load(path: Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _write_new(path: Path, value: Any) -> None:
    """Write a JSON file that must not exist yet; nothing here is ever replaced."""
    path = Path(path)
    _require(not path.exists(), f"output_exists:{path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=1)
        stream.write("\n")


def tested_identity(intent: dict) -> dict:
    """The fields of one formal render intent that the A/B result is bound to."""
    _require(intent.get("schemaVersion") == INTENT_SCHEMA, "unsupported_render_intent")
    return {field: intent.get(field) for field in TESTED_FIELDS}


def pcm_metrics(path: Path) -> dict:
    """Duration, RMS and peak of a mono PCM16 WAV, for the listener's reference only."""
    with wave.open(str(path), "rb") as audio:
        _require(audio.getsampwidth() == 2 and audio.getnchannels() == 1, f"unsupported_wav:{path.name}")
        rate, frames = audio.getframerate(), audio.readframes(audio.getnframes())
    samples = struct.unpack("<" + "h" * (len(frames) // 2), frames)
    _require(bool(samples), f"empty_wav:{path.name}")
    rms = math.sqrt(sum(sample * sample for sample in samples) / len(samples)) / 32768
    peak = max(abs(sample) for sample in samples) / 32768
    return {"durationSeconds": round(len(samples) / rate, 3),
            "rmsDbfs": round(20 * math.log10(rms), 2) if rms > 0 else None,
            "peakDbfs": round(20 * math.log10(peak), 2) if peak > 0 else None}


# --- select ---------------------------------------------------------------------------

def _batch_commit_binds(commit: dict, intent: dict, audio_sha256: str) -> bool:
    """Whether the formal renderer's commit says this very intent generated these bytes in a batch.

    A WAV whose hash is not the committed one (for example after silence compaction) is not
    the batch arm, and neither is a unit the commit does not place in its intent's window.
    """
    from . import renderer  # the formal renderer's own rule for a committed batch window
    return (commit.get("identity") == intent and commit.get("audioSha256") == audio_sha256
            and intent.get("batchSize", 1) > 1 and renderer._generation_batch_matches(commit, intent))


def select(speech_job: Path, count: int = MINIMUM_GROUPS_PER_LOCALE, *, exclude: set[str] = frozenset()) -> dict:
    """Pick ``count`` groups spread over the job's unit durations, deterministically.

    Units are ordered by duration and taken at evenly spaced ranks, so short, middle and
    long sentences are all heard. Every chosen unit must come from the same tested
    identity; a job mixing synthesis stacks cannot be one A/B.
    """
    _require(count >= MINIMUM_GROUPS_PER_LOCALE, f"at_least_{MINIMUM_GROUPS_PER_LOCALE}_groups_per_locale")
    speech_job = Path(speech_job)
    job_path = speech_job / "job.json"
    _require(job_path.is_file(), "speech_job_without_job_json")
    units = []
    for intent_path in sorted((speech_job / "receipts").glob("unit-[0-9][0-9][0-9][0-9].intent.json")):
        stem = intent_path.name.removesuffix(".intent.json")
        receipt_path = speech_job / "receipts" / f"{stem}.json"
        if not receipt_path.is_file():
            continue
        commit_path = speech_job / "receipts" / f"{stem}.render.json"
        if not commit_path.is_file():
            continue
        intent, receipt, commit = _load(intent_path), _load(receipt_path), _load(commit_path)
        wav = speech_job / receipt["audioRelativePath"]
        if (intent.get("groupId") in exclude or receipt.get("fullDecode") != "pass"
                or receipt.get("translationGroupId") != intent.get("groupId")
                or not wav.is_file() or file_sha256(wav) != receipt.get("audioSha256")
                or not _batch_commit_binds(commit, intent, receipt["audioSha256"])):
            continue
        units.append({"unitIndex": intent["unitIndex"], "translationGroupId": intent["groupId"],
                      "sourceUnitIds": intent["sourceUnitIds"], "textSha256": intent["textSha256"],
                      "durationSeconds": receipt["durationSeconds"], "audioRelativePath": receipt["audioRelativePath"],
                      "audioSha256": receipt["audioSha256"], "batchWindowStart": intent.get("batchWindowStart"),
                      "tested": tested_identity(intent)})
    _require(len(units) >= count, f"speech_job_has_only_{len(units)}_usable_units")
    identities = {json_sha256(unit["tested"]) for unit in units}
    _require(len(identities) == 1, "speech_job_mixes_synthesis_identities")
    ranked = sorted(units, key=lambda unit: (unit["durationSeconds"], unit["unitIndex"]))
    picks = sorted({round(position * (len(ranked) - 1) / (count - 1)) for position in range(count)})
    chosen = sorted((ranked[rank] for rank in picks), key=lambda unit: unit["unitIndex"])
    tested = units[0]["tested"]
    return {"schemaVersion": SELECTION_SCHEMA, "targetLocale": tested["targetLocale"],
            "speechJob": str(speech_job), "speechJobFileSha256": file_sha256(job_path),
            "testedIdentity": tested, "testedIdentitySha256": json_sha256(tested),
            "groups": [{key: value for key, value in unit.items() if key != "tested"} for unit in chosen],
            "previewRender": {"renderer": "render_speculative_target_language_speech.py",
                              "groupIds": [unit["translationGroupId"] for unit in chosen],
                              # pack refuses a preview rendered with anything else.
                              "settings": {"seed": tested["seed"], "dtype": tested["dtype"],
                                           "attention": tested["attention"], "instruct": tested["deliveryInstruction"]},
                              "note": "Run on Spark inside a begun exclusive session; it renders each group alone "
                                      "(preview_only) with the candidate, adapter and policies of this job."},
            "humanApproval": False}


# --- pack -----------------------------------------------------------------------------

def _preview_units(preview: Path) -> dict[str, dict]:
    """Preview receipts by group ID; only committed, preview_only, decoded units count."""
    found = {}
    for receipt_path in sorted((Path(preview) / "receipts").glob("unit-[0-9][0-9][0-9][0-9].json")):
        receipt = _load(receipt_path)
        wav = Path(preview) / "units" / receipt_path.name.replace(".json", ".wav")
        if (receipt.get("schemaVersion") != PREVIEW_UNIT_SCHEMA or receipt.get("status") != "preview_only"
                or receipt.get("fullDecode") != "pass" or not wav.is_file()
                or file_sha256(wav) != receipt.get("audioSha256")):
            continue
        sound = receipt.get("soundIdentity") or {}
        found[sound.get("groupId") or receipt.get("translationGroupId")] = {"receipt": receipt, "wav": wav}
    return found


def pack(selection: dict, preview: Path, out: Path, *, rng=secrets.SystemRandom()) -> dict:
    """Pair each selected formal WAV with its preview WAV under random X/Y labels."""
    _require(selection.get("schemaVersion") == SELECTION_SCHEMA, "invalid_ab_selection")
    out = Path(out)
    _require(not out.exists(), f"output_exists:{out}")
    speech_job = Path(selection["speechJob"])
    _require(file_sha256(speech_job / "job.json") == selection["speechJobFileSha256"], "speech_job_changed_since_selection")
    previews = _preview_units(preview)
    missing = [group["translationGroupId"] for group in selection["groups"] if group["translationGroupId"] not in previews]
    _require(not missing, f"preview_missing_groups:{missing[:3]}")
    pairs, key = [], []
    (out / "pairs").mkdir(parents=True)
    for number, group in enumerate(selection["groups"], 1):
        formal = speech_job / group["audioRelativePath"]
        _require(file_sha256(formal) == group["audioSha256"], f"formal_audio_changed:{group['translationGroupId']}")
        alone = previews[group["translationGroupId"]]
        sound = alone["receipt"].get("soundIdentity") or {}
        # The alone arm must say the same text with the same voice, seed and decoding; only the batch differs.
        _require(sound.get("textSha256") == group["textSha256"]
                 and all(sound.get(field) == selection["testedIdentity"].get(field) for field in PREVIEW_MATCH_FIELDS),
                 f"preview_differs_beyond_batching:{group['translationGroupId']}")
        arms = [("batch", formal), ("alone", alone["wav"])]
        rng.shuffle(arms)
        labels = {}
        for label, (arm, source) in zip(("X", "Y"), arms):
            target = out / "pairs" / f"pair-{number:02d}-{label}.wav"
            shutil.copyfile(source, target)
            labels[label] = {"arm": arm, "audioSha256": file_sha256(target), "metrics": pcm_metrics(target)}
        pairs.append({"pair": number, "files": {label: f"pairs/pair-{number:02d}-{label}.wav" for label in labels},
                      "metrics": {label: value["metrics"] for label, value in labels.items()}})
        key.append({"pair": number, "translationGroupId": group["translationGroupId"],
                    "arms": {label: value["arm"] for label, value in labels.items()},
                    "audioSha256": {label: value["audioSha256"] for label, value in labels.items()},
                    "previewSoundIdentitySha256": json_sha256(sound)})
    key_doc = {"schemaVersion": KEY_SCHEMA, "selectionSha256": json_sha256(selection), "pairs": key}
    _write_new(out / "key.json", key_doc)  # kept apart from the listener; bound below by hash
    packet = {"schemaVersion": PACKET_SCHEMA, "targetLocale": selection["targetLocale"],
              "selectionSha256": json_sha256(selection), "testedIdentitySha256": selection["testedIdentitySha256"],
              "keySha256": file_sha256(out / "key.json"), "pairs": pairs,
              "instructions": ("Listen to X and Y of every pair. Mark audible_difference if timbre, speaking rate or "
                               "volume differs in a way that would be noticed when the two sat in one track; "
                               "otherwise no_audible_difference. Do not open key.json before recording."),
              "verdictTemplate": [{"pair": pair["pair"], "verdict": None, "note": ""} for pair in pairs]}
    _write_new(out / "packet.json", packet)
    return packet


# --- record and apply -----------------------------------------------------------------

def record(packet_dir: Path, verdicts: list[dict], listener: str, listened_at: str) -> dict:
    """The A/B result: passes only if every pair was judged and none differs audibly."""
    packet_dir = Path(packet_dir)
    packet, key_path = _load(packet_dir / "packet.json"), packet_dir / "key.json"
    _require(packet.get("schemaVersion") == PACKET_SCHEMA and file_sha256(key_path) == packet["keySha256"],
             "packet_or_key_changed")
    _require(isinstance(listener, str) and listener.strip(), "listener_required")
    try:
        heard_at = datetime.fromisoformat(str(listened_at).replace("Z", "+00:00"))
    except ValueError:
        heard_at = None
    _require(heard_at is not None and heard_at.tzinfo is not None, "listened_at_needs_iso_time_with_timezone")
    pairs = [row.get("pair") for row in verdicts]
    _require(len(pairs) == len(set(pairs)), "duplicate_pair_verdicts")
    by_pair = {row.get("pair"): row for row in verdicts}
    _require(sorted(by_pair) == [pair["pair"] for pair in packet["pairs"]]
             and all(row.get("verdict") in VERDICTS for row in verdicts), "every_pair_needs_one_verdict")
    for pair in packet["pairs"]:  # the files heard are the files packed
        for label, relative in pair["files"].items():
            _require(file_sha256(packet_dir / relative) == next(
                row for row in _load(key_path)["pairs"] if row["pair"] == pair["pair"])["audioSha256"][label],
                f"packet_audio_changed:pair-{pair['pair']}")
    different = [pair for pair, row in sorted(by_pair.items()) if row["verdict"] == "audible_difference"]
    return {"schemaVersion": RESULT_SCHEMA, "decision": "batch_membership_out_of_sound_identity",
            "targetLocale": packet["targetLocale"], "testedIdentitySha256": packet["testedIdentitySha256"],
            "selectionSha256": packet["selectionSha256"], "packetSha256": file_sha256(packet_dir / "packet.json"),
            "keySha256": packet["keySha256"], "pairCount": len(packet["pairs"]),
            "audibleDifferencePairs": different, "verdicts": [by_pair[pair] for pair in sorted(by_pair)],
            "result": "pass" if not different else "fail",
            # A person listened; this is a listening judgment, not a release or content approval.
            "humanListening": {"listener": listener, "listenedAt": heard_at.isoformat()},
            "releaseEligible": False}


def applies(result: dict, current_identity: dict) -> bool:
    """Whether batch membership may stay out of the key for audio from ``current_identity``."""
    return (isinstance(result, dict) and result.get("schemaVersion") == RESULT_SCHEMA
            and result.get("result") == "pass" and result.get("pairCount", 0) >= MINIMUM_GROUPS_PER_LOCALE
            and result.get("testedIdentitySha256") == json_sha256({field: current_identity.get(field)
                                                                    for field in TESTED_FIELDS}))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    choose = sub.add_parser("select", help="pick groups from a formal speech job; renders nothing")
    choose.add_argument("--speech-job", type=Path, required=True)
    choose.add_argument("--count", type=int, default=MINIMUM_GROUPS_PER_LOCALE)
    choose.add_argument("--out", type=Path, required=True)
    packer = sub.add_parser("pack", help="build the blind packet from the preview renders")
    packer.add_argument("--selection", type=Path, required=True)
    packer.add_argument("--preview", type=Path, required=True)
    packer.add_argument("--out", type=Path, required=True)
    recorder = sub.add_parser("record", help="write the result from the listener's verdicts")
    recorder.add_argument("--packet", type=Path, required=True)
    recorder.add_argument("--verdicts", type=Path, required=True)
    recorder.add_argument("--listener", required=True)
    recorder.add_argument("--listened-at", required=True)
    recorder.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.command == "select":
        value = select(args.speech_job, args.count)
        _write_new(args.out, value)
        print(f"{value['targetLocale']}: {len(value['groups'])} groups, tested identity "
              f"{value['testedIdentitySha256'][:12]}; preview --group-id {' '.join(value['previewRender']['groupIds'])}")
    elif args.command == "pack":
        packet = pack(_load(args.selection), args.preview, args.out)
        print(f"packet {args.out}: {len(packet['pairs'])} pairs; keep key.json closed until verdicts are recorded")
    else:
        value = record(args.packet, _load(args.verdicts), args.listener, args.listened_at)
        _write_new(args.out, value)
        print(f"result {value['result']}: {len(value['audibleDifferencePairs'])} of {value['pairCount']} pairs differ")
    return 0


if __name__ == "__main__":
    sys.exit(main())
