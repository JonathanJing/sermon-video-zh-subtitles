#!/usr/bin/env python3
"""Build, then close, the post-publication listening sample sheet for one locale.

    python3 scripts/build_listening_sample.py build \
        --audio-package artifacts/weekend-live/layer3-<run>/ko/audio-package-c5.json \
        --candidate artifacts/weekend-live/layer2-<run>/recovered/ko/candidate.json \
        --anchors <the anchor manifest the candidate names in anchorManifestSha256> \
        --screening artifacts/weekend-live/layer3-<run>/ko/<speech job>/speech-job/asr-screening-receipt-c5.json \
        --audio-qc artifacts/weekend-live/text-qc-<run>/state-v3/qc-receipts/audio/ko/<lineage>/entry-000001.json \
        --out artifacts/weekend-live/listening-<run>/ko
    python3 scripts/build_listening_sample.py verdicts --sheet-dir artifacts/weekend-live/listening-<run>/ko
    python3 scripts/record_decision.py --run-dir <run> --question "ko 发布后抽查" --choice "<n 句通过，m 句有问题>" \
        --decided-by "Jony (chat)" --governs <the audio package> \
        --evidence artifacts/weekend-live/listening-<run>/ko/listening-verdicts.json

The sheet lists every unit a machine check did not pass (the ASR screening, and
audio QC when given) plus a seeded random sample of the rest (10 by default),
each with the published translation, the frozen English, the unit audio path and
a blank verdict cell. It replaces the small-hours "listened, passed" statement
with ten minutes on Monday.

Everything is checked before anything is written:
- the candidate is the one the audio package names, and each unit's text hash
  matches its group;
- the anchor manifest is the one the candidate names, with English for every unit;
- the ASR screening receipt is required and must cover this package exactly
  (speech job, locale, track, and every unit's group, text and audio hash);
  without it, units the screening flagged and audio QC later passed would drop
  out of a sheet that claims to list every flagged unit;
- each audio QC receipt names this package's audio and text for every group;
- every listed unit's audio file still hashes to the package's value, so the
  operator hears the bytes the package bound.
The manifest records each input's hash and the number of units actually sampled.

``verdicts`` reads the filled sheet, requires a verdict on every row, and writes
listening-verdicts.json bound to the sheet and the manifest; that is the file
record_decision.py binds. Neither file is a receipt: they change no package or
waiver, and humanApproval stays false.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

try:
    from scripts import sermon_sentence_interpretation as identity
except ImportError:  # pragma: no cover - direct CLI runs from scripts/
    import sermon_sentence_interpretation as identity

SCHEMA = "sermon-listening-sample-v1"
VERDICTS_SCHEMA = "sermon-listening-verdicts-v1"
SCREENING_PREFIX = "sermon-target-language-audio-screening-"
SHEET, MANIFEST, VERDICTS = "listening-sample.md", "listening-sample.json", "listening-verdicts.json"
PASS_WORDS = {"通过", "pass"}
ISSUE = re.compile(r"^(?:问题|issue)\s*[:：]?\s*(.+)$", re.I)


def read(path: Path) -> dict:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Expected a JSON object: {path}")
    return value


def file_sha256(path: Path) -> str | None:
    digest = hashlib.sha256()
    try:
        with Path(path).open("rb") as stream:
            for chunk in iter(lambda: stream.read(1 << 20), b""):
                digest.update(chunk)
    except OSError:
        return None
    return digest.hexdigest()


def check_screening(package: dict, screening: dict) -> None:
    """The screening receipt must be this package's: same speech job, locale, track and units, in order."""
    units = package["units"]
    track = (package.get("track") or {}).get("sha256")
    results = screening.get("results")
    problem = (
        "it is not an ASR screening receipt" if not str(screening.get("schemaVersion", "")).startswith(SCREENING_PREFIX)
        else "it screened another speech job"
        if screening.get("targetLanguageSpeechJobJsonSha256") != package.get("targetLanguageSpeechJobJsonSha256")
        else "it screened another locale" if screening.get("targetLocale") != package.get("targetLocale")
        else "it screened another track" if track is not None and screening.get("trackSha256") != track
        else "its unit audio differs" if screening.get("unitAudioSha256s") != [unit["audio"]["sha256"] for unit in units]
        else "it does not cover every unit" if not isinstance(results, list) or len(results) != len(units)
        else next((f"its row for {unit['textGroupId']} names other text or audio" for row, unit in zip(results, units)
                   if not isinstance(row, dict) or (row.get("textGroupId"), row.get("targetTextSha256"), row.get("audioSha256"))
                   != (unit["textGroupId"], unit["targetTextSha256"], unit["audio"]["sha256"])), None))
    if problem:
        raise ValueError(f"The ASR screening receipt is not this audio package's: {problem}")


