#!/usr/bin/env python3
"""Run the machine-QC text path on an existing Dev run with local models.

Test driver for the fixed three-minute clip (``artifacts/dev-full-rerun-20261001``)
or any earlier run that already has a model-reviewed Layer 2 candidate. For each
locale it:

1. finds the candidate, and the English source package, anchor and translation
   policy it binds, by canonical JSON hash (no assumptions about the run layout);
2. checks, without model calls, that the candidate can carry a waiver and which
   seeded error kinds this text can calibrate at all;
3. screens the candidate (deterministic checks + back-translation) from the
   text repair ledger head and appends the receipt to that ledger;
4. calibrates on the same groups with seeded errors;
5. issues the text waiver (``machine_quality_release_basis.build_text_waiver``).

``--spoken-binding LOCALE=BINDING`` screens a condensed spoken script instead:
the spoken candidate, full candidate and condensation record are found by the
hashes the binding names (``spoken_condensation.py bind``), the binding is
recomputed from them with the current code, condensed groups are judged by the
core-meaning rubric (``spoken_condensation.qc_groups``), the calibration adds
the ``spoken.*`` kinds on the condensed groups and binds both candidates, and
the waiver carries the binding. A record from the fake condenser is refused
unless the judge is fake too. Spoken outputs go under ``OUT/LOCALE/spoken``.
The spoken script shares its locale's text repair ledger with the full
candidate (the ledger counts per English unit), so screening one appends an
entry that the other's next run starts from.

The back-translation transport is the local Codex CLI under ChatGPT login
(``sermon_codex_transport``, Sol 6.1 medium); no API key is used. Every call is
cached by request and transport identity under the state dir, so a rerun reuses finished calls, and
independent calls are prefetched in parallel. ``--text-backend fake`` replaces
the model with an echo judge for plumbing tests only: it builds the waiver in
memory to prove the path, never saves one, and its receipts name the fake backend.

QC receipts are kept per repair ledger entry beside the ledger in the state dir;
calibrations and waivers are written once under names derived from their inputs,
so a revision adds files and never replaces evidence an earlier waiver binds.
Wall time per stage goes to ``timings.tsv``; ``summary.json`` records each
locale's outcome. The run never publishes and never marks anything human approved.
"""
from __future__ import annotations

import argparse
import fcntl
import hashlib
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts import auto_qc_seeded_errors as seeded
from scripts import machine_quality_release_basis as basis
from scripts import machine_repair_ledger as ledger
from scripts import prepare_target_language_speech_job as speech
from scripts import spoken_condensation as condensation
from scripts import target_text_auto_qc as text_qc

# Output directories of this invocation, for the exit-time run report.
REPORT_DIRS: list[Path] = []

ROOT = Path(__file__).resolve().parents[1]
LOCALES = ("zh-Hans", "ko", "es")
MAX_WORKERS = 8  # Codex CLI calls this driver may run at once
CANDIDATE_SCHEMA_PREFIX = "sermon-target-language-candidate"
CANDIDATE_SCHEMA = "sermon-target-language-candidate-v2"  # the version the waiver path accepts
CACHE_NAMESPACE = "machine-qc-clip-test-v1"
PENDING = "__prefetch_pending__"
json_sha256 = basis.json_sha256


class Timings:
    def __init__(self, path: Path):
        self.path = path
        if not path.exists():
            path.write_text("stage\tstatus\tseconds\n", encoding="utf-8")

    def run(self, name: str, function):
        started = time.monotonic()
        try:
            value = function()
        except Exception:
            self._row(name, "fail", started)
            raise
        self._row(name, "pass", started)
        return value

    def _row(self, name, status, started):
        line = f"{name}\t{status}\t{time.monotonic() - started:.1f}\n"
        with self.path.open("a", encoding="utf-8") as stream:
            stream.write(line)
        print(line, end="", flush=True)


def save(path: Path, value) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)
    return path


