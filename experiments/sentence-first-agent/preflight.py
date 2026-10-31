#!/usr/bin/env python3
"""Preflight a sentence-first run before Spark TTS or before the Production publish.

Checks the cheap, repeated failure modes from the 2026-10-23 full-episode run:

* run files and row-id consistency (sentences / translations / speech);
* ``speakerId -> speakerKey`` resolution against the speaker-voice Registry, the
  authorization purpose and the locale capability;
* every speech row's ``speaker`` equals the mapped checkpoint key;
* every evidence reference in an English source package resolves (relative paths are
  resolved against the repository root, not the current working directory);
* the run's ``sourceUnitId`` set is covered by the English package;
* optional: a checkpoint map, the Spark exclusive session and the Firebase ADC file.

Two stages share the same report:

* ``--stage full`` (default) checks a run that already has translations, review and
  speech; it is the gate before TTS or before a publish.
* ``--stage setup`` checks only what exists at 开工: ``clip.json`` and
  ``sentences.jsonl``, every assigned ``speakerId`` against the Registry (purpose and
  locale capability when ``--locale`` is given), the English package and the optional
  Spark/Firebase probes. It journals ``l1.preflight.setup`` so the later full run keeps
  ``l1.preflight``.

Usage:
  preflight.py --run artifacts/sentence-first-agent/<run> \
      [--stage full|setup] \
      --english-package artifacts/podcasts/<episode>/layer1-srt/english-source.json \
      [--checkpoint-map /path/to/speaker-checkpoints.dgx.json] \
      [--spark-session <name>] [--firebase]

Exit code 1 on any error; warnings do not fail.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_REGISTRY = ROOT / "config" / "speaker-voice-registry.json"
PURPOSES_BY_LOCALE = {"zh-Hans": {"chinese_dubbing", "multilingual_dubbing"},
                      "ko": {"multilingual_dubbing"}, "es": {"multilingual_dubbing"}}


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def json_sha(data) -> str:
    return hashlib.sha256(json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


def load_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def walk_refs(value, out: list[dict]) -> None:
    if isinstance(value, dict):
        if isinstance(value.get("path"), str) and isinstance(value.get("sha256"), str):
            out.append(value)
        for child in value.values():
            walk_refs(child, out)
    elif isinstance(value, list):
        for child in value:
            walk_refs(child, out)


class Report:
    def __init__(self):
        self.checks: list[dict] = []

    def add(self, name: str, ok: bool, detail: str, *, warning: bool = False) -> None:
        self.checks.append({"name": name, "status": "pass" if ok else ("warn" if warning else "fail"),
                            "detail": detail})

    def result(self) -> dict:
        errors = [c for c in self.checks if c["status"] == "fail"]
        warnings = [c for c in self.checks if c["status"] == "warn"]
        return {"status": "pass" if not errors else "fail", "errors": errors, "warnings": warnings,
                "checks": self.checks}


def check_run(run: Path, locale: str | None, registry_path: Path, report: Report) -> dict:
    ctx: dict = {}
    for name in ("clip.json", "sentences.jsonl", "translations.jsonl", "review.json", "speech.jsonl"):
        p = run / name
        report.add(f"file:{name}", p.exists(), str(p))
        if not p.exists():
            return ctx
    clip = json.loads((run / "clip.json").read_text(encoding="utf-8"))
    sentences = load_jsonl(run / "sentences.jsonl")
    translations = load_jsonl(run / "translations.jsonl")
    speech = load_jsonl(run / "speech.jsonl")
    review = json.loads((run / "review.json").read_text(encoding="utf-8"))
    locale = locale or review.get("locale") or clip.get("locale")
    ctx.update({"locale": locale, "clip": clip, "sentences": sentences, "review": review, "speech": speech})
    report.add("locale", bool(locale), f"locale={locale}")
    sids = [s["id"] for s in sentences]
    tids = [t["id"] for t in translations]
    pids = [s["id"] for s in speech]
    report.add("rows:translations", set(tids) == set(sids), f"{len(tids)} translation rows vs {len(sids)} sentences")
    report.add("rows:speech", set(pids) == set(sids), f"{len(pids)} speech rows vs {len(sids)} sentences")
    report.add("rows:unique", len(set(sids)) == len(sids), f"{len(sids)} unique sentence ids")

    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    speakers = {s["speakerId"]: s for s in registry.get("speakers", [])}
    mapping = review.get("speakers") or {}
    if review.get("speaker") and not mapping:
        mapping = {next((s["speakerId"] for s in sentences if s.get("speakerId")), "unknown"): review["speaker"]}
    report.add("review:speakers", bool(mapping), f"mapping={mapping}")
    for speaker_id, speaker_key in mapping.items():
        entry = speakers.get(speaker_id)
        report.add(f"registry:{speaker_id}", entry is not None, "present" if entry else "missing speakerId")
        if not entry:
            continue
        report.add(f"key:{speaker_id}", entry.get("speakerKey") == speaker_key,
                   f"registry={entry.get('speakerKey')} review={speaker_key}")
        purposes = set(entry.get("authorization", {}).get("purposes", []))
        allowed = PURPOSES_BY_LOCALE.get(locale, {"multilingual_dubbing"})
        report.add(f"purpose:{speaker_id}", bool(purposes & allowed),
                   f"purposes={sorted(purposes)} locale={locale}")
        caps = [c for c in entry.get("localeCapabilities", []) if c.get("targetLocale") == locale]
        report.add(f"capability:{speaker_id}:{locale}", bool(caps),
                   f"status={caps[0].get('status') if caps else None}")
        if caps and caps[0].get("status") != "human_reviewed":
            report.add(f"capability-status:{speaker_id}:{locale}", False,
                       f"status={caps[0].get('status')} (warn only; publish requires human_reviewed)", warning=True)
    # Every speech row must carry the mapped checkpoint key, not the speakerId.
    bad = [s["id"] for s in speech if s.get("speaker") not in set(mapping.values())]
    report.add("speech:speaker-keys", not bad, f"bad={bad[:5]} count={len(bad)}")
    wrong = [s["id"] for s in speech if s.get("language") != "Chinese" and locale == "zh-Hans"] if locale == "zh-Hans" else []
    report.add("speech:language", not wrong, f"wrong={wrong[:5]} count={len(wrong)}")
    ctx["mapping"] = mapping
    return ctx


def check_run_setup(run: Path, locale: str | None, registry_path: Path, report: Report) -> dict:
    """Checks that are possible right after prepare_clip/assign_speakers, before translation."""
    ctx: dict = {}
    for name in ("clip.json", "sentences.jsonl"):
        p = run / name
        report.add(f"file:{name}", p.exists(), str(p))
        if not p.exists():
            return ctx
    clip = json.loads((run / "clip.json").read_text(encoding="utf-8"))
    sentences = load_jsonl(run / "sentences.jsonl")
    locale = locale or clip.get("locale")
    ctx.update({"locale": locale, "clip": clip, "sentences": sentences})
    report.add("locale", bool(locale), f"locale={locale}")
    sids = [s["id"] for s in sentences]
    report.add("rows:sentences", bool(sids), f"{len(sids)} sentences")
    report.add("rows:unique", len(set(sids)) == len(sids), f"{len(sids)} unique sentence ids")
    missing_units = [s["id"] for s in sentences if not s.get("sourceUnitId")]
    report.add("sentences:source-unit-id", not missing_units,
               f"missing={missing_units[:5]} count={len(missing_units)}")
    speaker_ids = sorted({s["speakerId"] for s in sentences if s.get("speakerId")})
    if not speaker_ids:
        report.add("speakers:assigned", True, "no speakerId yet (single voice or assign_speakers not run)", warning=True)
        return ctx
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    speakers = {s["speakerId"]: s for s in registry.get("speakers", [])}
    for speaker_id in speaker_ids:
        entry = speakers.get(speaker_id)
        report.add(f"registry:{speaker_id}", entry is not None, "present" if entry else "missing speakerId")
        if not entry:
            continue
        report.add(f"key:{speaker_id}", bool(entry.get("speakerKey")), f"speakerKey={entry.get('speakerKey')}")
        if not locale:
            continue
        purposes = set(entry.get("authorization", {}).get("purposes", []))
        allowed = PURPOSES_BY_LOCALE.get(locale, {"multilingual_dubbing"})
        report.add(f"purpose:{speaker_id}", bool(purposes & allowed),
                   f"purposes={sorted(purposes)} locale={locale}")
        caps = [c for c in entry.get("localeCapabilities", []) if c.get("targetLocale") == locale]
        report.add(f"capability:{speaker_id}:{locale}", bool(caps),
                   f"status={caps[0].get('status') if caps else None}")
        if caps and caps[0].get("status") != "human_reviewed":
            report.add(f"capability-status:{speaker_id}:{locale}", False,
                       f"status={caps[0].get('status')} (warn only; publish requires human_reviewed)", warning=True)
    return ctx


def check_english_package(package_path: Path, ctx: dict, report: Report, root: Path = ROOT,
                          source_url: str | None = None) -> None:
    if not package_path.exists():
        report.add("english:package", False, str(package_path))
        return
    data = json.loads(package_path.read_text(encoding="utf-8"))
    refs: list[dict] = []
    walk_refs(data, refs)
    report.add("english:refs-found", bool(refs), f"{len(refs)} evidence refs (base={root})")
    seen = set()
    for ref in refs:
        raw = ref["path"]
        path = Path(raw) if Path(raw).is_absolute() else root / raw
        key = (str(path), ref["sha256"])
        if key in seen:
            continue
        seen.add(key)
        if not path.exists():
            report.add(f"english:ref:{raw}", False,
                       f"missing; resolved to {path} (cwd={Path.cwd()})")
            continue
        if sha256(path) != ref["sha256"]:
            report.add(f"english:ref:{raw}", False, f"file sha mismatch: {path}")
            continue
        if ref.get("jsonSha256"):
            try:
                if json_sha(json.loads(path.read_text(encoding="utf-8"))) != ref["jsonSha256"]:
                    report.add(f"english:ref:{raw}", False, f"json sha mismatch: {path}")
                    continue
            except (json.JSONDecodeError, UnicodeDecodeError):
                report.add(f"english:ref:{raw}", False, f"not readable JSON: {path}")
                continue
        report.add(f"english:ref:{raw}", True, "resolved and hashed")
    # The package stores the units in the anchor manifest referenced by anchors.artifact;
    # fall back to a top-level list for simple packages.
    units = data.get("sourceUnits") or data.get("units") or []
    anchor_ref = (data.get("anchors") or {}).get("artifact")
    if not units and isinstance(anchor_ref, dict) and anchor_ref.get("path"):
        ap = Path(anchor_ref["path"]) if Path(anchor_ref["path"]).is_absolute() else root / anchor_ref["path"]
        if ap.exists():
            units = json.loads(ap.read_text(encoding="utf-8")).get("sourceUnits", [])
    package_ids = {u.get("sourceUnitId") for u in units}
    run_ids = {s.get("sourceUnitId") for s in ctx.get("sentences", [])}
    missing = run_ids - package_ids
    report.add("english:unit-coverage", bool(units) and not missing,
               f"missing={sorted(missing)[:5]} count={len(missing)} units={len(units)}")
    if isinstance(data.get("anchors"), dict) and data["anchors"].get("sourceUnitCount"):
        report.add("english:unit-count", len(units) == data["anchors"]["sourceUnitCount"],
                   f"manifest={len(units)} package={data['anchors']['sourceUnitCount']}")
    source = data.get("source") or {}
    url = source.get("sourceUrl") or source.get("url")
    url_hash = source.get("sourceUrlHash")
    if source_url and url_hash:
        expected = hashlib.sha256(source_url.encode("utf-8")).hexdigest()
        report.add("english:source-url", expected == url_hash, f"hash match={expected == url_hash}")
    else:
        report.add("english:source-url", bool(url or url_hash), str(url or url_hash))
    review = data.get("review") or {}
    if "humanApproval" in review:
        report.add("english:human-approval", bool(review["humanApproval"]), f"humanApproval={review['humanApproval']}")
    else:
        report.add("english:human-approval", False, "review.humanApproval absent", warning=True)
    if "translationEligible" in data:
        report.add("english:translation-eligible", bool(data["translationEligible"]),
                   f"translationEligible={data['translationEligible']}")
    else:
        report.add("english:translation-eligible", False, "translationEligible absent", warning=True)


def check_checkpoint_map(path: Path, ctx: dict, report: Report) -> None:
    if not path.exists():
        report.add("checkpoints:map", False, str(path))
        return
    data = json.loads(path.read_text(encoding="utf-8"))
    # Accept either {"<speakerKey>": {"path": ...}} or the speaker-checkpoints file shape.
    by_key = {}
    if isinstance(data, dict):
        for key, value in data.items():
            if isinstance(value, dict):
                by_key[key] = value.get("path") or value.get("checkpointPath")
            elif isinstance(value, str):
                by_key[key] = value
    for speaker_key in set((ctx.get("mapping") or {}).values()):
        found = by_key.get(speaker_key)
        report.add(f"checkpoints:{speaker_key}", bool(found), str(found))
        if found:
            report.add(f"checkpoints:{speaker_key}:local", Path(found).exists(),
                       f"{found} (warn only; the Spark path is checked on the host)", warning=not Path(found).exists())


def check_spark(session: str, report: Report) -> None:
    cli = ROOT / "packages" / "production" / "src" / "tongxing_production" / "compute" / "spark_exclusive_session.py"
    if not cli.exists():
        report.add("spark:session", False, f"missing {cli}", warning=True)
        return
    env = dict(os.environ)
    env["PYTHONPATH"] = f"{ROOT / 'packages' / 'production' / 'src'}:{ROOT}"
    try:
        proc = subprocess.run([sys.executable, str(cli), "status", "--session-id", session,
                               "--owner", "sentence-first-agent"], capture_output=True, text=True, timeout=30, env=env)
    except (OSError, subprocess.TimeoutExpired) as exc:
        report.add("spark:session", False, f"{exc}", warning=True)
        return
    out = (proc.stdout or "").strip()
    report.add("spark:session", proc.returncode == 0, f"rc={proc.returncode} out={out[:200]}",
               warning=proc.returncode != 0)


def check_firebase(report: Report) -> None:
    adc = Path(os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", Path.home() / ".config/gcloud/application_default_credentials.json"))
    report.add("firebase:adc", adc.exists(), str(adc), warning=not adc.exists())


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--run", type=Path, required=True)
    p.add_argument("--stage", choices=("full", "setup"), default="full",
                   help="full: translations/review/speech exist; setup: only clip.json and sentences.jsonl (default: full)")
    p.add_argument("--locale", choices=("zh-Hans", "ko", "es"))
    p.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    p.add_argument("--english-package", type=Path)
    p.add_argument("--checkpoint-map", type=Path)
    p.add_argument("--spark-session")
    p.add_argument("--firebase", action="store_true")
    p.add_argument("--repo-root", type=Path, default=ROOT, help="base for relative evidence paths (default: this checkout)")
    p.add_argument("--source-url", help="expected source URL; checked against source.sourceUrlHash when both are given")
    p.add_argument("--out", type=Path)
    a = p.parse_args(argv)
    report = Report()
    journal = a.run.exists()
    stage = "l1.preflight" if a.stage == "full" else "l1.preflight.setup"
    if journal:
        _mark(a.run, stage, "started")
    ctx = check_run(a.run, a.locale, a.registry, report) if a.stage == "full" \
        else check_run_setup(a.run, a.locale, a.registry, report)
    if a.english_package:
        check_english_package(a.english_package, ctx, report, a.repo_root, a.source_url)
    if a.checkpoint_map:
        check_checkpoint_map(a.checkpoint_map, ctx, report)
    if a.spark_session:
        check_spark(a.spark_session, report)
    if a.firebase:
        check_firebase(report)
    result = report.result()
    result["stage"] = a.stage
    if journal:
        _mark(a.run, stage, "finished" if result["status"] == "pass" else "failed")
    print(json.dumps(result, ensure_ascii=False, indent=1))
    if a.out:
        a.out.write_text(json.dumps(result, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return 0 if result["status"] == "pass" else 1


def _mark(run, stage: str, event: str) -> None:
    try:
        from runlog import mark
    except ImportError:
        import sys as _sys
        _sys.path.insert(0, str(Path(__file__).resolve().parent))
        from runlog import mark
    mark(run, stage, event)


if __name__ == "__main__":
    raise SystemExit(main())
