#!/usr/bin/env python3
"""Start a sentence-first run with one command (optional setup wrapper).

Runs, in order, what the runbook asks the agent to do one step at a time at 开工
(``AGENTS.md`` §0.5 and §2):

  env       required scripts, ffmpeg/ffprobe, the run-directory rule; opt-in git,
            package-import, Firebase ADC and Spark-session checks
  prepare   prepare_clip.py: clip.wav, words/clip/sentences tables, per-sentence slices
  speakers  assign_speakers.py when --segments and --speaker-map are given
  share     copy clip.json + sentences.jsonl + slices/ to the other locale run dirs
  gate      preflight.py --stage setup (run files, speaker registry, English package,
            optional Spark session / Firebase ADC) for the primary run and every share
  receipt   decisions.json (the frozen decisions, machine-readable) and setup.json next to
            the run, plus one JSON line on stdout

The sync and publish decisions are required flags, not defaults: the runbook asks the user
before any downstream work, and preflight.py --stage setup checks the recorded file. The
title, window, units and sentence count land in decisions.json as well.

It is idempotent: an existing clip.json + sentences.jsonl skips prepare (re-run with
--force-prepare), an identical share target is left untouched, and a share target that
already has translations/review/speech is refused unless --force-share. The command
never writes translations.jsonl, review.json, speech.jsonl or publish files; run.md is
still written by prepare_clip.py only. The full preflight (which needs translations,
review and speech) still runs before TTS: this command journals l1.preflight.setup, the
full gate keeps l1.preflight.

Examples:
  python3 sfa.py start --run 20261102-jesus-wins-zh --locale zh-Hans \\
      --share-to ko=20261102-jesus-wins-ko --share-to es=20261102-jesus-wins-es \\
      --anchor artifacts/podcasts/<episode>/layer1-srt/anchor-manifest.json \\
      --media <video> --window-start 0 --units 0:417 --title "…" \\
      --english-package artifacts/podcasts/<episode>/layer1-srt/english-source.json \\
      --sync --publish
  python3 sfa.py start --run 20261102-jesus-wins-zh --locale zh-Hans \
      --no-sync --no-publish --plan

Exit code 1 when an environment check, a step or a setup gate fails; stdout stays JSON.
"""
from __future__ import annotations

import argparse
import filecmp
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
LOCALES = ("zh-Hans", "ko", "es")
REQUIRED_SCRIPTS = ("preflight.py", "prepare_clip.py", "slice_sentences.py", "assign_speakers.py")
SHARE_FILES = ("clip.json", "sentences.jsonl")
DOWNSTREAM_FILES = ("translations.jsonl", "review.json", "speech.jsonl")
RECEIPT_SCHEMA = "sentence-first-setup-v1"


class SetupError(Exception):
    def __init__(self, step: str, message: str):
        super().__init__(message)
        self.step = step
        self.message = message


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def append_decisions_to_run_md(run: Path, decisions: dict) -> bool:
    """Write the frozen-decision table into run.md once (the runbook asks for it there)."""
    path = run / "run.md"
    if not path.is_file():
        return False
    text = path.read_text(encoding="utf-8")
    if "## 冻结决策" in text:
        return False
    form = {"full": "整期", "clip": "片段"}.get(decisions.get("form"), "未记录")
    sync = "跟视频同步（--gap 0.05）" if decisions["sync"] else "不同步（自然语速）"
    publish = "发布正式页面" if decisions["publish"] else "不发，停在审核包"
    lines = [
        "",
        "## 冻结决策",
        "",
        "| 决策 | 取值 |",
        "|---|---|",
        f"| 形态 | {form} |",
        f"| 语言 | {'、'.join(decisions['locales'])} |",
        f"| 同步 | {sync} |",
        f"| 发布 | {publish} |",
        f"| 标题 | {decisions['title'] or '未记录'} |",
        f"| 窗口 / 单元 | start {decisions.get('windowStart')}，units {decisions.get('units')}（{decisions.get('sentences')} 句） |",
        "",
    ]
    with path.open("a", encoding="utf-8") as handle:
        handle.write("\n".join(lines))
    return True


