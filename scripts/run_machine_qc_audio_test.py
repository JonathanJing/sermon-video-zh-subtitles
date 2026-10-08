#!/usr/bin/env python3
"""Run the machine-QC audio path (the listening waiver) on an existing Dev run.

Companion of ``run_machine_qc_clip_test.py`` (the text path). Once a locale has
a text waiver, a speech job v3 bound to it, a rendered audio package and its v2
ASR screening, this driver, for each locale:

1. finds the audio package, then the speech job, English source package,
   anchor, candidate, policy and text waiver it binds, and the screening of
   that package, by canonical JSON hash;
2. checks without any model call that the package can carry a listening waiver:
   machine-screened with no human decision, v3 job bound to a current text
   waiver, screening v2 whose recorded scores rescore, unit audio intact,
   frozen source spans, the job's voice matching the package, and which seeded
   error kinds this material can calibrate at all;
3. proves the assembled track is the screened units in schedule order
   (``target_audio_auto_qc.check_track``);
4. runs per-unit audio QC from the audio repair ledger head: primary opinions
   are the bound screening's own transcripts, units the primary flags get a
   secondary opinion from ``gpt-transcribe``; the receipt is appended to the ledger;
5. calibrates on the same candidate and unit audio with seeded errors, text
   kinds (back-translation, replayed from the text driver's cache when the
   state dir is shared) and audio kinds (wrong_sentence through both ASRs,
   dropped_key_word rendered by the job's own TTS);
6. issues the audio waiver (``machine_quality_release_basis.build_audio_waiver``).

``--backend fake`` swaps every model for a plumbing fake: the waiver is built in
memory and never saved, and fake receipts name a ``fake-not-evidence`` backend.

The real backend needs the run's persistent ``--state-dir`` (the same one the
text driver used: it holds the repair ledgers and the back-translation cache), a
CUDA host with the screening's Qwen3-ASR (``--asr-model-path``) and the job's TTS
checkpoint (``--tts-checkpoint-map``) under a bound Spark model session, and an
OpenAI Project selected by ``scripts/run_with_openai_environment.py``. Paid
secondary ASR calls are capped by ``--max-api-calls`` and never retried; a call
with an unknown outcome blocks new dispatch until it is reconciled.

QC receipts are kept per ledger entry in the state dir; track checks,
calibrations and waivers are written once under names derived from their
inputs. ``timings.tsv`` and ``summary.json`` record the run. The driver never
publishes and never marks anything human approved.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import fcntl
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import threading

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts import auto_qc_seeded_errors as seeded
from scripts import machine_qc_audio_transports as transports
from scripts import machine_quality_release_basis as basis
from scripts import machine_repair_ledger as ledger
from scripts import run_machine_qc_clip_test as text_driver
from scripts import target_audio_auto_qc as audio_qc

# Output directories of this invocation, for the exit-time run report.
REPORT_DIRS: list[Path] = []

ROOT = Path(__file__).resolve().parents[1]
LOCALES = text_driver.LOCALES
MAX_WORKERS = 8
AUDIO_PACKAGE_SCHEMA = "sermon-target-language-audio-package-v1"
SCREENING_SCHEMAS = ("sermon-target-language-audio-screening-v1", "sermon-target-language-audio-screening-v2")
MACHINE_SPEECH_JOB_SCHEMA = "sermon-target-language-speech-job-v3"
MAX_TRIALS = 30  # seeded.calibrate default: audio kinds are tried on the first units only
json_sha256 = basis.json_sha256
read, save, Timings = text_driver.read, text_driver.save, text_driver.Timings
save_once, load_once, binding_path = text_driver.save_once, text_driver.load_once, text_driver.binding_path


# ---------------------------------------------------------------- discovery

def json_files(run_dir: Path, max_bytes: int = 20 * 1024 * 1024):
    for path in sorted(Path(run_dir).rglob("*.json")):
        if not path.is_file() or path.stat().st_size > max_bytes:
            continue
        try:
            value = read(path)
        except (ValueError, UnicodeDecodeError, OSError):
            continue
        if isinstance(value, dict):
            yield path, value


def find_package(run_dir: Path, locale: str, override: Path | None) -> tuple[Path | None, list[str]]:
    if override is not None:
        return override, []
    found = [path for path, value in json_files(run_dir)
             if value.get("schemaVersion") == AUDIO_PACKAGE_SCHEMA and value.get("targetLocale") == locale]
    screened = [path for path in found if basis._machine_screened(read(path))]
    for choice in (found, screened):
        if len(choice) == 1:
            return choice[0], []
    return None, [str(path) for path in found]


def bound_input(job: dict, name: str, index: dict) -> tuple[Path | None, dict | None]:
    """The file a speech job input names, verified by its canonical hash (or found by it in the run)."""
    reference = (job.get("inputs") or {}).get(name) or {}
    expected = reference.get("jsonSha256")
    if not expected:
        return None, None
    candidates = ([Path(reference["path"])] if isinstance(reference.get("path"), str) else []) + index.get(expected, [])
    for path in candidates:
        try:
            value = read(path)
        except (OSError, ValueError):
            continue
        if json_sha256(value) == expected:
            return Path(path), value
    return None, None


def find_screening(run_dir: Path, package: dict) -> tuple[Path | None, list[str]]:
    matches = []
    for path, value in json_files(run_dir):
        if value.get("schemaVersion") not in SCREENING_SCHEMAS:
            continue
        try:
            basis.screening_queue(package, value)
        except (ValueError, KeyError, TypeError):
            continue
        matches.append(path)
    if len({json_sha256(read(path)) for path in matches}) == 1:
        return matches[0], []
    return None, [str(path) for path in matches]


def source_spans(candidate: dict, anchor: dict) -> list[float]:
    """Each group's frozen source span, computed as the audio waiver recomputes it."""
    units = {unit["sourceUnitId"]: unit for unit in anchor["sourceUnits"]}
    return [float(units[group["sourceUnitIds"][-1]]["end"]) - float(units[group["sourceUnitIds"][0]]["start"])
            for group in candidate["groups"]]