def check_audio_qc(package: dict, receipt: dict) -> None:
    """Each audio QC row must name this package's audio and text for its group."""
    units = {unit["textGroupId"]: unit for unit in package["units"]}
    if receipt.get("locale") != package.get("targetLocale"):
        raise ValueError("An audio QC receipt is for another locale")
    for row in receipt.get("results") or []:
        unit = units.get(row.get("groupId")) if isinstance(row, dict) else None
        if unit is None or (row.get("audioSha256"), row.get("textSha256")) != (unit["audio"]["sha256"], unit["targetTextSha256"]):
            name = row.get("groupId") if isinstance(row, dict) else row
            raise ValueError(f"An audio QC receipt checked other audio or text for {name}")


def flagged_groups(receipts) -> dict[str, list[str]]:
    """Group id → reasons for every row a check did not pass (screening ``results`` or audio QC ``results``)."""
    reasons: dict[str, list[str]] = {}
    for receipt in receipts:
        for row in receipt.get("results") or []:
            if not isinstance(row, dict) or row.get("status") == "pass":
                continue
            group = row.get("groupId") or row.get("textGroupId")
            if isinstance(group, str):
                reasons.setdefault(group, []).append(
                    str(row.get("status")) + (": " + ", ".join(row["issues"]) if row.get("issues") else ""))
    return reasons