def build_decisions(a, run: Path, *, shares: dict[str, Path], sentences: int,
                    clip_seconds: float | None) -> dict:
    """The frozen decisions the runbook asks for before any downstream work."""
    return {
        "schemaVersion": "sentence-first-frozen-decisions-v1",
        "run": repo_relative(run),
        "recordedAt": utc_now(),
        "locales": [a.locale, *shares],
        "primaryLocale": a.locale,
        "form": a.form,
        "sync": bool(a.sync),
        "publish": bool(a.publish),
        "title": a.title or "",
        "windowStart": a.window_start,
        "units": a.units,
        "sentences": sentences,
        "clipSeconds": clip_seconds,
    }


def repo_relative(path: Path, repo: Path = ROOT) -> str:
    try:
        return path.relative_to(repo).as_posix()
    except ValueError:
        return str(path)


def resolve_run(value: str, repo: Path = ROOT) -> Path:
    """Resolve a run name/path to an absolute directory under artifacts/sentence-first-agent/."""
    artifact_root = repo / "artifacts" / "sentence-first-agent"
    path = Path(value)
    if path.is_absolute():
        resolved = path.resolve()
    else:
        base = repo if path.parts and path.parts[0] == "artifacts" else artifact_root
        resolved = (base / path).resolve()
    if artifact_root.resolve() not in resolved.parents:
        raise SetupError("env", f"run directory must live under {repo_relative(artifact_root, repo)}/, got {resolved}")
    return resolved


def parse_units(text: str) -> tuple[int, int]:
    lo, sep, hi = text.partition(":")
    if not sep:
        raise SetupError("prepare", f"--units wants LO:HI (inclusive anchor units), got {text!r}")
    try:
        lo_i, hi_i = int(lo), int(hi)
    except ValueError as exc:
        raise SetupError("prepare", f"--units wants integers, got {text!r}") from exc
    if lo_i < 0 or hi_i < lo_i:
        raise SetupError("prepare", f"--units needs 0 <= LO <= HI, got {text!r}")
    return lo_i, hi_i


def parse_shares(values: list[str] | None, primary_locale: str, primary_run: Path,
                 repo: Path = ROOT) -> dict[str, Path]:
    shares: dict[str, Path] = {}
    for item in values or []:
        locale, sep, value = item.partition("=")
        if not sep or not value:
            raise SetupError("share", f"--share-to wants LOCALE=RUN, got {item!r}")
        if locale not in LOCALES:
            raise SetupError("share", f"--share-to locale must be one of {', '.join(LOCALES)}, got {locale!r}")
        if locale == primary_locale:
            raise SetupError("share", f"--share-to {locale} repeats the primary locale")
        if locale in shares:
            raise SetupError("share", f"--share-to {locale} given twice")
        target = resolve_run(value, repo)
        if target == primary_run:
            raise SetupError("share", f"--share-to {locale} points at the primary run")
        if target in shares.values():
            raise SetupError("share", f"--share-to {locale} repeats another share target")
        shares[locale] = target
    return shares


def needs_prepare(run: Path, force: bool) -> bool:
    if force:
        return True
    return not ((run / "clip.json").exists() and (run / "sentences.jsonl").exists())


def count_sentences(run: Path) -> int:
    path = run / "sentences.jsonl"
    if not path.exists():
        return 0
    return sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line.strip())


def clip_seconds(run: Path) -> float | None:
    path = run / "clip.json"
    if not path.exists():
        return None
    try:
        clip = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    if "mediaStart" in clip and "mediaEnd" in clip:
        return round(float(clip["mediaEnd"]) - float(clip["mediaStart"]), 3)
    return None


# --- environment checks -------------------------------------------------------