def audio_coverage(job: dict, locale: str) -> dict:
    """Audio kinds this material can carry; wrong_sentence and dropped_key_word need ASR/TTS trials."""
    texts = [unit["text"] for unit in job["units"]][:MAX_TRIALS]
    dropped = sum(seeded.drop_key_word(text, locale) is not None for text in texts)
    untestable = [kind for kind, count in (("dropped_key_word", dropped), ("wrong_sentence", len(set(texts)) - 1))
                  if count < 1]
    return {"droppedKeyWordTrials": dropped, "wrongSentenceUnits": len(texts), "untestableKinds": untestable}


def resolve_locale(run_dir: Path, index: dict, locale: str, override: Path | None) -> dict:
    """Paths and blocking problems for one locale, without model calls."""
    path, ambiguous = find_package(run_dir, locale, override)
    if path is None:
        return {"locale": locale, "problems": [f"no unique audio package; found {len(ambiguous)}: {ambiguous[:6]}"]}
    package = read(path)
    problems, paths = [], {"package": str(path)}
    if package.get("schemaVersion") != AUDIO_PACKAGE_SCHEMA or package.get("targetLocale") != locale:
        return {"locale": locale, "paths": paths, "problems": [f"{path} is not a {locale} audio package"]}
    if not basis._machine_screened(package):
        problems.append("audio package is not machine-screened with human review still pending "
                        f"(status {package.get('status')!r}, screening {(package.get('machineScreening') or {}).get('status')!r})")
    job_hits = index.get(package.get("targetLanguageSpeechJobJsonSha256") or "", [])
    if not job_hits:
        return {"locale": locale, "paths": paths, "problems": problems + ["no speech job in the run matches the package"]}
    paths["job"] = str(job_hits[0])
    job = read(job_hits[0])
    if job.get("schemaVersion") != MACHINE_SPEECH_JOB_SCHEMA:
        problems.append(f"speech job is {job.get('schemaVersion')!r}; the listening waiver needs the v3 job "
                        "that binds a text waiver")
    values = {}
    for name, key in (("source", "englishSourcePackage"), ("anchor", "anchorManifest"),
                      ("candidate", "targetLanguageCandidate"), ("policy", "targetLanguagePolicy"),
                      ("textWaiver", "textReleaseBasis")):
        found, value = bound_input(job, key, index)
        if found is None:
            problems.append(f"speech job input {key} is missing or changed")
        else:
            paths[name], values[name] = str(found), value
    if len(values) < 5:
        return {"locale": locale, "paths": paths, "problems": problems}
    source, anchor, candidate = values["source"], values["anchor"], values["candidate"]
    text_waiver = values["textWaiver"]
    if (package.get("targetLanguageCandidateJsonSha256") != json_sha256(candidate)
            or package.get("englishSourcePackageJsonSha256") != json_sha256(source)):
        problems.append("audio package was rendered from another candidate or source than the speech job binds")
    if [unit.get("text") for unit in job.get("units") or []] != [group["targetText"] for group in candidate["groups"]]:
        problems.append("speech job units differ from the candidate text")
    try:
        basis.validate_text_waiver(text_waiver, candidate=candidate, source_sha=json_sha256(source),
                                   anchor_sha=json_sha256(anchor))
    except (ValueError, KeyError, TypeError) as error:
        problems.append(f"text waiver does not hold for this candidate now: {error}")
    if text_waiver.get("condensedGroupIds"):
        problems.append("the text waiver covers a condensed spoken script; this driver handles full candidates only")
    screening_path, screenings = find_screening(run_dir, package)
    if screening_path is None:
        problems.append(f"no unique ASR screening of this package; found {len(screenings)}: {screenings[:4]}")
    else:
        paths["screening"] = str(screening_path)
        screening = read(screening_path)
        try:
            settings = audio_qc.screening_asr_settings(screening)
            if (settings.get("runtime") or {}).get("backend") != "qwen-asr-local":
                problems.append("screening was not written by the qwen-asr-local screening CLI")
        except ValueError as error:
            problems.append(str(error))
        problems += basis.screening_score_problems(screening, candidate)
    for unit in package.get("units") or []:
        audio = Path(unit["audio"]["path"])
        try:
            data = audio.read_bytes()
            if transports._sha(data) != unit["audio"]["sha256"]:
                problems.append(f"unit audio changed since the package: {unit['textGroupId']}")
            else:
                audio_qc.decode_pcm16(data)
        except (OSError, ValueError, EOFError) as error:
            problems.append(f"unit audio unreadable as PCM16 WAV: {unit['textGroupId']}: {type(error).__name__}")
    try:
        if any(span <= 0 for span in source_spans(candidate, anchor)):
            problems.append("a group has no positive frozen source span")
    except (KeyError, IndexError, TypeError, ValueError):
        problems.append("candidate groups do not bind frozen anchor units")
    try:
        identity = transports.render_identity(job)
        problems += basis.waiver.render_binding_problems({"renderIdentity": identity}, package, job)
    except (ValueError, KeyError) as error:
        problems.append(f"speech job synthesis identity: {error}")
    for name in ("track", "schedule"):
        if not Path((package.get(name) or {}).get("path", "")).is_file():
            problems.append(f"package {name} file is missing")
    text_coverage = text_driver.calibration_coverage(text_driver.qc_groups(candidate, anchor), locale, values["policy"])
    audio = audio_coverage(job, locale)
    if text_coverage["untestableKinds"] or audio["untestableKinds"]:
        problems.append("this material cannot be calibrated for: "
                        + ", ".join(text_coverage["untestableKinds"] + [f"audio.{k}" for k in audio["untestableKinds"]]))
    flagged = basis.screening_queue(package, read(screening_path)) if screening_path is not None else []
    return {"locale": locale, "paths": paths, "packageJsonSha256": json_sha256(package),
            "calibrationCoverage": {"text": text_coverage, "audio": audio},
            "flaggedGroups": flagged, "problems": problems}