def read(path: Path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


# ---------------------------------------------------------------- discovery

def index_run(run_dir: Path, max_bytes: int = 20 * 1024 * 1024) -> dict[str, list[Path]]:
    """Canonical JSON hash -> files with that content, for every JSON file in the run."""
    found: dict[str, list[Path]] = {}
    for path in sorted(Path(run_dir).rglob("*.json")):
        if not path.is_file() or path.stat().st_size > max_bytes:
            continue
        try:
            value = read(path)
        except (ValueError, UnicodeDecodeError):
            continue
        found.setdefault(json_sha256(value), []).append(path)
    return found


def spoken_candidates(run_dir: Path) -> set[str]:
    """Hashes of spoken (condensed) candidates that a condensation binding in the run names."""
    found = set()
    for path in sorted(Path(run_dir).rglob("*.json")):
        try:
            value = read(path)
        except (ValueError, UnicodeDecodeError, OSError):
            continue
        if isinstance(value, dict) and value.get("schemaVersion") == basis.CONDENSATION_BINDING_SCHEMA:
            found.add(value.get("spokenCandidateJsonSha256"))
    return found


def find_candidate(run_dir: Path, locale: str, override: Path | None) -> tuple[Path | None, list[str]]:
    if override is not None:
        return override, []
    matches = []
    for path in sorted(Path(run_dir).rglob("*.json")):
        try:
            value = read(path)
        except (ValueError, UnicodeDecodeError, OSError):
            continue
        if (isinstance(value, dict) and str(value.get("schemaVersion", "")).startswith(CANDIDATE_SCHEMA_PREFIX)
                and value.get("targetLocale") == locale and value.get("groups")):
            matches.append(path)
    if len(matches) == 1:
        return matches[0], []
    pending = [path for path in matches if basis.machine_pending_candidate(read(path))]
    if len(pending) == 1:
        return pending[0], []
    preferred = [path for path in (pending or matches) if f"diagnostic-previews/{locale}/" in path.as_posix()]
    if len(preferred) == 1:
        return preferred[0], []
    return None, [str(path) for path in matches]


def candidate_problems(candidate: dict) -> list[str]:
    """Why ``machine_pending_candidate`` refuses this candidate, in words."""
    if basis.machine_pending_candidate(candidate):
        return []
    problems = []
    if candidate.get("status") != basis.MACHINE_PENDING_CANDIDATE:
        problems.append(f"status is {candidate.get('status')!r}, not {basis.MACHINE_PENDING_CANDIDATE!r}")
    if candidate.get("releaseEligible") is not False:
        problems.append("releaseEligible is not false")
    if (candidate.get("humanReview") or {}).get("translation") != "pending":
        problems.append("humanReview.translation is not pending")
    model = candidate.get("modelReview") or {}
    ids = [group.get("translationGroupId") for group in candidate.get("groups") or []]
    if model.get("status") != "pass" or model.get("reviewedGroupIds") != ids:
        problems.append("modelReview did not pass every group")
    bad = [group.get("translationGroupId") for group in candidate.get("groups") or []
           if not basis._semantic_pass(group.get("semanticReview"))]
    if bad:
        problems.append(f"semanticReview not clean in {len(bad)} group(s): {bad[:5]}")
    language = [group.get("translationGroupId") for group in candidate.get("groups") or []
                if (group.get("languageReview") or {}).get("status") != "pass"
                or not all(check.get("status") == "pass" for check in (group.get("languageReview") or {}).get("checks") or [])]
    if language:
        problems.append(f"languageReview not passing in {len(language)} group(s): {language[:5]}")
    return problems or ["candidate is not machine-review pending"]


def qc_groups(candidate: dict, anchor: dict) -> list[dict]:
    english = {unit["sourceUnitId"]: unit["english"] for unit in anchor["sourceUnits"]}
    return [{"groupId": group["translationGroupId"],
             "english": " ".join(english[unit_id] for unit_id in group["sourceUnitIds"]),
             "targetText": group["targetText"], "sourceUnitIds": group["sourceUnitIds"]}
            for group in candidate["groups"]]


def candidate_validator():
    from jsonschema import Draft202012Validator, FormatChecker
    schema = read(ROOT / "schemas" / f"{CANDIDATE_SCHEMA}.schema.json")
    return Draft202012Validator(schema, format_checker=FormatChecker())


def calibration_coverage(groups: list[dict], locale: str, policy: dict | None,
                         spoken_groups: list[dict] | None = None) -> dict:
    """Seeded error kinds this text can carry; a kind with no trial blocks any waiver.

    ``spoken_groups`` (a spoken script's QC groups) add the ``spoken.*`` kinds,
    seeded only into its condensed groups."""
    counts = {kind: sum(1 for group in groups
                        if seeded.mutate_text(group, kind, locale, policy, groups) not in (None, group["targetText"]))
              for kind in seeded.TEXT_KINDS}
    if spoken_groups is not None:
        counts.update({f"spoken.{kind}": sum(
            1 for group in spoken_groups if group.get("condensation")
            and seeded.mutate_spoken(group, kind, locale, spoken_groups) not in (None, group["targetText"]))
            for kind in seeded.SPOKEN_KINDS})
    return {"applicableGroups": counts, "untestableKinds": [kind for kind, count in counts.items() if not count]}


def resolve_spoken(index: dict, binding_file: Path, override: Path | None,
                   allow_fake_condenser: bool = False) -> tuple[dict, list[str]]:
    """The spoken candidate, full candidate and record a condensation binding names,
    and why they cannot be screened. ``index`` covers the run and the binding's folder."""
    binding = read(binding_file)
    paths, problems = {"condensationBinding": str(binding_file)}, []
    if binding.get("schemaVersion") != basis.CONDENSATION_BINDING_SCHEMA or binding.get("status") != "pass":
        return paths, ["condensation binding is not a passing spoken_condensation binding"]
    for name, key in (("candidate", "spokenCandidateJsonSha256"), ("fullCandidate", "fullCandidateJsonSha256"),
                      ("condensationRecord", "condensationRecordJsonSha256")):
        hits = [override] if name == "candidate" and override is not None else index.get(binding.get(key) or "", [])
        if hits:
            paths[name] = str(hits[0])
        else:
            problems.append(f"no {name} file in the run or beside the binding matches its {key}")
    if problems:
        return paths, problems
    record = read(Path(paths["condensationRecord"]))
    if not allow_fake_condenser and str((record.get("condenserIdentity") or {}).get("backend", "")).startswith("fake"):
        problems.append("condensation record came from the fake condenser; condense with a real model")
    return paths, problems


def resolve_locale(run_dir: Path, index: dict, locale: str, override: Path | None,
                   spoken_binding: Path | None = None, allow_fake_condenser: bool = False) -> dict:
    """Paths and blocking problems for one locale, without model calls."""
    spoken_paths: dict = {}
    if spoken_binding is not None:
        # The binding may sit outside the run, beside the record and candidates it binds.
        index = {**index_run(spoken_binding.parent), **index}
        spoken_paths, problems = resolve_spoken(index, spoken_binding, override, allow_fake_condenser)
        if problems:
            return {"locale": locale, "mode": "spoken", "paths": spoken_paths, "problems": problems}
        path = Path(spoken_paths["candidate"])
    else:
        path, ambiguous = find_candidate(run_dir, locale, override)
        if path is None:
            return {"locale": locale, "problems": [f"no unique candidate; found {len(ambiguous)}: {ambiguous[:6]}"]}
    candidate = read(path)
    problems = candidate_problems(candidate)
    if candidate.get("schemaVersion") != CANDIDATE_SCHEMA:
        problems.append(f"candidate schemaVersion is {candidate.get('schemaVersion')!r}, not {CANDIDATE_SCHEMA!r}")
    else:
        # Layer 3 validates the full package, so a candidate it would refuse never reaches paid QC.
        errors = sorted(candidate_validator().iter_errors(candidate), key=lambda error: list(error.absolute_path))
        problems += [f"candidate schema: {'/'.join(map(str, error.absolute_path)) or '<root>'}: {error.message}"
                     for error in errors[:5]]
    if candidate.get("targetLocale") != locale:
        problems.append(f"candidate targetLocale is {candidate.get('targetLocale')!r}, not {locale!r}")
    # An override may sit outside the run with its binding beside it.
    spoken = spoken_candidates(run_dir) | (spoken_candidates(path.parent) if override is not None else set())
    if spoken_binding is None and json_sha256(candidate) in spoken:
        # A condensed dub script is screened with its binding, never as full text.
        problems.append("candidate is a condensed spoken script; screen it with --spoken-binding")
    paths = {**spoken_paths, "candidate": str(path)}
    for name, key in (("source", "englishSourcePackageJsonSha256"), ("anchor", "anchorManifestSha256"),
                      ("policy", "translationPolicySha256")):
        hits = index.get(candidate.get(key) or "", [])
        if hits:
            paths[name] = str(hits[0])
        else:
            problems.append(f"no {name} file in the run matches candidate {key}")
    if "source" in paths and "anchor" in paths:
        source, anchor = read(Path(paths["source"])), read(Path(paths["anchor"]))
        if ((source.get("anchors") or {}).get("artifact") or {}).get("jsonSha256") != json_sha256(anchor):
            problems.append("source package does not bind the candidate's anchor")
        covered = [unit_id for group in candidate["groups"] for unit_id in group.get("sourceUnitIds") or []]
        if covered != [unit["sourceUnitId"] for unit in anchor["sourceUnits"]]:
            problems.append("candidate groups do not cover every anchor unit once, in order")
    if "source" in paths and "anchor" in paths:
        # The same source and anchor checks Layer 3 applies, before any paid call.
        try:
            speech.validate_target_candidate(read(Path(paths["source"])), read(Path(paths["anchor"])),
                                             candidate, require_human_approval=False)
        except (ValueError, KeyError, TypeError) as error:
            problems.append(f"Layer 3 would refuse this candidate: {error}")
    if spoken_binding is not None and "anchor" in paths and "policy" in paths:
        # The binding is recomputed with the current code, so an obsolete or edited one never reaches paid QC.
        try:
            rebound = condensation.bind_spoken_candidate(
                read(Path(paths["condensationRecord"])), read(Path(paths["anchor"])),
                read(Path(paths["fullCandidate"])), candidate, read(Path(paths["policy"])))
        except (ValueError, KeyError, TypeError) as error:
            problems.append(f"condensation binding cannot be recomputed: {error}")
        else:
            if rebound != read(spoken_binding):
                problems.append("condensation binding differs from one recomputed by the current code; rebind")
    return {"locale": locale, **({"mode": "spoken"} if spoken_binding is not None else {}), "paths": paths,
            "candidateJsonSha256": json_sha256(candidate), "problems": problems}


def binding_path(path: Path) -> Path:
    return path.with_name(path.stem + ".inputs.json")


def fresh(path: Path, binding: str) -> bool:
    """A saved receipt made from exactly these inputs."""
    marker = binding_path(path)
    return path.exists() and marker.exists() and read(marker).get("inputsSha256") == binding


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save_once(path: Path, value, binding: str) -> Path:
    """Write an immutable receipt and its input marker; an existing receipt is never replaced."""
    # The marker goes first: a receipt never exists without the hash it must keep.
    save(binding_path(path), {"inputsSha256": binding, "receiptJsonSha256": json_sha256(value)})
    # A complete temporary file is linked into place, so the receipt is never partial,
    # and the link fails rather than replace an existing receipt.
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.",
                                     suffix=".tmp", delete=False) as stream:
        stream.write(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    temporary = Path(stream.name)
    try:
        os.link(temporary, path)
    finally:
        temporary.unlink()
    return path


def load_once(path: Path, binding: str):
    """The immutable receipt at ``path`` if it was made from ``binding`` and is unchanged, else None."""
    if not fresh(path, binding):
        return None
    value = read(path)
    if json_sha256(value) != read(binding_path(path)).get("receiptJsonSha256"):
        raise ValueError(f"{path} changed after it was written")
    return value


def qc_receipt_path(state: Path, lineage: dict, sequence: int) -> Path:
    """One immutable QC receipt per repair ledger entry, kept with the ledger in the state dir."""
    return ledger.directory(state / "qc-receipts", lineage) / f"entry-{sequence:06d}.json"


# ---------------------------------------------------------------- transports

class CodexJudge:
    """``call(role, system, user, schema)`` through the local Codex CLI, cached per request."""

    def __init__(self, cache: Path, *, timeout_seconds: int = 300, reasoning: str = "medium",
                 cache_namespace: str = CACHE_NAMESPACE):
        # Back-translation uses Sol medium; another role (the spoken condenser uses
        # Sol high) names its own effort and namespace, so its identity and cache differ.
        from scripts import sermon_codex_transport as codex
        self.codex, self.cache, self.timeout, self.reasoning = codex, cache, timeout_seconds, reasoning
        cli = Path(os.environ.get("SERMON_CODEX_CLI", str(Path.home() / ".local/bin/codex"))).resolve()
        version = subprocess.check_output([str(cli), "--version"], text=True, timeout=15).strip()
        binary = cli.parent.parent / "CodexCLI.app/Contents/MacOS/codex"
        # The same implementation hashes the transport records, so a changed CLI
        # binary or adapter is a new identity and never reuses cached responses.
        transport = {"cliSha256": file_sha256(cli), "binarySha256": file_sha256(binary if binary.is_file() else cli),
                     "adapterSha256": file_sha256(Path(codex.__file__))}
        self.identity = {"backend": "codex_cli_chatgpt", "model": codex.TEXT_MODEL, "modelRevision": version,
                         "cacheNamespace": cache_namespace,
                         "settings": {"reasoningEffort": reasoning, "serviceTier": "fast",
                                      "promptFormat": "system-user-json-v1", "transport": transport}}

    def key(self, role, system, user, schema) -> str:
        return json_sha256({"role": role, "system": system, "user": user, "schema": schema,
                            "identity": self.identity})

    def cached(self, role, system, user, schema):
        # A saved response is read back through the transport, which checks its
        # identity, completion outcome and schema and raises on an unconfirmed call.
        response = self.cache / self.key(role, system, user, schema) / "response.json"
        return self(role, system, user, schema) if response.exists() else None

    def uncertain(self) -> list[str]:
        """Calls that started but never recorded a completed response: their outcome is unknown."""
        def settled(call: Path) -> bool:
            # A response counts only with its completed outcome; the transport writes them in turn.
            # A known rejection is settled too: it fails its own locale, not the run.
            try:
                status = read(call / "outcome.json").get("status")
            except (OSError, ValueError):
                return False
            return status == "rejected_response" or (status == "completed" and (call / "response.json").exists())
        return sorted(path.parent.name for path in self.cache.glob("*/started.json") if not settled(path.parent))

    def __call__(self, role, system, user, schema):
        prompt = f"SYSTEM:\n{system}\n\nUSER:\n{user}"
        return self.codex.call_json(prompt, model=self.codex.TEXT_MODEL, reasoning=self.reasoning,
                                    output_schema=schema, timeout_seconds=self.timeout,
                                    output_dir=self.cache / self.key(role, system, user, schema))


class FakeJudge:
    """Plumbing-only judge: back-translation is exact for the clean texts it was given.

    Its runs never save a waiver: ``run_locale`` only proves one could be built."""

    def __init__(self, groups_by_locale: dict[str, list[dict]]):
        self.clean = {group["targetText"]: group["english"] for groups in groups_by_locale.values() for group in groups}
        self.identity = {"backend": "fake-echo-not-evidence", "model": "fake-judge", "modelRevision": "0",
                         "cacheNamespace": CACHE_NAMESPACE, "settings": {"fake": True}}

    def cached(self, *request):
        return self(*request)

    def uncertain(self) -> list[str]:
        return []

    def __call__(self, role, system, user, schema):
        if role == "back_translator":
            return {"english": self.clean.get(user, "A different passage.")}
        pair = json.loads(user)
        if pair["ORIGINAL"] == pair["BACK-TRANSLATION"]:
            return {"status": "pass", "issues": []}
        return {"status": "fail", "issues": [{"kind": "meaning_shift", "severity": "major",
                                              "english": pair["ORIGINAL"], "backTranslation": pair["BACK-TRANSLATION"]}]}


def prefetch(judge, run, *, workers: int) -> int:
    """Issue every model request ``run(call)`` will make, in parallel, before the real run.

    ``run`` is deterministic in its inputs, so rounds of a recording call find
    the back-translations first, then the comparisons that depend on them."""
    issued = 0
    while True:
        wanted = {}

        def record(role, system, user, schema):
            done = judge.cached(role, system, user, schema)
            if done is not None:
                return done
            if PENDING not in user:
                wanted[judge.key(role, system, user, schema)] = (role, system, user, schema)
            return {"english": PENDING} if role == "back_translator" else {"status": "pass", "issues": []}

        run(record)
        if not wanted:
            return issued
        # After any failure nothing new is dispatched; calls already running finish and keep their receipts.
        failed = threading.Event()

        def dispatch(request):
            if failed.is_set():
                return None
            try:
                return judge(*request)
            except BaseException:
                failed.set()
                raise

        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = [pool.submit(dispatch, request) for request in wanted.values()]
        for future in futures:
            future.result()
        issued += len(wanted)


# ---------------------------------------------------------------- one locale

def screened_groups(paths: dict) -> tuple[list[dict], list[dict] | None]:
    """The QC groups of the screened candidate, and the full candidate's groups in spoken mode."""
    anchor, candidate = read(Path(paths["anchor"])), read(Path(paths["candidate"]))
    if "condensationBinding" not in paths:
        return qc_groups(candidate, anchor), None
    spoken = condensation.qc_groups(read(Path(paths["condensationBinding"])), anchor, candidate)
    return spoken, qc_groups(read(Path(paths["fullCandidate"])), anchor)


def run_locale(locale: str, paths: dict, out: Path, state: Path, judge, timings: Timings, workers: int) -> dict:
    source, anchor = read(Path(paths["source"])), read(Path(paths["anchor"]))
    candidate, policy = read(Path(paths["candidate"])), read(Path(paths["policy"]))
    groups, full_groups = screened_groups(paths)
    spoken = full_groups is not None
    binding = read(Path(paths["condensationBinding"])) if spoken else None
    full = read(Path(paths["fullCandidate"])) if spoken else candidate
    folder = out / locale / ("spoken" if spoken else "")
    lineage = ledger.lineage("text", locale, json_sha256(source), json_sha256(anchor))
    ledger_root = state / "repair-ledger"
    entries = ledger.load(ledger_root, lineage)
    # The head QC receipt lives beside the ledger, so any OUT using this state dir finds it.
    head_path = qc_receipt_path(state, lineage, len(entries)) if entries else None
    head = read(head_path) if head_path and head_path.exists() else None
    if head is not None and ledger.head_problems(lineage, entries, head):
        head = None
    # A failed screen is repaired by a new candidate revision, never by screening
    # the same text again under another runtime or implementation.
    if entries and entries[-1]["failedSourceUnitIds"]:
        if head is None:
            return {"status": "blocked_prior_failure",
                    "reason": f"the repair ledger head failed and its QC receipt is missing from {head_path}"}
        # Group ids are local to a revision; the ledger counts by source unit, so match on those.
        current = {(tuple(group["sourceUnitIds"]), hashlib.sha256(group["targetText"].encode("utf-8")).hexdigest()):
                   group for group in groups}
        # A length failure is relative to the candidate-wide median, so an unchanged
        # group is repaired only if it now passes against the current median.
        median = text_qc.candidate_length_median(groups)

        def still_failing(row, group):
            if row.get("problems") and all(problem.startswith("length ratio") for problem in row["problems"]):
                return text_qc.length_problem(group, median) is not None
            return True

        unrepaired = [current[key]["groupId"] for row in head["results"]
                      if row["status"] != "pass"
                      and (key := (tuple(row["sourceUnitIds"]), row["targetTextSha256"])) in current
                      and still_failing(row, current[key])]
        if unrepaired:
            return {"status": "blocked_prior_failure", "failedGroups": unrepaired,
                    "reason": "failed groups are unchanged; repair them in a new candidate revision"}
    # Past the repair ladder a unit falls back to English, which waiver v1 cannot
    # release, so no later revision is screened for it.
    counts = entries[-1]["failedAttempts"] if entries else {}
    exhausted = sorted(group["groupId"] for group in groups
                       if any(counts.get(unit, 0) > text_qc.MAX_TEXT_REPAIR_ATTEMPTS for unit in group["sourceUnitIds"]))
    if exhausted:
        return {"status": "source_text_fallback", "fallbackGroups": exhausted,
                "reason": "the repair limit is used up; waiver v1 cannot release an English fallback"}
    # Resume only receipts made from these exact inputs; a repaired candidate,
    # policy, judge runtime or implementation is screened and calibrated again.
    qc_binding = json_sha256({"groups": groups, "policy": policy, "identity": judge.identity,
                              "implementation": basis.waiver.implementation_sha256()})
    qc = load_once(head_path, qc_binding) if head is not None else None
    if qc is None:
        # The receipt is written before its ledger entry. A receipt past the ledger
        # head is from an interrupted run: append it if it still binds these inputs,
        # else discard it, since no ledger entry or waiver refers to it.
        next_path = qc_receipt_path(state, lineage, len(entries) + 1)
        pending = load_once(next_path, qc_binding) if next_path.exists() else None
        if pending is not None and pending.get("repairLedger") == ledger.position(lineage, entries):
            qc = pending
        else:
            for stale in (next_path, binding_path(next_path)):
                stale.unlink(missing_ok=True)

            def screen(call):
                return text_qc.screen(groups, locale, policy=policy, call=call, identity=judge.identity,
                                      repair_position=ledger.position(lineage, entries))
            timings.run(f"{locale}.text-qc.prefetch", lambda: prefetch(judge, screen, workers=workers))
            qc = timings.run(f"{locale}.text-qc", lambda: screen(judge))
            save_once(next_path, qc, qc_binding)
        ledger.append(ledger_root, lineage, qc)
        head_path = next_path
    result = {"textQc": qc["status"], "textQcReceipt": str(head_path),
              "failedGroups": [row["groupId"] for row in qc["results"] if row["status"] != "pass"]}
    if qc["sourceTextFallbackGroupIds"]:
        result.update(status="source_text_fallback", fallbackGroups=qc["sourceTextFallbackGroupIds"],
                      reason="the repair limit is used up; waiver v1 cannot release an English fallback")
        return result
    if qc["status"] != "pass":
        # Calibration binds this candidate, which a repair replaces anyway.
        result.update(status="requires_repair", reason="text QC failed; repair the failed groups in a new candidate revision")
        return result
    # Calibrations and waivers are immutable and named by their inputs, so a
    # revision adds a file and never replaces evidence an earlier waiver binds.
    calibration_binding = json_sha256({"qc": qc_binding, "candidate": candidate,
                                       **({"fullCandidate": full} if spoken else {})})
    calibration_path = folder / f"calibration-{calibration_binding[:16]}.json"
    calibration = load_once(calibration_path, calibration_binding)
    if calibration is None:
        def calibrate(call):
            if spoken:
                # Text kinds on the full translation, spoken kinds on the condensed groups.
                return seeded.calibrate(locale, full_groups, policy=policy, call=call, identity=judge.identity,
                                        candidate=full, spoken_groups=groups, spoken_candidate=candidate)
            return seeded.calibrate(locale, groups, policy=policy, call=call, identity=judge.identity,
                                    candidate=candidate)
        timings.run(f"{locale}.calibration.prefetch", lambda: prefetch(judge, calibrate, workers=workers))
        calibration = timings.run(f"{locale}.calibration", lambda: calibrate(judge))
        save_once(calibration_path, calibration, calibration_binding)
    result["calibration"] = {key: calibration[key] for key in
                             ("overallDetectionRate", "cleanFalsePositiveRate", "trials", "detected")}
    result["calibrationMisses"] = {kind: row for kind, row in calibration["kinds"].items() if row["rate"] < 0.9}
    entries = ledger.load(ledger_root, lineage)
    waiver_binding = json_sha256({"calibration": calibration_binding, "qc": json_sha256(qc),
                                  "calibrationReceipt": json_sha256(calibration), "ledger": entries,
                                  **({"condensationBinding": json_sha256(binding)} if spoken else {})})
    waiver_path = folder / f"{'spoken-' if spoken else ''}text-waiver-{waiver_binding[:16]}.json"
    if not isinstance(judge, FakeJudge):
        saved = load_once(waiver_path, waiver_binding)
        if saved is not None:
            basis.validate_text_waiver(saved, candidate=candidate)
            result.update(status="text_waiver_issued", textWaiver=str(waiver_path), reused=True)
            return result
    try:
        waiver = timings.run(f"{locale}.text-waiver", lambda: basis.build_text_waiver(
            source, anchor, candidate, qc, calibration, repair_ledger=entries, condensation_binding=binding))
    except ValueError as error:
        result.update(status="waiver_refused", reason=str(error))
        return result
    if isinstance(judge, FakeJudge):
        basis.validate_text_waiver(waiver, candidate=candidate)
        result.update(status="fake_plumbing_pass", reason="fake judge: waiver built in memory, never saved")
        return result
    save_once(waiver_path, waiver, waiver_binding)
    result.update(status="text_waiver_issued", textWaiver=str(waiver_path))
    return result


def still_valid(row: dict) -> bool:
    """An earlier summary row still describes its candidate and the receipts it names."""
    try:
        if "paths" in row and json_sha256(read(Path(row["paths"]["candidate"]))) != row.get("candidateJsonSha256"):
            return False
        for key in ("textQcReceipt", "textWaiver"):
            if key in row and json_sha256(read(Path(row[key]))) != read(binding_path(Path(row[key]))).get("receiptJsonSha256"):
                return False
        if row.get("status") != "text_waiver_issued":
            return True
        path = Path(row["textWaiver"])
        marker = read(binding_path(path))
        waiver = read(path)
        if json_sha256(waiver) != marker.get("receiptJsonSha256"):
            return False
        basis.validate_text_waiver(waiver, candidate=read(Path(row["paths"]["candidate"])))
    except (KeyError, OSError, ValueError, TypeError):
        return False
    return True


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--run-dir", type=Path, default=ROOT / "artifacts/dev-full-rerun-20261001")
    parser.add_argument("--out", type=Path, required=True, help="New or resumed output directory (ignored artifacts/)")
    parser.add_argument("--state-dir", type=Path, help="The run's persistent state dir holding its repair ledger (required for real runs)")
    parser.add_argument("--locales", default=",".join(LOCALES))
    parser.add_argument("--candidate", action="append", default=[], metavar="LOCALE=PATH",
                        help="Use this candidate instead of searching the run")
    parser.add_argument("--spoken-binding", action="append", default=[], metavar="LOCALE=PATH",
                        help="Screen the condensed spoken script this spoken_condensation binding names")
    parser.add_argument("--text-backend", choices=("codex", "fake"), default="codex")
    parser.add_argument("--workers", type=int, default=4, help="Parallel Codex CLI calls")
    parser.add_argument("--preflight-only", action="store_true", help="Stop before any model call")
    args = parser.parse_args(argv)
    locales = [locale for locale in args.locales.split(",") if locale]
    if not locales or set(locales) - set(LOCALES):
        parser.error(f"--locales must name one or more of {', '.join(LOCALES)}")
    if not 1 <= args.workers <= MAX_WORKERS:
        parser.error(f"--workers must be between 1 and {MAX_WORKERS}")
    if args.text_backend == "codex" and not args.preflight_only and not args.state_dir:
        # The repair ledger must outlive any one OUT, or each revision would restart the repair cap.
        parser.error("real runs need --state-dir: the run's persistent state dir holding its repair ledger")
    if args.text_backend == "fake" and args.state_dir:
        parser.error("--text-backend fake never writes to a persistent state dir")
    overrides = {}
    for item in args.candidate:
        locale, _, path = item.partition("=")
        if not path or locale not in locales or locale in overrides:
            parser.error(f"--candidate {item!r}: use LOCALE=PATH once per requested locale ({', '.join(locales)})")
        overrides[locale] = path
    bindings = {}
    for item in args.spoken_binding:
        locale, _, path = item.partition("=")
        if not path or locale not in locales or locale in bindings:
            parser.error(f"--spoken-binding {item!r}: use LOCALE=PATH once per requested locale ({', '.join(locales)})")
        bindings[locale] = Path(path).resolve()
    # Fake runs write every receipt, and their own ledger, in a separate subtree,
    # so plumbing output never touches real evidence or repair attempts.
    out = args.out.resolve() / ("fake-plumbing" if args.text_backend == "fake" else "")
    state = out / "state" if args.text_backend == "fake" else (args.state_dir or out / "state").resolve()
    for path in (out, state):
        if path.is_relative_to(ROOT) and subprocess.run(["git", "-C", str(ROOT), "check-ignore", "-q", str(path)]).returncode:
            parser.error(f"{path} is not ignored by Git; use a directory under artifacts/")
    out.mkdir(parents=True, exist_ok=True)
    state.mkdir(parents=True, exist_ok=True)
    REPORT_DIRS.append(out)
    locks = []
    for folder in dict.fromkeys((out, state)):  # One writer per OUT and per state dir.
        locks.append((folder / ".run.lock").open("a"))
        try:
            fcntl.flock(locks[-1], fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            parser.error(f"another run is using {folder}")
    timings = Timings(out / "timings.tsv")
    index = timings.run("discover", lambda: index_run(args.run_dir))
    summary = {"runDir": str(args.run_dir.resolve()), "textBackend": args.text_backend,
               "implementationSha256": basis.waiver.implementation_sha256(), "locales": {}}
    # Resuming a subset keeps the other locales' rows from earlier runs in this OUT,
    # but only rows from the same run and implementation whose evidence still holds.
    previous = read(out / "summary.json") if (out / "summary.json").exists() else {}
    if all(previous.get(key) == summary[key] for key in ("runDir", "textBackend", "implementationSha256")):
        for locale, row in previous.get("locales", {}).items():
            if locale not in locales:
                summary["locales"][locale] = row if still_valid(row) else {
                    "status": "stale", "reason": "earlier row no longer matches its evidence; rerun this locale",
                    "previousStatus": row.get("status")}
    resolved = {}
    for locale in locales:
        found = resolve_locale(args.run_dir, index, locale, Path(overrides[locale]) if locale in overrides else None,
                               bindings.get(locale), args.text_backend == "fake")
        if not found["problems"]:
            groups, full_groups = screened_groups(found["paths"])
            policy = read(Path(found["paths"]["policy"]))
            coverage = (calibration_coverage(groups, locale, policy) if full_groups is None
                        else calibration_coverage(full_groups, locale, policy, spoken_groups=groups))
            found["calibrationCoverage"] = coverage
            if coverage["untestableKinds"]:
                found["problems"].append("this text cannot be calibrated for: " + ", ".join(coverage["untestableKinds"]))
        save(out / locale / "preflight.json", found)
        summary["locales"][locale] = {"status": "blocked" if found["problems"] else "ready", **found}
        if not found["problems"]:
            resolved[locale] = found["paths"]
    save(out / "summary.json", summary)
    if args.preflight_only or not resolved:
        print(json.dumps({locale: summary["locales"][locale]["problems"] for locale in locales},
                         ensure_ascii=False, indent=2))
        return 0 if len(resolved) == len(locales) else 2
    if args.text_backend == "codex":
        judge = CodexJudge(state / "codex-calls")
    else:
        judge = FakeJudge({locale: [group for part in screened_groups(paths) for group in part or []]
                           for locale, paths in resolved.items()})
    for locale, paths in resolved.items():
        # A call with an unknown outcome blocks every new dispatch in this run
        # until it is reconciled; other errors stop only their own locale.
        uncertain = judge.uncertain()
        if uncertain:
            outcome = {"status": "blocked_unknown_outcome", "uncertainCalls": uncertain,
                       "reason": f"model calls with an unknown outcome in {state / 'codex-calls'}; reconcile them first"}
        else:
            try:
                outcome = run_locale(locale, paths, out, state, judge, timings, args.workers)
            except Exception as error:  # The receipt says what failed.
                outcome = {"status": "error", "reason": f"{type(error).__name__}: {error}"}
        summary["locales"][locale].update(outcome)
        save(out / "summary.json", summary)
    print(json.dumps({locale: {key: row.get(key) for key in ("status", "reason", "problems", "calibration")}
                      for locale, row in summary["locales"].items()}, ensure_ascii=False, indent=2))
    done = "fake_plumbing_pass" if args.text_backend == "fake" else "text_waiver_issued"
    return 0 if all(summary["locales"][locale].get("status") == done for locale in locales) else 1


if __name__ == "__main__":
    from scripts.export_run_digest import write_report
    try:
        code = main()
    finally:
        if REPORT_DIRS:  # Pass or fail, leave a redacted run report for cloud review.
            write_report(REPORT_DIRS, "machine-qc-text")
    sys.exit(code)