def _git_check(repo: Path) -> tuple[bool, str]:
    try:
        subprocess.run(["git", "fetch", "--quiet", "origin"], cwd=repo, capture_output=True, text=True,
                       timeout=120, check=False)
        proc = subprocess.run(["git", "rev-list", "--left-right", "--count", "origin/main...HEAD"],
                              cwd=repo, capture_output=True, text=True, timeout=60, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, f"git check unavailable: {exc}"
    counts = proc.stdout.split()
    if proc.returncode != 0 or len(counts) != 2:
        return False, f"git rev-list failed: {(proc.stderr or proc.stdout).strip()[:200]}"
    behind, ahead = int(counts[0]), int(counts[1])
    return behind == 0, f"behind origin/main {behind} commit(s), ahead {ahead}"


def _package_check(repo: Path) -> tuple[bool, str]:
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join([str(repo / "packages" / "production" / "src"), str(repo)])
    code = ("import pathlib, tongxing_production as m, jsonschema, google.auth; "
            "print(pathlib.Path(m.__file__).resolve())")
    try:
        proc = subprocess.run([sys.executable, "-c", code], cwd=repo, capture_output=True, text=True,
                              timeout=120, env=env, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, f"import check unavailable: {exc}"
    resolved = (proc.stdout.strip().splitlines() or [""])[-1]
    expected = (repo / "packages" / "production" / "src").resolve()
    if proc.returncode == 0 and resolved.startswith(str(expected)):
        return True, resolved
    return False, resolved or (proc.stderr.strip().splitlines() or ["import failed"])[-1][:300]


def env_checks(a, run: Path) -> tuple[list[dict], bool]:
    checks: list[dict] = []

    def add(name: str, ok: bool, detail: str, *, warning: bool = False) -> None:
        checks.append({"name": name, "status": "pass" if ok else ("warn" if warning else "fail"),
                       "detail": detail})

    missing = [name for name in REQUIRED_SCRIPTS if not (HERE / name).exists()]
    add("scripts", not missing,
        f"missing={missing}" if missing else f"{len(REQUIRED_SCRIPTS)} scripts present")
    for tool in ("ffmpeg", "ffprobe"):
        found = shutil.which(tool)
        add(f"tool:{tool}", bool(found), found or "not on PATH")
    if a.check_git:
        ok, detail = _git_check(ROOT)
        add("git", ok, detail, warning=True)
    if a.check_package or a.publish:
        ok, detail = _package_check(ROOT)
        if not ok:
            detail += ("; use .venv/bin/python or tools/ops/bootstrap_sentence_first_env.sh "
                       "(.venv-sfa) — system python3 has no jsonschema/google-auth")
        add("package", ok, detail, warning=False)
    if a.publish:
        add("english-package", bool(a.english_package),
            "given" if a.english_package else "publish planned but --english-package not given; "
                                              "the publish path needs the approved English package",
            warning=True)
    return checks, not any(c["status"] == "fail" for c in checks)


def validate_start(a, prepare_needed: bool) -> list[str]:
    errors: list[str] = []
    if prepare_needed:
        required = {"--anchor": a.anchor, "--media": a.media, "--window-start": a.window_start,
                    "--units": a.units}
        absent = [name for name, value in required.items() if value is None]
        if absent:
            errors.append("prepare_clip needs " + ", ".join(absent))
        if a.anchor is not None and not a.anchor.is_file():
            errors.append(f"--anchor not found: {a.anchor}")
        if a.media is not None and not a.media.is_file():
            errors.append(f"--media not found: {a.media}")
        if a.units is not None:
            try:
                parse_units(a.units)
            except SetupError as exc:
                errors.append(exc.message)
    if (a.segments is None) != (a.speaker_map is None):
        errors.append("give both --segments and --speaker-map, or neither")
    for flag, value in (("--segments", a.segments), ("--speaker-map", a.speaker_map),
                        ("--english-package", a.english_package)):
        if value is not None and not value.is_file():
            errors.append(f"{flag} not found: {value}")
    return errors


# --- steps --------------------------------------------------------------------

def run_step(cmd: list[str], step: str) -> str:
    proc = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
    if proc.returncode != 0:
        tail = " | ".join(((proc.stderr or proc.stdout).strip().splitlines() or ["no output"])[-6:])
        raise SetupError(step, f"exit {proc.returncode}: {tail}")
    return proc.stdout


def _json_line(output: str) -> dict:
    for line in reversed(output.strip().splitlines()):
        line = line.strip()
        if line.startswith("{"):
            try:
                return json.loads(line)
            except json.JSONDecodeError:
                continue
    return {}


def do_prepare(a, run: Path) -> dict:
    cmd = [sys.executable, str(HERE / "prepare_clip.py"),
           "--anchor", str(a.anchor), "--media", str(a.media),
           "--window-start", str(a.window_start), "--units", a.units,
           "--run", repo_relative(run), "--title", a.title or run.name,
           "--margin-before", str(a.margin_before), "--margin-after", str(a.margin_after),
           "--pad", str(a.pad)]
    return _json_line(run_step(cmd, "prepare"))


def do_assign(a, run: Path) -> dict:
    cmd = [sys.executable, str(HERE / "assign_speakers.py"), "--run", repo_relative(run),
           "--segments", str(a.segments), "--mapping", str(a.speaker_map),
           "--min-share", str(a.min_share)]
    if a.use_text:
        cmd.append("--use-text")
    if a.speaker_offset is not None:
        cmd += ["--offset", str(a.speaker_offset)]
    return _json_line(run_step(cmd, "speakers"))


def do_preflight(a, run: Path, *, locale: str, primary: bool) -> dict:
    cmd = [sys.executable, str(HERE / "preflight.py"), "--stage", "setup", "--require-decisions",
           "--run", repo_relative(run), "--locale", locale, "--registry", str(a.registry)]
    if primary:
        if a.english_package:
            cmd += ["--english-package", str(a.english_package)]
        if a.source_url:
            cmd += ["--source-url", a.source_url]
        if a.spark_session:
            cmd += ["--spark-session", a.spark_session]
        if a.firebase or a.publish:
            cmd.append("--firebase")
    proc = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
    try:
        result = json.loads(proc.stdout)
    except json.JSONDecodeError:
        tail = (proc.stderr or proc.stdout).strip()[:400]
        return {"status": "fail", "stage": "setup", "errors": [{"name": "preflight", "detail": tail}],
                "warnings": [], "checks": []}
    if proc.returncode != 0 and result.get("status") != "fail":
        result["status"] = "fail"
    return result


def share_run(source: Path, target: Path, *, force: bool = False) -> dict:
    # slices.json keeps the primary run's paths on purpose: the source audio lives there,
    # same as the manual copy in AGENTS.md §2.
    if target == source or source in target.parents:
        raise SetupError("share", f"share target must be outside the source run: {target}")
    if target.exists() and not target.is_dir():
        raise SetupError("share", f"share target is not a directory: {target}")
    for name in SHARE_FILES:
        if not (source / name).is_file():
            raise SetupError("share", f"source is missing {name}: {source}")
    slices = source / "slices"
    if not slices.is_dir():
        raise SetupError("share", f"source is missing slices/: {source}")
    if not (slices / "slices.json").is_file():
        raise SetupError("share", f"source is missing slices/slices.json: {source}")
    source_files = sorted(path.relative_to(slices) for path in slices.rglob("*") if path.is_file())
    if target.exists():
        if any((target / name).exists() for name in DOWNSTREAM_FILES) and not force:
            raise SetupError("share", f"{target} already has translations/review/speech; "
                                      "pass --force-share to overwrite the shared inputs")
        same = all((target / name).is_file() and filecmp.cmp(source / name, target / name, shallow=False)
                   for name in SHARE_FILES)
        dest_slices = target / "slices"
        dest_files = sorted(path.relative_to(dest_slices) for path in dest_slices.rglob("*") if path.is_file()) \
            if dest_slices.is_dir() else []
        same = same and dest_files == source_files and all(
            filecmp.cmp(slices / name, dest_slices / name, shallow=False) for name in source_files)
        if same:
            return {"status": "already-shared", "sentences": count_sentences(source),
                    "slices": sum(1 for name in source_files if name.suffix == ".wav")}
    target.mkdir(parents=True, exist_ok=True)
    for name in SHARE_FILES:
        shutil.copyfile(source / name, target / name)
    dest_slices = target / "slices"
    dest_slices.mkdir(parents=True, exist_ok=True)
    copied = 0
    for name in source_files:
        src, dest = slices / name, dest_slices / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        if dest.exists():
            if filecmp.cmp(src, dest, shallow=False):
                continue
            if not force:
                raise SetupError("share", f"{dest} differs; pass --force-share to overwrite")
        shutil.copyfile(src, dest)
        copied += 1
    return {"status": "shared", "sentences": count_sentences(source),
            "slices": sum(1 for name in source_files if name.suffix == ".wav"), "filesCopied": copied + len(SHARE_FILES)}


def build_plan(a, run: Path, shares: dict[str, Path], prepare_needed: bool) -> list[dict]:
    steps: list[dict] = [{"step": "env", "action": "check",
                          "detail": "scripts · ffmpeg/ffprobe" +
                                    (" · git" if a.check_git else "") +
                                    (" · package" if (a.check_package or a.publish) else "")}]
    steps.append({"step": "prepare", "action": "run" if prepare_needed else "skip",
                  "run": repo_relative(run),
                  "reason": "clip.json/sentences.jsonl missing" if prepare_needed else "already prepared"})
    if a.segments and a.speaker_map:
        steps.append({"step": "speakers", "action": "run", "run": repo_relative(run),
                      "detail": "assign_speakers.py" + (" --use-text" if a.use_text else "")})
    for locale, target in shares.items():
        steps.append({"step": "share", "action": "copy-if-needed", "locale": locale,
                      "run": repo_relative(target)})
    steps.append({"step": "gate", "action": "run",
                  "detail": "preflight.py --stage setup for " + ", ".join([a.locale, *shares])})
    steps.append({"step": "receipt", "action": "write", "path": repo_relative(run / "setup.json")})
    return steps


# --- journal and receipt ------------------------------------------------------

def journal_mark(run: Path, stage: str, event: str) -> None:
    try:
        if str(HERE) not in sys.path:
            sys.path.insert(0, str(HERE))
        from runlog import mark
        mark(run, stage, event)
    except Exception as exc:  # journaling is evidence, not a gate
        print(f"sfa: journal mark skipped ({stage}/{event}): {exc}", file=sys.stderr)


def write_receipt(run: Path, receipt: dict) -> None:
    try:
        (run / "setup.json").write_text(json.dumps(receipt, ensure_ascii=False, indent=1) + "\n",
                                        encoding="utf-8")
    except OSError as exc:
        print(f"sfa: could not write setup.json: {exc}", file=sys.stderr)


def emit(payload: dict, pretty: bool) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=1 if pretty else None))