# ---------------------------------------------------------------- transports

def make_transports(backend: str, args, state: Path, *, locale: str, screening: dict, job: dict,
                    package: dict) -> tuple:
    """``(primary, secondary, tts)`` for one locale."""
    if backend == "fake":
        tts = transports.FakeTts(job)
        texts = {unit["audio"]["sha256"]: job_unit["text"] for unit, job_unit in zip(package["units"], job["units"])}
        return (transports.FakePrimaryAsr(screening, tts), transports.FakeSecondaryAsr(locale, texts, tts), tts)
    primary = transports.QwenPrimaryAsr(screening, cache=state / "asr-calls" / "primary", model_path=args.asr_model_path)
    secondary = transports.OpenAiTranscribeSecondary(locale, cache=state / "asr-calls" / "secondary",
                                                     max_calls=args.max_api_calls)
    checkpoint = transports.checkpoint_path(job, read(args.tts_checkpoint_map))
    tts = transports.QwenTtsRender(job, checkpoint=checkpoint, cache=state / "tts-renders", seed=args.tts_seed,
                                   device=args.tts_device, dtype=args.tts_dtype,
                                   attention=None if args.tts_attention == "none" else args.tts_attention,
                                   instruct=args.tts_instruct)
    return primary, secondary, tts


def uncertain_calls(state: Path) -> list[str]:
    return transports.CallCache(state / "asr-calls" / "secondary", paid=True).uncertain()