def build(package: dict, candidate: dict, *, anchors: dict, screening: dict, audio_qc=(), sample_size: int = 10,
          seed: str | None = None, package_path: str | None = None,
          now=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds")) -> dict:
    package_sha = identity.json_sha256(package)
    candidate_sha = identity.json_sha256(candidate)
    if candidate_sha != package.get("targetLanguageCandidateJsonSha256"):
        raise ValueError("The candidate is not the one the audio package was rendered from")
    anchors_sha = identity.json_sha256(anchors)
    if anchors_sha != candidate.get("anchorManifestSha256"):
        raise ValueError("The anchor manifest is not the one the candidate was translated from")
    units = package.get("units") or []
    if not units:
        raise ValueError("The audio package has no units")
    groups = {group["translationGroupId"]: group for group in candidate.get("groups", [])}
    english = {row["translationGroupId"]: row.get("targetEnglish") for row in anchors.get("translationRequests", [])
               if isinstance(row, dict)}
    rows = []
    for index, unit in enumerate(units):
        group_id = unit.get("textGroupId")
        group = groups.get(group_id)
        if group is None:
            raise ValueError(f"Unit {group_id} has no group in the candidate")
        text = group.get("targetText", "")
        if hashlib.sha256(text.encode("utf-8")).hexdigest() != unit.get("targetTextSha256"):
            raise ValueError(f"Unit {group_id} text differs from the candidate group")
        if not isinstance(english.get(group_id), str):
            raise ValueError(f"Unit {group_id} has no English in the anchor manifest")
        rows.append({"index": index, "groupId": group_id, "text": text, "english": english[group_id],
                     "audioPath": unit["audio"]["path"], "audioSha256": unit["audio"]["sha256"],
                     "textSha256": unit["targetTextSha256"], "durationSeconds": unit.get("durationSeconds")})
    check_screening(package, screening)
    for receipt in audio_qc:
        check_audio_qc(package, receipt)
    if type(sample_size) is not int or sample_size < 0:
        raise ValueError("sample size must be a non-negative integer")
    flagged = flagged_groups([screening, *audio_qc])
    seed = seed or package_sha
    pool = [row["groupId"] for row in rows if row["groupId"] not in flagged]
    chosen = set(random.Random(seed).sample(pool, min(sample_size, len(pool))))
    selected = []
    for row in rows:
        if row["groupId"] in flagged:
            selected.append({**row, "reason": "flagged", "flags": flagged[row["groupId"]]})
        elif row["groupId"] in chosen:
            selected.append({**row, "reason": "random"})
    for row in selected:
        if file_sha256(row["audioPath"]) != row["audioSha256"]:
            raise ValueError(f"Unit {row['groupId']} audio at {row['audioPath']} is missing or no longer matches the package")
    return {"schemaVersion": SCHEMA, "builtAt": now(), "targetLocale": package.get("targetLocale"),
            "packageId": package.get("packageId"), "audioPackagePath": package_path, "audioPackageJsonSha256": package_sha,
            "targetLanguageCandidateJsonSha256": candidate_sha, "anchorManifestJsonSha256": anchors_sha,
            "screeningReceiptJsonSha256": identity.json_sha256(screening),
            "audioQcReceiptJsonSha256s": [identity.json_sha256(receipt) for receipt in audio_qc],
            "seed": seed, "sampleSizeRequested": sample_size, "sampleSize": len(chosen), "unflaggedCount": len(pool),
            "unitCount": len(rows), "flaggedCount": sum(row["reason"] == "flagged" for row in selected),
            "audioBytesVerified": True, "rows": selected, "humanApproval": False, "scope": "review_aid_not_a_receipt"}


def markdown(sample: dict) -> str:
    random_note = f"另随机抽 {sample['sampleSize']} 句"
    if sample["sampleSize"] < sample["sampleSizeRequested"]:
        random_note += f"（请求 {sample['sampleSizeRequested']} 句，未标记的只有 {sample['unflaggedCount']} 句）"
    package = f"`{sample['audioPackagePath']}`" if sample.get("audioPackagePath") else "<音频包>"
    lines = [f"# 听审抽样 · {sample['targetLocale']} · {sample['packageId']}", "",
             f"音频包 `{sample['audioPackageJsonSha256'][:12]}`，候选 `{sample['targetLanguageCandidateJsonSha256'][:12]}`，"
             f"共 {sample['unitCount']} 句；机器标记 {sample['flaggedCount']} 句全部列出，{random_note}"
             f"（种子 `{sample['seed'][:12]}`）。每行听一遍音频，把「结论」的 `[ ]` 改成 `通过` 或 `问题：…`。", "",
             f"填完运行 `python3 scripts/build_listening_sample.py verdicts --sheet-dir <本目录>`，它检查每行都有结论并写出 "
             f"`{VERDICTS}`；再用 `record_decision.py --governs {package} --evidence <本目录>/{VERDICTS}` 记录。"
             "本表是复核辅助，不是收据。", "",
             "| 序 | 组 | 译文 | 英文 | 音频 | 秒 | 来源 | 结论 |", "|---|---|---|---|---|---|---|---|"]
    cell = lambda value: str(value).replace("|", "\\|").replace("\n", " ")
    for row in sample["rows"]:
        source = "机器标记：" + "；".join(row["flags"]) if row["reason"] == "flagged" else "随机"
        lines.append(f"| {row['index'] + 1} | `{row['groupId']}` | {cell(row['text'])} | {cell(row['english'])} | "
                     f"`{row['audioPath']}` | {row['durationSeconds']} | {cell(source)} | [ ] |")
    return "\n".join(lines) + "\n"


def verdicts(sheet_dir: Path, now=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds")) -> dict:
    """Read the filled sheet; every manifest row needs exactly one verdict: 通过 / pass, or 问题：… / issue: …."""
    sheet_dir = Path(sheet_dir)
    sample = read(sheet_dir / MANIFEST)
    if sample.get("schemaVersion") != SCHEMA:
        raise ValueError(f"{sheet_dir / MANIFEST} is not a listening sample manifest")
    sheet_bytes = (sheet_dir / SHEET).read_bytes()
    expected = {row["index"] + 1: row for row in sample["rows"]}
    found, missing = {}, []
    for line in sheet_bytes.decode("utf-8").splitlines():
        cells = [cell.strip() for cell in re.split(r"(?<!\\)\|", line.strip())[1:-1]]
        if len(cells) < 8 or not cells[0].isdigit():
            continue  # title, prose, header and separator lines
        number, group = int(cells[0]), cells[1].strip("`")
        row = expected.get(number)
        if row is None or row["groupId"] != group or number in found:
            raise ValueError(f"Sheet row {number} ({group}) is not a row of this sample")
        answer = re.sub(r"^\[[ xX]?\]\s*", "", cells[-1]).strip()
        issue = ISSUE.match(answer)
        if answer.lower() in PASS_WORDS:
            found[number] = {"verdict": "pass"}
        elif issue:
            found[number] = {"verdict": "issue", "note": issue.group(1).strip()[:2000]}
        else:
            missing.append(number)
            found[number] = None
    absent = sorted(set(expected) - set(found))
    if absent:
        raise ValueError("The sheet lost rows " + ", ".join(map(str, absent)) + "; rebuild it rather than editing rows out")
    if missing:
        raise ValueError("Rows without a verdict: " + ", ".join(map(str, sorted(missing))) + " (write 通过 or 问题：…)")
    rows = [{"index": expected[n]["index"], "groupId": expected[n]["groupId"], "reason": expected[n]["reason"], **found[n]}
            for n in sorted(found)]
    return {"schemaVersion": VERDICTS_SCHEMA, "recordedAt": now(), "targetLocale": sample["targetLocale"],
            "packageId": sample["packageId"], "audioPackageJsonSha256": sample["audioPackageJsonSha256"],
            "sampleJsonSha256": identity.json_sha256(sample), "sheetSha256": hashlib.sha256(sheet_bytes).hexdigest(),
            "counts": {"pass": sum(r["verdict"] == "pass" for r in rows), "issue": sum(r["verdict"] == "issue" for r in rows)},
            "rows": rows, "humanApproval": False, "scope": "post_publication_sample_not_a_receipt"}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    make = commands.add_parser("build", help="Write listening-sample.md and .json for one audio package")
    make.add_argument("--audio-package", type=Path, required=True)
    make.add_argument("--candidate", type=Path, required=True)
    make.add_argument("--anchors", type=Path, required=True, help="The Layer 1 anchor manifest the candidate names")
    make.add_argument("--screening", type=Path, required=True, help="The ASR screening receipt of this package's speech job")
    make.add_argument("--audio-qc", type=Path, action="append", default=[], help="Audio QC receipt entry; repeatable")
    make.add_argument("--sample-size", type=int, default=10)
    make.add_argument("--seed", help="Defaults to the audio package hash, so the same package samples the same units")
    make.add_argument("--out", type=Path, required=True, help="Directory for the sheet and manifest (must not exist)")
    close = commands.add_parser("verdicts", help="Check the filled sheet and write listening-verdicts.json")
    close.add_argument("--sheet-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.command == "verdicts":
        result = verdicts(args.sheet_dir)
        (args.sheet_dir / VERDICTS).write_text(json.dumps(result, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        print(json.dumps({"locale": result["targetLocale"], **result["counts"], "verdicts": str(args.sheet_dir / VERDICTS)},
                         ensure_ascii=False))
        return 0
    if args.out.exists():
        parser.error("output directory already exists: " + str(args.out))
    sample = build(read(args.audio_package), read(args.candidate), anchors=read(args.anchors),
                   screening=read(args.screening), audio_qc=[read(path) for path in args.audio_qc],
                   sample_size=args.sample_size, seed=args.seed, package_path=str(args.audio_package))
    args.out.mkdir(parents=True)
    (args.out / MANIFEST).write_text(json.dumps(sample, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    (args.out / SHEET).write_text(markdown(sample), encoding="utf-8")
    print(json.dumps({"locale": sample["targetLocale"], "rows": len(sample["rows"]), "flagged": sample["flaggedCount"],
                      "sampled": sample["sampleSize"], "sheet": str(args.out / SHEET)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