def fail(step: str, message: str, run: Path | None = None) -> int:
    payload: dict = {"ok": False, "step": step, "error": message}
    if run is not None:
        payload["run"] = repo_relative(run)
    emit(payload, False)
    print(f"sfa: {step}: {message}", file=sys.stderr)
    return 1


# --- command ------------------------------------------------------------------

def _path(value: str) -> Path:
    return Path(value).expanduser().resolve()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    start = sub.add_parser("start", help="environment checks → prepare → speakers → share → setup gate",
                           description="Start one sentence-first run with one command.")
    start.add_argument("--run", required=True, help="run directory under artifacts/sentence-first-agent/")
    start.add_argument("--locale", required=True, choices=LOCALES, help="primary locale of --run")
    start.add_argument("--share-to", action="append", metavar="LOCALE=RUN",
                       help="repeatable: copy clip.json/sentences.jsonl/slices/ into that run")
    start.add_argument("--anchor", type=_path, help="anchor-manifest.json (v2) for prepare_clip")
    start.add_argument("--media", type=_path, help="source video or audio for prepare_clip")
    start.add_argument("--window-start", type=float, help="media seconds where anchor time 0 sits")
    start.add_argument("--units", help="inclusive anchor unit indices LO:HI")
    start.add_argument("--title", default="", help="one line for the run.md header")
    start.add_argument("--margin-before", type=float, default=1.0)
    start.add_argument("--margin-after", type=float, default=8.0)
    start.add_argument("--pad", type=float, default=0.08, help="slice padding, passed to slice_sentences.py")
    start.add_argument("--segments", type=_path, help="diarization segments.json (dual-speaker runs)")
    start.add_argument("--speaker-map", type=_path, help="speaker label mapping json")
    start.add_argument("--use-text", action="store_true", help="assign_speakers --use-text")
    start.add_argument("--min-share", type=float, default=0.8)
    start.add_argument("--speaker-offset", type=float, help="assign_speakers --offset (default: clip.json mediaStart)")
    start.add_argument("--english-package", type=_path, help="Layer 1 english-source.json for the gate")
    start.add_argument("--source-url", help="expected source URL (checked against sourceUrlHash)")
    start.add_argument("--registry", type=_path, default=(ROOT / "config" / "speaker-voice-registry.json"))
    start.add_argument("--spark-session", help="check this Spark exclusive session before starting work")
    decisions = start.add_mutually_exclusive_group(required=True)
    decisions.add_argument("--sync", action="store_true",
                           help="the dub follows the source video clock; the lag loop is mandatory")
    decisions.add_argument("--no-sync", action="store_true",
                           help="independent track at natural speech rate, no trimming")
    publishing = start.add_mutually_exclusive_group(required=True)
    publishing.add_argument("--publish", action="store_true",
                            help="a page will be published: also check the package import and Firebase ADC")
    publishing.add_argument("--no-publish", action="store_true",
                            help="review bundle only; no page will be published")
    start.add_argument("--form", choices=("full", "clip"), help="整期 or 片段, recorded in decisions.json")
    start.add_argument("--firebase", action="store_true", help="check Firebase ADC even without --publish")
    start.add_argument("--check-git", action="store_true", help="fetch origin and warn when behind origin/main")
    start.add_argument("--check-package", action="store_true",
                       help="verify tongxing_production resolves to this checkout (implied by --publish)")
    start.add_argument("--force-prepare", action="store_true", help="run prepare_clip even when clip.json exists")
    start.add_argument("--force-share", action="store_true",
                       help="overwrite a share target that already has downstream files or differing slices")
    start.add_argument("--plan", action="store_true", help="print the plan and run only read-only env checks")
    start.add_argument("--pretty", action="store_true", help="indent the JSON output (default: one line)")
    start.add_argument("--out", type=_path, help="also write the JSON output to this path")
    return parser


