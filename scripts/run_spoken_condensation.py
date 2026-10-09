#!/usr/bin/env python3
"""Condense one locale's over-window dub groups with a local model.

Runs ``spoken_condensation.condense`` for a full Layer 2 candidate and its
pre-TTS budget (``target_audio_predicted_schedule.py budget``), then writes the
condensation record and its Layer 2 revision brief. The brief feeds
``run_target_language_models.py --revision-brief``; the spoken candidate that
chain produces is bound with ``spoken_condensation.py bind`` and screened in
spoken mode by ``run_machine_qc_clip_test.py --spoken-binding``.

The condenser transport is the local Codex CLI under ChatGPT login, the same
mechanism and cache rules as the back-translation judge
(``run_machine_qc_clip_test.CodexJudge``): Sol 6.1 at high reasoning effort,
the effort of Layer 2 initial translation, with its own cache namespace. Every
call is cached by request and transport identity under the state dir, so a
rerun reuses finished calls; groups are condensed in parallel first, then the
record is assembled from the cache. A call with an unknown outcome blocks new
dispatch until it is reconciled. ``--backend fake`` drops leading clauses
instead of calling a model, for plumbing tests only: its output stays under
``OUT/fake-plumbing`` and its record names the fake backend.

The record and brief are written once under names derived from their inputs,
so a rerun with the same inputs reuses them and changed inputs add files; no
evidence is replaced. Nothing here edits the full candidate, publishes, or
grants approval.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
import fcntl
import itertools
import json
from pathlib import Path
import re
import subprocess
import sys
import threading

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts import run_machine_qc_clip_test as clip
from scripts import spoken_condensation as condensation
from scripts import target_audio_predicted_schedule as predicted

ROOT = Path(__file__).resolve().parents[1]
CACHE_NAMESPACE = "spoken-condensation-v1"
REASONING_EFFORT = "high"  # Same as Layer 2 initial translation (production-model-runtime-policy).
TIMEOUT_SECONDS = 600
json_sha256 = clip.json_sha256
read, save, save_once, load_once = clip.read, clip.save, clip.save_once, clip.load_once


def codex_condenser(cache: Path):
    """The Codex CLI condenser: Sol 6.1 high, cached per request and transport identity."""
    return clip.CodexJudge(cache, timeout_seconds=TIMEOUT_SECONDS, reasoning=REASONING_EFFORT,
                           cache_namespace=CACHE_NAMESPACE)


class FakeCondenser:
    """Plumbing-only condenser: drops whole clauses, declared as restatement.

    It keeps the most clauses whose text fits and passes the deterministic
    checks, so the plumbing reaches a brief; it judges no meaning."""

    CLAUSE = re.compile(r"[^，。；：！？,.;:!?]+[，。；：！？,.;:!?]*\s*")
    MAX_CLAUSES = 12

    def __init__(self, locale: str, policy: dict | None):
        self.locale, self.policy = locale, policy
        self.identity = {"backend": "fake-clause-drop-not-evidence", "model": "fake-condenser",
                         "modelRevision": "0", "cacheNamespace": CACHE_NAMESPACE, "settings": {"fake": True}}

    def uncertain(self) -> list[str]:
        return []

    def __call__(self, role, system, user, schema):
        asked = json.loads(user)
        full = asked["fullTranslation"]
        clauses = [clause for clause in self.CLAUSE.findall(full) if clause.strip()][:self.MAX_CLAUSES]
        request = {"translationGroupId": asked["translationGroupId"], "fullTargetText": full,
                   "maxSpeechUnits": asked["maxSpeechUnits"],
                   "englishUnits": [{"sourceUnitId": "fake", "english": asked["english"]}]}
        best = {"translationGroupId": asked["translationGroupId"], "spokenText": full, "omissions": []}
        for count in range(1, len(clauses)):
            for dropped in itertools.combinations(range(len(clauses)), count):
                spoken = "".join(clause for index, clause in enumerate(clauses) if index not in dropped).strip()
                omissions = [{"fullTextSpan": clauses[index].strip(), "kind": "restatement"} for index in dropped]
                if not condensation.spoken_problems(request, spoken, omissions, self.locale, self.policy):
                    return {**best, "spokenText": spoken, "omissions": omissions}
        return best


def prefetch(condenser, requests: list[dict], locale: str, policy: dict, *, workers: int) -> None:
    """Condense the independent groups in parallel so the record run reads the cache.

    After any failure nothing new is dispatched; calls already running finish
    and keep their receipts."""
    failed = threading.Event()

    def one(request):
        if failed.is_set():
            return None
        try:
            return condensation._condense_one(request, locale, policy, condenser)
        except BaseException:
            failed.set()
            raise

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(one, request) for request in requests]
    for future in futures:
        future.result()


def run(paths: dict, out: Path, condenser, *, workers: int, timings) -> dict:
    """Condense one locale and write its record and brief; returns the summary row."""
    anchor, candidate = read(paths["anchor"]), read(paths["candidate"])
    budget, policy = read(paths["budget"]), read(paths["policy"])
    if json_sha256(policy) != candidate.get("translationPolicySha256"):
        raise ValueError("Policy is not the candidate's frozen translation policy")
    # Validates the budget, anchor and frozen timing before any model call.
    asked = condensation.requests(anchor, candidate, budget)
    locale = asked["targetLocale"]
    row = {"locale": locale, "candidateJsonSha256": json_sha256(candidate), "budgetJsonSha256": json_sha256(budget),
           "condenserIdentity": condenser.identity, "cannotFitGroupIds": asked["cannotFitGroupIds"],
           "shortenGroupIds": [request["translationGroupId"] for request in asked["requests"]]}
    if not asked["requests"]:
        return {**row, "status": "nothing_to_condense", "reason": "the budget marks no group shorten"}
    binding = json_sha256({"anchor": json_sha256(anchor), "candidate": json_sha256(candidate),
                           "budget": json_sha256(budget), "policy": json_sha256(policy),
                           "identity": condenser.identity, "promptVersion": condensation.PROMPT_VERSION,
                           "implementation": condensation.implementation_sha256()})
    record_path = out / f"condensation-record-{binding[:16]}.json"
    record = load_once(record_path, binding)
    reused = record is not None
    if record is None:
        uncertain = condenser.uncertain()
        if uncertain:
            return {**row, "status": "blocked_unknown_outcome", "uncertainCalls": uncertain,
                    "reason": "condenser calls with an unknown outcome; reconcile them first"}
        timings.run(f"{locale}.condense.prefetch",
                    lambda: prefetch(condenser, asked["requests"], locale, policy, workers=workers))
        record = timings.run(f"{locale}.condense", lambda: condensation.condense(
            anchor, candidate, budget, call=condenser, identity=condenser.identity, policy=policy))
        save_once(record_path, record, binding)
    row.update(record=str(record_path), recordReused=reused, recordStatus=record["status"],
               condensedGroupIds=[g["translationGroupId"] for g in record["groups"] if g["status"] == "condensed"],
               failedGroupIds=record["failedGroupIds"], modelCalls=record["modelCalls"])
    if not row["condensedGroupIds"]:
        return {**row, "status": "no_group_condensed",
                "reason": "every shorten group failed its checks; those groups stay subtitle-only in the dub"}
    brief_binding = json_sha256({"record": json_sha256(record), "candidate": json_sha256(candidate)})
    brief_path = out / f"revision-brief-{brief_binding[:16]}.json"
    brief = load_once(brief_path, brief_binding)
    if brief is None:
        save_once(brief_path, condensation.revision_brief(record, candidate), brief_binding)
    row["revisionBrief"] = str(brief_path)
    row["status"] = "brief_ready" if not record["failedGroupIds"] else "brief_ready_with_failures"
    if record["failedGroupIds"]:
        row["reason"] = "failed groups keep the full translation; their dub falls back to subtitles"
    return row


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--candidate", required=True, type=Path, help="The full Layer 2 candidate")
    parser.add_argument("--budget", required=True, type=Path,
                        help="Its pre-TTS budget (target_audio_predicted_schedule.py budget)")
    parser.add_argument("--anchor", required=True, type=Path, help="The frozen anchor manifest the candidate binds")
    parser.add_argument("--policy", required=True, type=Path, help="The candidate's frozen translation policy")
    parser.add_argument("--out", required=True, type=Path, help="New or resumed output directory (ignored artifacts/)")
    parser.add_argument("--state-dir", type=Path, help="Where the model call cache lives (default OUT/state)")
    parser.add_argument("--backend", choices=("codex", "fake"), default="codex")
    parser.add_argument("--workers", type=int, default=4, help="Parallel Codex CLI calls")
    args = parser.parse_args(argv)
    if not 1 <= args.workers <= clip.MAX_WORKERS:
        parser.error(f"--workers must be between 1 and {clip.MAX_WORKERS}")
    if args.backend == "fake" and args.state_dir:
        parser.error("--backend fake never writes to a persistent state dir")
    out = args.out.resolve() / ("fake-plumbing" if args.backend == "fake" else "")
    state = out / "state" if args.backend == "fake" else (args.state_dir or out / "state").resolve()
    for path in (out, state):
        if path.is_relative_to(ROOT) and subprocess.run(
                ["git", "-C", str(ROOT), "check-ignore", "-q", str(path)]).returncode:
            parser.error(f"{path} is not ignored by Git; use a directory under artifacts/")
    out.mkdir(parents=True, exist_ok=True)
    state.mkdir(parents=True, exist_ok=True)
    with ExitStack() as stack:
        for folder in dict.fromkeys((out, state)):  # One writer per OUT and per state dir.
            lock = stack.enter_context((folder / ".run.lock").open("a"))
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                parser.error(f"another run is using {folder}")
        paths = {name: getattr(args, name).resolve() for name in ("candidate", "budget", "anchor", "policy")}
        locale = read(paths["candidate"]).get("targetLocale")
        condenser = (codex_condenser(state / "codex-calls") if args.backend == "codex"
                     else FakeCondenser(locale, read(paths["policy"])))
        timings = clip.Timings(out / "timings.tsv")
        try:
            row = run(paths, out, condenser, workers=args.workers, timings=timings)
        except Exception as error:  # The summary says what failed.
            row = {"locale": locale, "status": "error", "reason": f"{type(error).__name__}: {error}"}
        summary = {"backend": args.backend, "inputs": {name: str(path) for name, path in paths.items()},
                   "implementationSha256": condensation.implementation_sha256(), **row}
        save(out / "summary.json", summary)
    print(json.dumps({key: summary.get(key) for key in ("status", "reason", "record", "revisionBrief",
                                                           "condensedGroupIds", "failedGroupIds")},
                     ensure_ascii=False, indent=2))
    return 0 if row["status"] in ("brief_ready", "nothing_to_condense") else 1


if __name__ == "__main__":
    sys.exit(main())