def parallel(function, items: list, workers: int) -> list:
    """Run ``function`` over ``items``; after any failure nothing new is dispatched."""
    failed = threading.Event()

    def run(item):
        if failed.is_set():
            return None
        try:
            return function(item)
        except BaseException:
            failed.set()
            raise

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(run, item) for item in items]
    return [future.result() for future in futures]


# ---------------------------------------------------------------- one locale

def qc_units(job: dict, package: dict, candidate: dict, anchor: dict) -> list[dict]:
    return [{"groupId": unit["textGroupId"], "text": job_unit["text"], "sourceSeconds": span,
             "wav": Path(unit["audio"]["path"]).read_bytes(), "sourceUnitIds": group["sourceUnitIds"]}
            for unit, job_unit, group, span in zip(package["units"], job["units"], candidate["groups"],
                                                    source_spans(candidate, anchor))]


def run_locale(locale: str, paths: dict, out: Path, state: Path, judge, asr: tuple, timings: Timings,
               workers: int, *, fake: bool) -> dict:
    primary, secondary, tts = asr
    package, job, screening = read(Path(paths["package"])), read(Path(paths["job"])), read(Path(paths["screening"]))
    source, anchor = read(Path(paths["source"])), read(Path(paths["anchor"]))
    candidate, policy, text_waiver = read(Path(paths["candidate"])), read(Path(paths["policy"])), read(Path(paths["textWaiver"]))
    implementation = basis.waiver.implementation_sha256()
    folder = out / locale
    result = {}

    # 3. The assembled track is the screened units in schedule order.
    track_binding = json_sha256({"package": package, "implementation": implementation})
    track_path = folder / f"track-check-{track_binding[:16]}.json"
    track = load_once(track_path, track_binding)
    if track is None:
        track = timings.run(f"{locale}.track-check", lambda: audio_qc.check_track(package))
        save_once(track_path, track, track_binding)
    result.update(trackCheck=track["status"], trackCheckReceipt=str(track_path))
    if track["status"] != "pass":
        result.update(status="track_check_failed", reason="; ".join(track["issues"]))
        return result

    # 4. Unit audio QC from the audio repair ledger head.
    units = qc_units(job, package, candidate, anchor)
    lineage = ledger.lineage("audio", locale, json_sha256(source), json_sha256(anchor))
    ledger_root = state / "repair-ledger"
    entries = ledger.load(ledger_root, lineage)
    head_path = text_driver.qc_receipt_path(state, lineage, len(entries)) if entries else None
    head = read(head_path) if head_path and head_path.exists() else None
    if head is not None and ledger.head_problems(lineage, entries, head):
        head = None
    if entries and entries[-1]["failedSourceUnitIds"]:
        if head is None:
            return {**result, "status": "blocked_prior_failure",
                    "reason": f"the audio repair ledger head failed and its QC receipt is missing from {head_path}"}
        current = {(unit["groupId"], transports._sha(unit["wav"])) for unit in units}
        unrepaired = [row["groupId"] for row in head["results"]
                      if row["status"] == "fail" and (row["groupId"], row["audioSha256"]) in current]
        if unrepaired:
            return {**result, "status": "blocked_prior_failure", "failedGroups": unrepaired,
                    "reason": "failed units still have the same audio; re-render them (new seed or revised text) first"}
    counts = entries[-1]["failedAttempts"] if entries else {}
    exhausted = [unit["groupId"] for unit in units
                 if any(counts.get(unit_id, 0) > audio_qc.MAX_REPAIR_ATTEMPTS for unit_id in unit["sourceUnitIds"])]
    if exhausted:
        return {**result, "status": "subtitle_only", "subtitleOnlyGroups": exhausted,
                "reason": "the audio repair limit is used up; waiver v1 cannot release subtitle-only units"}
    spans = [unit["sourceSeconds"] for unit in units]
    qc_binding = json_sha256({"package": json_sha256(package), "screening": json_sha256(screening),
                              "primary": primary.identity(), "secondary": secondary.identity(),
                              "spans": spans, "implementation": implementation})
    qc = load_once(head_path, qc_binding) if head is not None else None
    if qc is None:
        next_path = text_driver.qc_receipt_path(state, lineage, len(entries) + 1)
        pending = load_once(next_path, qc_binding) if next_path.exists() else None
        if pending is not None and pending.get("repairLedger") == ledger.position(lineage, entries):
            qc = pending
        else:
            for stale in (next_path, binding_path(next_path)):
                stale.unlink(missing_ok=True)
            threshold = audio_qc.THRESHOLDS["asrMinSimilarity"]
            for unit in units:
                unit["asr"] = {"primary": primary.opinion(unit["wav"], unit["text"], locale)}
            flagged = [unit for unit in units
                       if not audio_qc.transcript_agrees(unit["text"], unit["asr"]["primary"]["recognized"],
                                                         locale, threshold)]
            if flagged:
                opinions = timings.run(f"{locale}.secondary-asr", lambda: parallel(
                    lambda unit: secondary.opinion(unit["wav"], unit["text"], locale), flagged, workers))
                for unit, opinion in zip(flagged, opinions):
                    unit["asr"]["secondary"] = opinion
            qc = timings.run(f"{locale}.audio-qc", lambda: audio_qc.screen(
                units, locale, repair_position=ledger.position(lineage, entries)))
            save_once(next_path, qc, qc_binding)
        ledger.append(ledger_root, lineage, qc)
        head_path = next_path
    result.update(audioQc=qc["status"], audioQcReceipt=str(head_path),
                  secondaryAsrGroups=[row["groupId"] for row in qc["results"] if row["asrSecondaryModel"]],
                  failedGroups=[row["groupId"] for row in qc["results"] if row["status"] != "pass"])
    if qc["subtitleOnlyGroupIds"]:
        result.update(status="subtitle_only", subtitleOnlyGroups=qc["subtitleOnlyGroupIds"],
                      reason="the audio repair limit is used up; waiver v1 cannot release subtitle-only units")
        return result
    if qc["status"] != "pass":
        result.update(status="requires_repair",
                      nextActions={row["groupId"]: row["nextAction"] for row in qc["results"] if row["status"] != "pass"},
                      reason="audio QC failed; re-render the failed units as the repair ladder says")
        return result

    # 5. Seeded-error calibration on this candidate and this unit audio.
    groups = text_driver.qc_groups(candidate, anchor)
    calibration_binding = json_sha256({"qc": qc_binding, "candidate": json_sha256(candidate), "policy": policy,
                                       "judge": judge.identity, "renderIdentity": tts.identity,
                                       "renderSettings": getattr(tts, "settings", None)})
    calibration_path = folder / f"audio-calibration-{calibration_binding[:16]}.json"
    calibration = load_once(calibration_path, calibration_binding)
    if calibration is None:
        if not fake:
            problems = primary.runtime_problems()
            if problems:
                return {**result, "status": "blocked_runtime", "reason": "; ".join(problems)}
        timings.run(f"{locale}.calibration.prefetch", lambda: text_driver.prefetch(
            judge, lambda call: seeded.calibrate_text(groups, locale, policy=policy, call=call), workers=workers))
        clean = [{key: value for key, value in unit.items() if key not in ("asr", "sourceUnitIds")} for unit in units]
        calibration = timings.run(f"{locale}.calibration", lambda: seeded.calibrate(
            locale, groups, clean, policy=policy, call=judge, identity=judge.identity,
            asr=transports.asr_router(primary, secondary), render=tts, render_identity=tts.identity,
            candidate=candidate, max_trials=MAX_TRIALS))
        save_once(calibration_path, calibration, calibration_binding)
    result["calibration"] = {key: calibration[key] for key in
                             ("overallDetectionRate", "cleanFalsePositiveRate", "trials", "detected")}
    result["calibrationMisses"] = {kind: row for kind, row in calibration["kinds"].items() if row["rate"] < 0.9}

    # 6. The audio waiver.
    entries = ledger.load(ledger_root, lineage)
    waiver_binding = json_sha256({"calibration": calibration_binding, "qc": json_sha256(qc),
                                  "calibrationReceipt": json_sha256(calibration), "track": json_sha256(track),
                                  "textWaiver": json_sha256(text_waiver), "ledger": entries})
    waiver_path = folder / f"audio-waiver-{waiver_binding[:16]}.json"
    if not fake:
        saved = load_once(waiver_path, waiver_binding)
        if saved is not None:
            basis.validate_audio_waiver(package, saved, screening)
            result.update(status="audio_waiver_issued", audioWaiver=str(waiver_path), reused=True)
            return result
    try:
        receipt = timings.run(f"{locale}.audio-waiver", lambda: basis.build_audio_waiver(
            package, screening, qc, text_waiver, calibration, anchor=anchor, candidate=candidate,
            repair_ledger=entries, speech_job=job, track_check=track))
    except ValueError as error:
        result.update(status="waiver_refused", reason=str(error))
        return result
    basis.validate_audio_waiver(package, receipt, screening)
    if fake:
        result.update(status="fake_plumbing_pass", reason="fake transports: waiver built in memory, never saved")
        return result
    save_once(waiver_path, receipt, waiver_binding)
    result.update(status="audio_waiver_issued", audioWaiver=str(waiver_path))
    return result