def main(argv=None) -> int:
    parser = build_parser()
    a = parser.parse_args(argv)
    started = time.monotonic()
    try:
        run = resolve_run(a.run)
        shares = parse_shares(a.share_to, a.locale, run)
    except SetupError as exc:
        return fail(exc.step, exc.message)
    prepare_needed = needs_prepare(run, a.force_prepare)

    if a.plan:
        checks, env_ok = env_checks(a, run)
        errors = validate_start(a, prepare_needed)
        payload = {"ok": env_ok and not errors, "plan": True, "run": repo_relative(run),
                   "primaryLocale": a.locale, "locales": [a.locale, *shares],
                   "steps": build_plan(a, run, shares, prepare_needed),
                   "decisions": {"form": a.form, "sync": bool(a.sync), "publish": bool(a.publish),
                                 "title": a.title or "", "windowStart": a.window_start, "units": a.units},
                   "gates": {"env": checks}}
        if errors:
            payload["errors"] = errors
        emit(payload, a.pretty)
        return 0 if payload["ok"] else 1

    journal_mark(run, "l1.start", "started")
    receipt: dict = {
        "schemaVersion": RECEIPT_SCHEMA,
        "ok": False,
        "at": utc_now(),
        "run": repo_relative(run),
        "primaryLocale": a.locale,
        "locales": [a.locale, *shares],
        "inputs": {"anchor": str(a.anchor) if a.anchor else None,
                   "media": str(a.media) if a.media else None,
                   "windowStart": a.window_start,
                   "units": a.units,
                   "segments": str(a.segments) if a.segments else None,
                   "speakerMap": str(a.speaker_map) if a.speaker_map else None,
                   "englishPackage": str(a.english_package) if a.english_package else None},
        "decisions": {"publish": bool(a.publish)},
        "gates": {},
        "elapsedSeconds": None,
    }
    try:
        checks, env_ok = env_checks(a, run)
        receipt["gates"]["env"] = checks
        if not env_ok:
            failed = [c["name"] for c in checks if c["status"] == "fail"]
            raise SetupError("env", "failed checks: " + ", ".join(failed))
        errors = validate_start(a, prepare_needed)
        if errors:
            raise SetupError("args", "; ".join(errors))

        prepared = False
        if prepare_needed:
            data = do_prepare(a, run)
            prepared = True
            sentences = int(data.get("sentences") or count_sentences(run))
            seconds = data.get("clipSeconds") if data.get("clipSeconds") is not None else clip_seconds(run)
        else:
            sentences = count_sentences(run)
            seconds = clip_seconds(run)
        receipt.update({"prepared": prepared, "sentences": sentences, "clipSeconds": seconds})

        if a.segments and a.speaker_map:
            receipt["speakers"] = do_assign(a, run) or None

        share_results: dict[str, dict] = {}
        for locale, target in shares.items():
            share_results[locale] = {"run": repo_relative(target),
                                     **share_run(run, target, force=a.force_share)}
        receipt["shares"] = share_results

        decisions = build_decisions(a, run, shares=shares, sentences=sentences, clip_seconds=seconds)
        write_json(run / "decisions.json", decisions)
        append_decisions_to_run_md(run, decisions)
        for target in shares.values():
            write_json(target / "decisions.json",
                       {**decisions, "run": repo_relative(target), "primaryRun": repo_relative(run)})
        receipt["decisions"] = decisions
        receipt["decisionsFile"] = repo_relative(run / "decisions.json")

        gate_results: dict[str, dict] = {}
        failures: list[str] = []
        for locale, target in [(a.locale, run), *shares.items()]:
            result = do_preflight(a, target, locale=locale, primary=(locale == a.locale))
            gate_results[locale] = {"status": result.get("status"),
                                    "errors": result.get("errors", []),
                                    "warnings": result.get("warnings", [])}
            if result.get("status") != "pass":
                failures.append(locale)
        receipt["gates"]["preflight"] = gate_results
        if failures:
            detail = []
            for locale in failures:
                for error in gate_results[locale]["errors"][:3]:
                    detail.append(f"{locale}/{error.get('name')}: {error.get('detail')}")
            raise SetupError("preflight", "setup gate failed for " + ", ".join(failures) +
                             (": " + " | ".join(detail) if detail else ""))
    except SetupError as exc:
        journal_mark(run, "l1.start", "failed")
        receipt.update({"ok": False, "step": exc.step, "error": exc.message,
                        "elapsedSeconds": round(time.monotonic() - started, 1)})
        write_receipt(run, receipt)
        return fail(exc.step, exc.message, run)

    journal_mark(run, "l1.start", "finished")
    receipt.update({"ok": True, "elapsedSeconds": round(time.monotonic() - started, 1),
                    "next": ["translate"] if a.english_package else ["english-review"]})
    write_receipt(run, receipt)
    preflight_summary = {locale: value["status"] for locale, value in receipt["gates"]["preflight"].items()}
    payload = {"ok": True, "run": receipt["run"], "primaryLocale": a.locale,
               "locales": receipt["locales"], "prepared": receipt["prepared"],
               "sentences": receipt["sentences"], "clipSeconds": receipt["clipSeconds"],
               "shares": {locale: value["status"] for locale, value in receipt.get("shares", {}).items()},
               "gates": {"env": "pass", "preflight": "pass" if all(v == "pass" for v in preflight_summary.values()) else "fail",
                         "preflightByLocale": preflight_summary},
               "elapsedSeconds": receipt["elapsedSeconds"], "next": receipt["next"],
               "receipt": repo_relative(run / "setup.json")}
    emit(payload, a.pretty)
    if a.out:
        try:
            a.out.write_text(json.dumps(payload, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        except OSError as exc:
            print(f"sfa: could not write --out: {exc}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