def still_valid(row: dict) -> bool:
    """An earlier summary row still describes its package and the receipts it names."""
    try:
        if "paths" in row and json_sha256(read(Path(row["paths"]["package"]))) != row.get("packageJsonSha256"):
            return False
        for key in ("trackCheckReceipt", "audioQcReceipt", "audioWaiver"):
            if key in row and json_sha256(read(Path(row[key]))) != read(binding_path(Path(row[key]))).get("receiptJsonSha256"):
                return False
        if row.get("status") == "audio_waiver_issued":
            basis.validate_audio_waiver(read(Path(row["paths"]["package"])), read(Path(row["audioWaiver"])),
                                        read(Path(row["paths"]["screening"])))
    except (KeyError, OSError, ValueError, TypeError):
        return False
    return True


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--run-dir", type=Path, default=ROOT / "artifacts/dev-full-rerun-20261001")
    parser.add_argument("--out", type=Path, required=True, help="New or resumed output directory (ignored artifacts/)")
    parser.add_argument("--state-dir", type=Path,
                        help="The run's persistent state dir (the text driver's): repair ledgers and call caches")
    parser.add_argument("--locales", default=",".join(LOCALES))
    parser.add_argument("--audio-package", action="append", default=[], metavar="LOCALE=PATH",
                        help="Use this audio package instead of searching the run")
    parser.add_argument("--backend", choices=("real", "fake"), default="real")
    parser.add_argument("--asr-model-path", type=Path, help="Local Qwen3-ASR directory the screening used")
    parser.add_argument("--tts-checkpoint-map", type=Path, help="sermon-speaker-checkpoint-map-v1 of the formal renderer")
    parser.add_argument("--tts-seed", type=int, default=42)
    parser.add_argument("--tts-device", default="cuda:0")
    parser.add_argument("--tts-dtype", choices=("bfloat16", "float32"), default="bfloat16")
    parser.add_argument("--tts-attention", default="sdpa", help="'none' for the model default")
    parser.add_argument("--tts-instruct", default=None)
    parser.add_argument("--max-api-calls", type=int, default=150,
                        help="Cap on new paid gpt-transcribe requests per locale in this process")
    parser.add_argument("--workers", type=int, default=4, help="Parallel back-translation and secondary ASR calls")
    parser.add_argument("--preflight-only", action="store_true", help="Stop before any model call")
    args = parser.parse_args(argv)
    locales = [locale for locale in args.locales.split(",") if locale]
    if not locales or set(locales) - set(LOCALES):
        parser.error(f"--locales must name one or more of {', '.join(LOCALES)}")
    if not 1 <= args.workers <= MAX_WORKERS:
        parser.error(f"--workers must be between 1 and {MAX_WORKERS}")
    if args.max_api_calls < 0:
        parser.error("--max-api-calls must not be negative")
    real = args.backend == "real"
    if real and not args.preflight_only:
        if not args.state_dir:
            parser.error("real runs need --state-dir: the run's persistent state dir holding its repair ledgers")
        if not args.asr_model_path or not args.tts_checkpoint_map:
            parser.error("real runs need --asr-model-path and --tts-checkpoint-map")
        from scripts import sermon_openai_runtime
        try:
            route = sermon_openai_runtime.selected_route()
        except ValueError as error:
            parser.error(f"the selected OpenAI runtime is invalid: {error}")
        if route is None:
            parser.error("the secondary ASR uses the OpenAI API: start under "
                         "scripts/run_with_openai_environment.py --environment dev (prod for formal content)")
    if not real and args.state_dir:
        parser.error("--backend fake never writes to a persistent state dir")
    overrides = {}
    for item in args.audio_package:
        locale, _, path = item.partition("=")
        if not path or locale not in locales or locale in overrides:
            parser.error(f"--audio-package {item!r}: use LOCALE=PATH once per requested locale ({', '.join(locales)})")
        overrides[locale] = Path(path)
    out = args.out.resolve() / ("" if real else "fake-plumbing")
    state = (args.state_dir or out / "state").resolve() if real else out / "state"
    for path in (out, state):
        if path.is_relative_to(ROOT) and subprocess.run(["git", "-C", str(ROOT), "check-ignore", "-q", str(path)]).returncode:
            parser.error(f"{path} is not ignored by Git; use a directory under artifacts/")
    out.mkdir(parents=True, exist_ok=True)
    state.mkdir(parents=True, exist_ok=True)
    REPORT_DIRS.append(out)
    locks = []
    for folder in dict.fromkeys((out, state)):  # One writer per OUT and per state dir.
        locks.append((folder / ".audio-run.lock").open("a"))
        try:
            fcntl.flock(locks[-1], fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            parser.error(f"another audio run is using {folder}")
    timings = Timings(out / "timings.tsv")
    index = timings.run("discover", lambda: text_driver.index_run(args.run_dir))
    summary = {"runDir": str(args.run_dir.resolve()), "backend": args.backend,
               "implementationSha256": basis.waiver.implementation_sha256(),
               "transportSha256": transports.implementation_sha256(), "locales": {}}
    previous = read(out / "summary.json") if (out / "summary.json").exists() else {}
    if all(previous.get(key) == summary[key] for key in ("runDir", "backend", "implementationSha256", "transportSha256")):
        for locale, row in previous.get("locales", {}).items():
            if locale not in locales:
                summary["locales"][locale] = row if still_valid(row) else {
                    "status": "stale", "reason": "earlier row no longer matches its evidence; rerun this locale",
                    "previousStatus": row.get("status")}
    resolved = {}
    for locale in locales:
        found = resolve_locale(args.run_dir, index, locale, overrides.get(locale))
        save(out / locale / "preflight.json", found)
        summary["locales"][locale] = {"status": "blocked" if found["problems"] else "ready", **found}
        if not found["problems"]:
            resolved[locale] = found["paths"]
    save(out / "summary.json", summary)
    if args.preflight_only or not resolved:
        print(json.dumps({locale: summary["locales"][locale]["problems"] for locale in locales},
                         ensure_ascii=False, indent=2))
        return 0 if len(resolved) == len(locales) else 2
    groups = {locale: text_driver.qc_groups(read(Path(paths["candidate"])), read(Path(paths["anchor"])))
              for locale, paths in resolved.items()}
    judge = text_driver.CodexJudge(state / "codex-calls") if real else text_driver.FakeJudge(groups)
    for locale, paths in resolved.items():
        uncertain = judge.uncertain() + uncertain_calls(state)
        if uncertain:
            outcome = {"status": "blocked_unknown_outcome", "uncertainCalls": uncertain,
                       "reason": f"model calls with an unknown outcome under {state}; reconcile them first"}
        else:
            try:
                asr = make_transports(args.backend, args, state, locale=locale, screening=read(Path(paths["screening"])),
                                      job=read(Path(paths["job"])), package=read(Path(paths["package"])))
                outcome = run_locale(locale, paths, out, state, judge, asr, timings, args.workers, fake=not real)
            except Exception as error:  # The summary says what failed.
                outcome = {"status": "error", "reason": f"{type(error).__name__}: {error}"}
        summary["locales"][locale].update(outcome)
        save(out / "summary.json", summary)
    print(json.dumps({locale: {key: row.get(key) for key in ("status", "reason", "problems", "calibration")}
                      for locale, row in summary["locales"].items()}, ensure_ascii=False, indent=2))
    done = "audio_waiver_issued" if real else "fake_plumbing_pass"
    return 0 if all(summary["locales"][locale].get("status") == done for locale in locales) else 1


if __name__ == "__main__":
    from scripts.export_run_digest import write_report
    try:
        code = main()
    finally:
        if REPORT_DIRS:  # Pass or fail, leave a redacted run report for cloud review.
            write_report(REPORT_DIRS, "machine-qc-audio")
    sys.exit(code)
