#!/usr/bin/env python3
"""Run a real-model clip E2E: a weekly clip through Layer 1-4 to an isolated Dev page.

One run specification (``sermon-clip-real-e2e-run-v1``) names the clip, the locales, the frozen
policy and voice-rights templates of the source week, the approved spend and the test page.
The run directory (under ``artifacts/``) holds every input and output; each stage records its
result in ``stages.json`` and a resumed run skips finished stages. Stages, in order:

1. ``inputs``: the clip's English source, anchors and media (``build_dev_180s_simulated_inputs``,
   under its own test root) and its timeline map (``clip_timeline_map``);
2. ``layer2-setup``: clip-scoped frozen policies, the canonical Layer 2 execution config and the
   QC inputs bound to the explicit OpenAI launcher route;
3. ``layer2``: budget plan, start check, then the canonical controller for every locale;
4. ``qc.<locale>``: one QC budget per locale, text QC; a failed group goes back to Layer 2 as a
   revision carrying the QC receipt (execution v5, gate 4) and is checked again, at most
   ``qc.maxRevisions`` times;
5. ``audio.<locale>``: inside one exclusive Spark session, voice authorization, speech job, render,
   compaction, ASR screen, audio package and audio QC (``clip_e2e_spark``);
6. ``layer4``: the machine-checked release (``clip_e2e_release``), Dev baseline, guarded publish
   with ``--publish`` only, and the browser smoke;
7. ``report``: the redacted run report (``export_run_digest``), not yet published.

Spend is planned with ``plan_run_budgets.py`` against the specification's approved total:
settled spend is the specification's earlier spend plus this run's ledgers (unpriced rows at
their reservation), and every QC budget still open counts at its full cap. Nothing here marks
any content human-approved. See docs/clip-real-e2e.zh.md.
"""
from __future__ import annotations

import argparse
import copy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

SPEC_SCHEMA = "sermon-clip-real-e2e-run-v1"
LOCALES = ("zh-Hans", "ko", "es")
DEV_ORIGIN = "https://ai-for-god-sermon-audio-dev.web.app"
PY = sys.executable
WORKER_PATTERN = "run.py text.controller worker"


class Stop(Exception):
    """A stage ended without its outcome; the message says what to look at."""


def require(ok, message):
    if not ok:
        raise ValueError(message)


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def read(path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write(path, value) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return path


# ---------------------------------------------------------------- specification


def load_spec(path: Path) -> dict:
    """Validate a run specification and resolve its paths against the specification's directory."""
    path = Path(path).resolve()
    spec = read(path)
    base = path.parent
    resolve = lambda value: str((base / value).resolve())
    require(spec.get("schemaVersion") == SPEC_SCHEMA, "unsupported run specification")
    require(set(spec) <= {"schemaVersion", "name", "clipSpec", "locales", "openai", "authorization", "budget",
                          "layer2", "layer3", "qc", "spark", "page", "notes"}, "unknown run specification field")
    require(isinstance(spec.get("name"), str) and spec["name"].replace("-", "").isalnum() and len(spec["name"]) <= 60,
            "name must be a short [A-Za-z0-9-] label")
    locales = spec.get("locales")
    require(isinstance(locales, list) and locales and len(set(locales)) == len(locales)
            and set(locales) <= set(LOCALES), "locales must be distinct values of " + ", ".join(LOCALES))
    auth = spec.get("authorization") or {}
    require(all(isinstance(auth.get(k), str) and auth[k].strip() for k in ("approvedBy", "evidence", "defaultPass"))
            and "not a human review" in auth["defaultPass"],
            "authorization needs approvedBy, evidence and a defaultPass statement saying it is not a human review")
    budget = spec.get("budget") or {}
    require(all(type(budget.get(k)) in (int, float) and budget[k] >= 0 for k in ("totalUsd", "settledUsdBefore"))
            and budget["settledUsdBefore"] < budget["totalUsd"], "budget needs totalUsd > settledUsdBefore >= 0")
    layer2, layer3 = spec.get("layer2") or {}, spec.get("layer3") or {}
    for field, table in (("policyTemplates", layer2), ("plugins", layer2), ("attestationTemplates", layer3)):
        require(isinstance(table.get(field), dict) and set(locales) <= set(table[field]), f"{field} missing a locale")
        table[field] = {k: resolve(v) for k, v in table[field].items() if k in locales}
    require(isinstance(layer3.get("speakerRegistry"), str), "layer3.speakerRegistry required")
    layer3["speakerRegistry"] = resolve(layer3["speakerRegistry"])
    layer3.setdefault("maxEndLagSeconds", 120.0)
    spec["clipSpec"] = resolve(spec["clipSpec"])
    openai = spec.setdefault("openai", {})
    openai.setdefault("environment", "dev")
    require(openai["environment"] in ("dev", "prod"), "openai.environment must be dev or prod")
    openai["envFile"] = resolve(openai.get("envFile", str(ROOT / ".env.openai")))
    qc = spec.setdefault("qc", {})
    qc.setdefault("maxRevisions", 2)
    require(type(qc["maxRevisions"]) is int and 0 <= qc["maxRevisions"] <= 3, "qc.maxRevisions must be 0-3")
    page = spec.get("page") or {}
    require(isinstance(page.get("pageId"), str) and page["pageId"].startswith("mockup-"),
            "page.pageId must be an isolated mockup- page")
    from scripts import clip_e2e_release
    clip_e2e_release.validate_display(page.get("display"), locales)
    spark = spec.setdefault("spark", {})
    spark.setdefault("sessionId", "clip-e2e-" + spec["name"])
    spark.setdefault("owner", "clip-e2e-" + spec["name"])
    for key in ("baselineCachePublic", "baselineCacheReceipt"):
        if page.get(key):
            page[key] = resolve(page[key])
    return spec


# ---------------------------------------------------------------- run state


class Run:
    def __init__(self, spec_path: Path, run_dir: Path, *, publish: bool):
        self.spec_path = Path(spec_path).resolve()
        self.spec = load_spec(self.spec_path)
        self.dir = Path(run_dir).resolve()
        artifacts = (ROOT / "artifacts").resolve()
        require(str(self.dir).startswith(str(artifacts) + "/"),
                "run directory must be under artifacts/ (it is mirrored to Spark at the same path)")
        self.publish = publish
        self.dir.mkdir(parents=True, exist_ok=True)
        frozen = self.dir / "run-spec.json"
        spec_bytes = self.spec_path.read_bytes()
        if frozen.exists():
            require(frozen.read_bytes() == spec_bytes, "run directory belongs to another specification")
        else:
            frozen.write_bytes(spec_bytes)
        self.stages_path = self.dir / "stages.json"
        self.stages = read(self.stages_path) if self.stages_path.exists() else {}
        (self.dir / "logs").mkdir(exist_ok=True)
        from scripts import clip_e2e_spark
        self.runtime = clip_e2e_spark.load_runtime()
        self.stage_dir = f"{self.runtime['stageRoot'].rstrip('/')}/clip-e2e-{self.spec['name']}"
        self.session_up = False

    # -- bookkeeping
    def done(self, name) -> bool:
        return (self.stages.get(name) or {}).get("status") == "done"

    def mark(self, name, status, **info):
        self.stages[name] = {"status": status, "at": now(), **info}
        write(self.stages_path, self.stages)

    def sh(self, label, argv, *, launcher=False, check=True, cwd=ROOT, env=None) -> subprocess.CompletedProcess:
        if launcher:
            argv = [PY, str(ROOT / "scripts/run_with_openai_environment.py"), "--environment",
                    self.spec["openai"]["environment"], "--env-file", self.spec["openai"]["envFile"], "--", *argv]
        log = self.dir / "logs" / f"{label}.log"
        started = time.time()
        with log.open("ab") as stream:
            stream.write(f"\n== {now()} {' '.join(map(str, argv))}\n".encode())
            stream.flush()
            done = subprocess.run([str(a) for a in argv], cwd=cwd, stdout=stream, stderr=subprocess.STDOUT,
                                  env={**os.environ, **(env or {})})
        with (self.dir / "timings.tsv").open("a") as timings:
            timings.write(f"{label}\t{'pass' if done.returncode == 0 else 'fail(%d)' % done.returncode}\t"
                          f"{round(time.time() - started)}\n")
        if check and done.returncode != 0:
            raise Stop(f"{label} exited {done.returncode}; see {log}")
        return done

    # -- paths
    @property
    def l2(self) -> Path:
        return self.dir / "l2"

    def candidate(self, locale) -> Path:
        info = self.stages.get("qc." + locale) or {}
        return Path(info.get("candidate") or self.l2 / "text" / locale / "candidate.json")

    def impl(self) -> str:
        from scripts import tongxing_host  # noqa: F401  binds the production package ports
        from tongxing_production.review import waiver
        return waiver.implementation_sha256()

    def head(self) -> str:
        return subprocess.run(["git", "-C", str(ROOT), "rev-parse", "HEAD"], check=True, capture_output=True,
                              text=True).stdout.strip()

    # -- budget
    def settled(self) -> float:
        """Earlier spend plus this run's Layer 2 results and QC ledgers; unpriced rows count at their reservation."""
        from scripts.export_run_digest import budget_summary
        total = 0
        for path in self.dir.rglob("*.result.json"):
            if "layer2-budget" in str(path) and "responses" not in path.parts:
                total += read(path)["result"]["usage"]["costMicrousd"]
        for path in self.dir.rglob("source-budget.json"):
            ledger = read(path)
            total += budget_summary(ledger).get("estimatedMicrousd", 0)
            total += sum((row.get("bounds") or {}).get("costMicrousd", 0) for row in ledger.get("requests", {}).values()
                         if row.get("status") == "returned"
                         and (row.get("settlement") or {}).get("costStatus") not in ("estimated_upper_bound", "reused"))
        return round(self.spec["budget"]["settledUsdBefore"] + total / 1e6, 6)

    def open_qc_caps(self) -> float:
        """Full caps of QC budgets planned in this run whose locale has not finished audio QC."""
        caps = 0.0
        for locale in self.spec["locales"]:
            plan = self.dir / "plans" / f"qc-{locale}" / "plan.json"
            if plan.exists() and not self.done("audio." + locale) and (self.stages.get("audio." + locale) or {}).get(
                    "status") != "failed":
                caps += sum(stage["capUsd"] for stage in read(plan)["stages"])
        return caps

    def plan(self, out: Path, stages: list[str], locales: list[str], *, extra: list = (), include_open_qc=True):
        if (out / "plan.json").exists():
            return
        settled = self.settled() + (self.open_qc_caps() if include_open_qc else 0)
        auth = self.spec["authorization"]
        argv = [PY, ROOT / "scripts/plan_run_budgets.py", "--out", out, "--scale", "clip", "--locales", ",".join(locales),
                "--total-usd", self.spec["budget"]["totalUsd"], "--settled-usd", round(settled, 6),
                "--approved-by", auth["approvedBy"],
                "--evidence", auth["evidence"] + f" Run {self.spec['name']}; settled and open caps {round(settled, 3)} USD.",
                *[arg for stage in stages for arg in ("--stage", stage)], *extra]
        self.sh("plan-" + out.name, argv, launcher=True)

    def check(self, label, *extra):
        out = self.dir / f"start-check-{label}.json"
        done = self.sh("check-" + label, [PY, ROOT / "scripts/check_run_start.py", "--expected-commit", self.head(),
                                          "--expected-implementation", self.impl(),
                                          "--openai-environment", self.spec["openai"]["environment"],
                                          "--env-file", self.spec["openai"]["envFile"], *extra, "--out", out], check=False)
        if done.returncode != 0:
            report = read(out)
            raise Stop(f"start check {label} failed: " + json.dumps(
                [(c["check"], c.get("problems")) for c in report["checks"] if c["status"] == "fail"], ensure_ascii=False))


# ---------------------------------------------------------------- stages: inputs and Layer 2


def stage_inputs(run: Run):
    # The clip builder writes only under its own ignored test root; the run keeps copies of what it binds.
    from scripts.build_dev_180s_simulated_inputs import TEST_ROOT
    inputs = TEST_ROOT / ("clip-e2e-" + run.spec["name"]) / "inputs"
    if not (inputs / "source.json").exists():
        run.sh("inputs", [PY, ROOT / "scripts/build_dev_180s_simulated_inputs.py", "--clip-spec", run.spec["clipSpec"],
                          "--run-id", "clip-e2e-" + run.spec["name"], "--out", inputs])
    src = run.l2 / "src"
    src.mkdir(parents=True, exist_ok=True)
    for name in ("source.json", "anchor.json"):
        if not (src / name).exists():
            shutil.copyfile(inputs / name, src / name)
    timeline = run.dir / "l3" / "clip-timeline-map.json"
    if not timeline.exists():
        timeline.parent.mkdir(parents=True, exist_ok=True)
        run.sh("timeline-map", [PY, ROOT / "tools/ops/run.py", "audio.clip_timeline", "--source", src / "source.json",
                                "--anchor", src / "anchor.json", "--clip-media", inputs / "clip/source.mp4",
                                "--out", timeline])
    anchor = read(src / "anchor.json")
    run.mark("inputs", "done", units=len(anchor["sourceUnits"]), inputs=str(inputs))


def freeze_clip_policy(template: Path, source: dict, anchor: dict, *, reviewed_by: str, statement: str) -> dict:
    """The source week's frozen policy narrowed to this clip's source scope and terms, frozen again."""
    from scripts import target_language_policy as tp
    rows = anchor["sourceUnits"]
    observed = tp.source_scoped_proper_names(rows, set())
    frozen = read(template)
    exclusions = sorted(e for e in frozen["sourceScope"]["ordinaryPhraseExclusions"] if e in observed)
    used = sorted(observed - set(exclusions))
    draft = copy.deepcopy(frozen)
    draft.pop("componentSha256")
    draft["terminology"]["properNames"] = [t for t in draft["terminology"]["properNames"] if t["source"] in used]
    scope = draft["sourceScope"]
    scope.update(englishSourcePackageJsonSha256=tp.canonical_sha256(source), anchorManifestSha256=tp.canonical_sha256(anchor),
                 usedSeriesNames=[], usedProperNames=used, ordinaryPhraseExclusions=exclusions, termApprovalEvidence=[])
    receipt = scope["termApprovalReceipt"]
    targets = {t["source"]: t["target"] for t in receipt["approvedTerms"]}
    missing = [name for name in used if name not in targets]
    require(not missing, f"the source week's term receipt has no approved target for {missing}")
    unit_with = lambda term: next(r["sourceUnitId"] for r in rows if term.casefold() in r["english"].casefold())
    receipt.update(englishSourcePackageJsonSha256=scope["englishSourcePackageJsonSha256"],
                   anchorManifestSha256=scope["anchorManifestSha256"],
                   approvedTerms=[{"source": n, "target": targets[n], "sourceUnitId": unit_with(n)} for n in used],
                   excludedScannerPhrases=[p for p in receipt.get("excludedScannerPhrases", [])
                                           if (p if isinstance(p, str) else p.get("source")) in exclusions],
                   reviewedBy=reviewed_by, reviewedAt=now(), userStatement=statement)
    policy = tp.freeze_policy(draft, series_table=tp.SERIES_TABLE, language_review="draft")
    tp.validate_source_scope(policy, source, anchor)
    require(tp.validate_policy(policy, series_table=tp.SERIES_TABLE)["productionPolicyReady"], "clip policy not ready")
    return policy


def stage_layer2_setup(run: Run):
    spec, l2 = run.spec, run.l2
    source, anchor = read(l2 / "src/source.json"), read(l2 / "src/anchor.json")
    auth = spec["authorization"]
    for locale in spec["locales"]:
        path = l2 / "policy" / f"{locale}-policy-clip.json"
        if not path.exists():
            write(path, freeze_clip_policy(Path(spec["layer2"]["policyTemplates"][locale]), source, anchor,
                                           reviewed_by=auth["defaultPass"] + "; targets carried from the source week's receipt",
                                           statement=auth["evidence"]))
    if not (l2 / "execution.json").exists():
        write(l2 / "inspection.json", {"schemaVersion": "sermon-canonical-package-inspection-config-v1",
                                       "source": "src/source.json", "anchor": "src/anchor.json",
                                       "locales": {k: {"policy": f"policy/{k}-policy-clip.json"} for k in spec["locales"]}})
        from scripts import tongxing_host  # noqa: F401  binds the production package ports
        from tongxing_production.text import controller
        from scripts import layer2_auto_repair as auto_repair
        run_id = hashlib.sha256(("clip-real-e2e " + spec["name"] + " " + ",".join(spec["locales"])).encode()).hexdigest()
        write(l2 / "execution.json", {
            "schemaVersion": controller.AUTO_REPAIR_SCHEMA, "productionRunId": run_id, "inspectionConfig": "inspection.json",
            "jobRoot": "layer2-jobs",
            "locales": {k: {"outputDirectory": f"text/{k}", "plugin": spec["layer2"]["plugins"][k]} for k in spec["locales"]},
            "layer2AutoRepair": {"routingVersion": auto_repair.ROUTING_VERSION, "groupWorkers": 8,
                                 "maxActiveLocales": len(spec["locales"])}})
    if not (l2 / "qc-inputs.json").exists():
        run.sh("route-probe", [PY, Path(__file__).resolve(), "_route", "--out", run.dir / "logs/route.json"], launcher=True)
        route = read(run.dir / "logs/route.json")
        write(l2 / "qc-inputs.json", {"schemaVersion": "sermon-machine-qc-inputs-v3", "environment": spec["openai"]["environment"],
                                      "openaiRoute": route["openaiRoute"], "credentialSha256": route["credentialSha256"],
                                      "source": "src/source.json", "anchor": "src/anchor.json",
                                      "policies": {k: f"policy/{k}-policy-clip.json" for k in spec["locales"]}})
    run.mark("layer2-setup", "done")


def drive_layer2(run: Run, execution: Path, authorization: Path, locales: list[str], label: str):
    """Tick the canonical controller until every locale succeeds; a blocked locale stops the stage."""
    for attempt in range(12):
        result_path = run.dir / "logs" / f"{label}-tick.json"
        run.sh(label, [PY, Path(__file__).resolve(), "_drive", "--execution", execution, "--authorization", authorization,
                       "--locales", ",".join(locales), "--out", result_path], launcher=True)
        results = read(result_path)
        blocked = {k: v for k, v in results.items() if v["status"] == "blocked"}
        if blocked:
            raise Stop(f"{label}: Layer 2 blocked {json.dumps(blocked, ensure_ascii=False)}")
        if all(v["status"] == "succeeded" for v in results.values()):
            return results
        time.sleep(5)
        while subprocess.run(["pgrep", "-f", WORKER_PATTERN], capture_output=True).returncode == 0:
            time.sleep(5)
    raise Stop(f"{label}: Layer 2 did not finish after 12 controller ticks")


def stage_layer2(run: Run):
    plans = run.dir / "plans" / "layer2"
    run.plan(plans, ["layer2"], run.spec["locales"], extra=["--layer2-execution", run.l2 / "execution.json"],
             include_open_qc=False)
    if not any((run.l2 / "text").glob("*/candidate.json")):
        run.check("layer2", "--budget-plan", plans, "--spark", "--fresh-dir", run.l2 / "text",
                  "--page-id", run.spec["page"]["pageId"], "--origin", DEV_ORIGIN)
    drive_layer2(run, run.l2 / "execution.json", plans / "layer2/budget-authorization.json", run.spec["locales"], "layer2")
    run.mark("layer2", "done")


# ---------------------------------------------------------------- stages: QC and Layer 2 revisions


def text_qc(run: Run, locale: str, candidate: Path, out_name: str) -> dict:
    root = run.dir / f"textqc-{locale}"
    work, out = root / f"run-{out_name}", root / out_name
    authorization = run.dir / "plans" / f"qc-{locale}" / f"qc-{locale}" / "api-budget-authorization.json"
    run.check(f"qc-{locale}-{out_name}", "--budget-plan", run.dir / "plans" / f"qc-{locale}", "--fresh-dir", out)
    (work / "policies").mkdir(parents=True, exist_ok=True)
    (work / locale).mkdir(exist_ok=True)
    shutil.copyfile(run.l2 / "src/source.json", work / "source.json")
    shutil.copyfile(run.l2 / "src/anchor.json", work / "anchor.json")
    shutil.copyfile(run.l2 / "policy" / f"{locale}-policy-clip.json", work / "policies" / f"{locale}-policy-clip.json")
    shutil.copyfile(candidate, work / locale / "candidate.json")
    run.sh(f"text-qc.{locale}.{out_name}",
           [PY, ROOT / "tools/ops/run.py", "review.qc_text_run", "--run-dir", work, "--out", out, "--state-dir", root / "state",
            "--locales", locale, "--text-backend", "api", "--api-budget-authorization", authorization,
            "--workers", 8, "--expected-implementation", run.impl()], launcher=True, check=False)
    summary = read(out / "summary.json")["locales"][locale]
    waivers = [p for p in (out / locale).glob("text-waiver-*.json") if not p.name.endswith(".inputs.json")]
    return {"status": summary["status"], "failedGroups": summary.get("failedGroups"),
            "receipt": summary.get("textQcReceipt"), "waiverDir": str(out / locale) if waivers else None}


def revise(run: Run, locale: str, receipt: str, number: int) -> Path:
    """A Layer 2 revision of one locale carrying its failed QC receipt (execution v5, gate 4)."""
    from scripts import tongxing_host  # noqa: F401  binds the production package ports
    from tongxing_production.text import controller
    schema = getattr(controller, "QC_REPAIR_SCHEMA", None)
    require(schema is not None, "QC repair needs execution schema v5 (PR #402)")
    revision = run.dir / f"l2-{locale}-r{number}"
    base = read(run.l2 / "execution.json")
    if not (revision / "execution.json").exists():
        write(revision / "execution.json", {
            "schemaVersion": schema, "productionRunId": base["productionRunId"], "inspectionConfig": "../l2/inspection.json",
            "jobRoot": "../l2/layer2-jobs", "locales": {locale: {"outputDirectory": f"text/{locale}",
                                                                 "plugin": base["locales"][locale]["plugin"]}},
            "layer2AutoRepair": {**base["layer2AutoRepair"], "maxActiveLocales": 1,
                                 "backTranslationQc": {locale: str(Path(receipt).resolve())}}})
    plans = run.dir / "plans" / f"layer2-{locale}-r{number}"
    run.plan(plans, ["layer2"], [locale], extra=["--layer2-execution", revision / "execution.json"])
    drive_layer2(run, revision / "execution.json", plans / "layer2/budget-authorization.json", [locale],
                 f"layer2-{locale}-r{number}")
    return revision / "text" / locale / "candidate.json"


def stage_qc(run: Run, locale: str):
    """Text QC; a failed candidate goes back to Layer 2 once per revision, never re-checked unchanged.

    Resume-safe: a candidate whose QC is already recorded is not checked again (a recorded
    ``requires_repair`` goes straight to its revision), and the candidate a revision produced is
    recorded before it is checked."""
    run.plan(run.dir / "plans" / f"qc-{locale}", [f"qc.{locale}"], [locale],
             extra=["--qc-inputs", run.l2 / "qc-inputs.json"])
    state = run.stages.get("qc." + locale) or {}
    history = list(state.get("history", []))
    candidate = run.candidate(locale)
    while True:
        last = history[-1] if history else None
        if last is not None and last["candidate"] == str(candidate):
            result = last
        else:
            out_name = "out" if not history else f"out-r{len(history)}"
            result = {"candidate": str(candidate), "out": out_name, **text_qc(run, locale, candidate, out_name)}
            history.append(result)
            run.mark("qc." + locale, "running", history=history, candidate=str(candidate))
        if result["status"] == "text_waiver_issued":
            run.mark("qc." + locale, "done", history=history, candidate=str(candidate), waiverDir=result["waiverDir"])
            return
        revisions = len(history) - 1
        if result["status"] != "requires_repair" or revisions >= run.spec["qc"]["maxRevisions"]:
            run.mark("qc." + locale, "failed", history=history, candidate=str(candidate))
            raise Stop(f"qc.{locale}: {result['status']} after {revisions} revision(s); failed {result['failedGroups']}")
        candidate = revise(run, locale, result["receipt"], revisions + 1)
        run.mark("qc." + locale, "running", history=history, candidate=str(candidate))


# ---------------------------------------------------------------- stages: Spark


def ensure_session(run: Run):
    if run.session_up:
        return
    env = {"SPARK_EXCLUSIVE_SESSION_ID": run.spec["spark"]["sessionId"],
           "SPARK_EXCLUSIVE_SESSION_OWNER": run.spec["spark"]["owner"]}
    os.environ.update(env)
    for attempt in range(1, 4):
        # begin may need a second call while Spark services stop; every attempt keeps its own output.
        done = run.sh(f"spark-begin-{attempt}", [PY, ROOT / "scripts/spark_exclusive_session.py", "begin",
                                                  "--session-id", env["SPARK_EXCLUSIVE_SESSION_ID"],
                                                  "--owner", env["SPARK_EXCLUSIVE_SESSION_OWNER"]], check=False)
        if done.returncode == 0:
            run.session_up = True
            return
        time.sleep(30)
    raise Stop("Spark exclusive session did not begin; see logs/spark-begin-*.log")


def finish_session(run: Run):
    if run.session_up:
        run.sh("spark-finish", [PY, ROOT / "scripts/spark_exclusive_session.py", "finish",
                                "--session-id", run.spec["spark"]["sessionId"], "--owner", run.spec["spark"]["owner"]])
        run.session_up = False


def stage_code(run: Run) -> str:
    code = "repo-" + run.head()[:8]
    from scripts.clip_e2e_spark import Spark
    spark = Spark(run.runtime["host"])
    target = f"{run.stage_dir}/{code}"
    if "present" not in spark.out(f"test -d {target} && echo present || true"):
        archive = subprocess.run(["git", "-C", str(ROOT), "archive", "HEAD"], check=True, capture_output=True).stdout
        subprocess.run(["ssh", "-o", "BatchMode=yes", run.runtime["host"],
                        f"mkdir -p {target}.partial && tar -x -C {target}.partial && mv {target}.partial {target}"],
                       input=archive, check=True)
    return code


def attestation(run: Run, locale: str) -> Path:
    from scripts import tongxing_host  # noqa: F401  binds the production package ports
    from tongxing_production.source import sentence_interpretation as interp
    path = run.dir / "l3" / locale / "clip-user-rights-attestation.json"
    if not path.exists():
        template = read(run.spec["layer3"]["attestationTemplates"][locale])
        stamp = now()
        template.update(englishSourcePackageJsonSha256=interp.json_sha256(read(run.l2 / "src/source.json")),
                        targetLocales=[locale], recordedAt=stamp, attestedAt=stamp,
                        userStatement=run.spec["authorization"]["evidence"]
                        + f" Dev clip from {Path(run.spec['clipSpec']).name}, inside the window the source attestation covers.")
        write(path, template)
    return path


def mirror_run_to_spark(run: Run):
    relative = run.dir.relative_to((ROOT / "artifacts").resolve())
    mirror = f"{run.stage_dir}/mac-artifacts/{relative}"
    subprocess.run(["ssh", "-o", "BatchMode=yes", run.runtime["host"],
                    "mkdir -p -- " + shlex.quote(mirror)], check=True)
    subprocess.run(["rsync", "-a", "-e", "ssh", "--exclude", "logs/", f"{run.dir}/",
                    f"{run.runtime['host']}:{mirror}/"], check=True)


def stage_audio(run: Run, locale: str, code: str):
    l3, q = run.dir / "l3" / locale, run.stages["qc." + locale]
    candidate, waiver_dir = Path(q["candidate"]), Path(q["waiverDir"])
    waiver = next(p for p in waiver_dir.glob("text-waiver-*.json") if not p.name.endswith(".inputs.json"))
    adapter = ROOT / "config/layer3-adapters" / f"adapter-{locale}.json"
    policy = run.l2 / "policy" / f"{locale}-policy-clip.json"
    src, anchor, timeline = run.l2 / "src/source.json", run.l2 / "src/anchor.json", run.dir / "l3/clip-timeline-map.json"
    registry = Path(run.spec["layer3"]["speakerRegistry"])
    voice = l3 / "clip-voice-authorization.json"
    job_dir = l3 / "speech-job"
    if not (job_dir / "job.json").exists():
        run.sh(f"voice-auth.{locale}", [PY, ROOT / "scripts/prepare_clip_voice_authorization.py", "--source", src,
                                        "--candidate", candidate, "--adapter", adapter,
                                        "--user-attestation", attestation(run, locale), "--out", voice])
        run.sh(f"speech-job.{locale}", [PY, ROOT / "tools/ops/run.py", "audio.speech_job",
                                        "--english-source-package", src, "--anchor", anchor, "--candidate", candidate,
                                        "--policy", policy, "--text-release-basis", waiver, "--adapter", adapter,
                                        "--speaker-registry", registry, "--clip-voice-authorization", voice,
                                        "--clip-timeline-map", timeline, "--out", job_dir])
    run.check(f"gpu-{locale}", "--budget-plan", run.dir / "plans" / f"qc-{locale}", "--spark-stages",
              "--spark-code-dir", f"{run.stage_dir}/{code}")
    inputs = ["--source", src, "--anchor", anchor, "--candidate", candidate, "--policy", policy,
              "--human-review-receipt", waiver, "--speaker-registry", registry, "--adapter", adapter,
              "--clip-voice-authorization", voice, "--clip-timeline-map", timeline,
              "--audio-operation-policies", ROOT / "config/layer3-audio-operation-policies.json"]
    spark = [PY, ROOT / "scripts/clip_e2e_spark.py"]
    common = ["--locale", locale, "--stage", run.stage_dir, "--code", code]
    raw, compacted = f"{locale}-raw", f"{locale}-c"
    lag = str(run.spec["layer3"]["maxEndLagSeconds"])
    if not (l3 / "dispatch.result.json").exists():
        # The renderer exits 1 when its own unit screening flags units; the ASR screen below decides.
        run.sh(f"render.{locale}", [*spark, "render", *common, "--job", job_dir / "job.json", *inputs,
                                    "--remote-name", raw, "--max-end-lag-seconds", lag], check=False)
        require(read(l3 / "dispatch.result.json")["outcome"] == "known_terminal", f"render.{locale}: unknown outcome")
    compact_job = l3 / f"spark-{compacted}" / "speech-job" / "job.json"
    if not (l3 / f"compact-{compacted}.result.json").exists():
        run.sh(f"compact.{locale}", [*spark, "compact", *common, "--job", job_dir / "job.json", *inputs,
                                     "--raw-name", raw, "--remote-name", compacted, "--max-end-lag-seconds", lag,
                                     "--trim-trailing", "--padding-seconds", "0.03", "--inter-utterance-gap-seconds", "0",
                                     "--reaction-lag-seconds", "0", "--tail-overrun-seconds", "1.0"])
    # compact reads its root back into l3/<locale>/spark-<name>/; screen reads the screened root back
    # beside the job it ran on, under that directory's spark-output/.
    compacted_local = l3 / f"spark-{compacted}"
    if not (compacted_local / "screen-v1.result.json").exists():
        run.sh(f"screen.{locale}", [*spark, "screen", *common, "--job", compact_job, "--remote-name", compacted,
                                    "--batch-size", "1", "--tag", "v1"])
    rendered = compacted_local / "spark-output" / "speech-job"
    package = l3 / "audio-package.json"
    if not package.exists():
        run.sh(f"package.{locale}", [PY, ROOT / "tools/ops/run.py", "audio.package", "--source", src,
                                     "--anchor", anchor, "--candidate", candidate, "--job", rendered / "job.json",
                                     "--adapter", adapter, "--policy", policy, "--human-review-receipt", waiver,
                                     "--speaker-registry", registry, "--clip-voice-authorization", voice,
                                     "--clip-timeline-map", timeline,
                                     "--render-manifest", rendered / "render-manifest-screened-v1.json",
                                     "--artifact-root", rendered, "--out", package])
    qc_run = run.dir / "aqc" / f"run-{locale}"
    for directory in (qc_run / locale, qc_run / "policies", qc_run / "l3"):
        directory.mkdir(parents=True, exist_ok=True)
    for source_path, target in ((src, qc_run / "source.json"), (anchor, qc_run / "anchor.json"),
                                (policy, qc_run / "policies" / policy.name), (candidate, qc_run / locale / "candidate.json"),
                                (waiver, qc_run / locale / waiver.name), (package, qc_run / "l3/audio-package.json"),
                                (rendered / "asr-screening-receipt-v1.json", qc_run / "l3/asr-screening-receipt-v1.json"),
                                (rendered / "render-manifest-screened-v1.json", qc_run / "l3/render-manifest-screened-v1.json"),
                                (rendered / "job.json", qc_run / "l3/speech-job.json")):
        shutil.copyfile(source_path, target)
    mirror_run_to_spark(run)
    out = run.dir / "aqc" / locale
    authorization = run.dir / "plans" / f"qc-{locale}" / f"qc-{locale}" / "api-budget-authorization.json"
    run.sh(f"audio-qc.{locale}", [*spark, "audio-qc", *common, "--audio-package", package,
                                  "--state-dir", run.dir / f"textqc-{locale}" / "state",
                                  "--api-budget-authorization", authorization, "--out", out, "--run-dir", qc_run,
                                  "--openai-environment", run.spec["openai"]["environment"], "--max-api-calls", "150"],
           check=False)
    summary = read(out / "summary.json")["locales"][locale]
    if summary.get("status") != "audio_waiver_issued":
        run.mark("audio." + locale, "failed", qcStatus=summary.get("status"), failedGroups=summary.get("failedGroups"),
                 nextActions=summary.get("nextActions"))
        raise Stop(f"audio.{locale}: {summary.get('status')} {summary.get('failedGroups')} {summary.get('reason')}")
    run.mark("audio." + locale, "done", package=str(package), audioQcOut=str(out / locale))


def repair_audio(run: Run, locale: str, seed: int, code: str, *, unit_instructions: Path | None = None):
    """Re-render a failed locale in a fresh root and recheck against its existing repair ledger."""
    key = "audio." + locale
    prior = run.stages.get(key) or {}
    require(prior.get("status") == "failed", f"{key} has no terminal failure to repair")
    require(prior.get("nextActions") and set(prior["nextActions"].values()) == {"resynthesize_new_seed"},
            f"{key} does not call for a new TTS seed")
    attempts = list(prior.get("repairAttempts") or [])
    instruction_sha = hashlib.sha256(unit_instructions.read_bytes()).hexdigest() if unit_instructions else None
    require(type(seed) is int and seed >= 0 and seed != 42, "repair seed must differ from the original seed 42")
    require(not attempts or seed not in [a["seed"] for a in attempts[:-1]], "repair seed was used earlier")
    require(not attempts or attempts[-1]["seed"] == seed or attempts[-1]["status"] == "failed",
            "reconcile the current repair attempt before using another seed")
    require(not attempts or attempts[-1]["seed"] != seed
            or attempts[-1].get("unitInstructionsSha256") == instruction_sha,
            "repair instructions differ from the frozen attempt")
    if not attempts or attempts[-1]["seed"] != seed:
        attempts.append({"seed": seed, "status": "running", "startedAt": now(),
                         "failedGroupsBefore": prior.get("failedGroups"),
                         "unitInstructionsSha256": instruction_sha})
    run.mark(key, "failed", **{k: v for k, v in prior.items() if k not in ("status", "at", "repairAttempts")},
             repairAttempts=attempts)

    l3 = run.dir / "l3" / locale
    repair = run.dir / "l3" / f"{locale}-repair-seed-{seed}"
    q = run.stages["qc." + locale]
    candidate, waiver_dir = Path(q["candidate"]), Path(q["waiverDir"])
    waiver = next(p for p in waiver_dir.glob("text-waiver-*.json") if not p.name.endswith(".inputs.json"))
    adapter = ROOT / "config/layer3-adapters" / f"adapter-{locale}.json"
    policy = run.l2 / "policy" / f"{locale}-policy-clip.json"
    src, anchor = run.l2 / "src/source.json", run.l2 / "src/anchor.json"
    timeline = run.dir / "l3/clip-timeline-map.json"
    registry = Path(run.spec["layer3"]["speakerRegistry"])
    voice = l3 / "clip-voice-authorization.json"
    job = repair / "speech-job" / "job.json"
    job.parent.mkdir(parents=True, exist_ok=True)
    original_job = l3 / "speech-job" / "job.json"
    if job.exists():
        require(job.read_bytes() == original_job.read_bytes(), "repair speech job differs from frozen original")
    else:
        shutil.copyfile(original_job, job)
    repair_plan = run.dir / "plans" / f"qc-{locale}-audio-seed-{seed}"
    run.check(f"gpu-{locale}-seed-{seed}", "--budget-plan", repair_plan,
              "--spark-stages", "--spark-code-dir", f"{run.stage_dir}/{code}")
    inputs = ["--source", src, "--anchor", anchor, "--candidate", candidate, "--policy", policy,
              "--human-review-receipt", waiver, "--speaker-registry", registry, "--adapter", adapter,
              "--clip-voice-authorization", voice, "--clip-timeline-map", timeline,
              "--audio-operation-policies", ROOT / "config/layer3-audio-operation-policies.json"]
    spark = [PY, ROOT / "scripts/clip_e2e_spark.py"]
    common = ["--locale", locale, "--stage", run.stage_dir, "--code", code]
    raw, compacted = f"{locale}-seed-{seed}-raw", f"{locale}-seed-{seed}-c"
    lag = str(run.spec["layer3"]["maxEndLagSeconds"])
    if not (repair / "dispatch.result.json").exists():
        run.sh(f"render.{locale}.seed-{seed}", [*spark, "render", *common, "--job", job, *inputs,
               "--remote-name", raw, "--max-end-lag-seconds", lag, "--seed", str(seed),
               *(["--unit-instructions", unit_instructions] if unit_instructions else [])], check=False)
    require(read(repair / "dispatch.result.json")["outcome"] == "known_terminal",
            f"render.{locale}.seed-{seed}: unknown outcome")
    if not (repair / f"compact-{compacted}.result.json").exists():
        run.sh(f"compact.{locale}.seed-{seed}", [*spark, "compact", *common, "--job", job, *inputs,
               "--raw-name", raw, "--remote-name", compacted, "--max-end-lag-seconds", lag,
               "--trim-trailing", "--padding-seconds", "0.03", "--inter-utterance-gap-seconds", "0",
               "--reaction-lag-seconds", "0", "--tail-overrun-seconds", "1.0"])
    compacted_local = repair / f"spark-{compacted}"
    compact_job = compacted_local / "speech-job" / "job.json"
    if not (compacted_local / "screen-v1.result.json").exists():
        run.sh(f"screen.{locale}.seed-{seed}", [*spark, "screen", *common, "--job", compact_job,
               "--remote-name", compacted, "--batch-size", "1", "--tag", "v1"])
    rendered = compacted_local / "spark-output" / "speech-job"
    package = repair / "audio-package.json"
    if not package.exists():
        run.sh(f"package.{locale}.seed-{seed}", [PY, ROOT / "tools/ops/run.py", "audio.package",
               "--source", src, "--anchor", anchor, "--candidate", candidate, "--job", rendered / "job.json",
               "--adapter", adapter, "--policy", policy, "--human-review-receipt", waiver,
               "--speaker-registry", registry, "--clip-voice-authorization", voice,
               "--clip-timeline-map", timeline, "--render-manifest", rendered / "render-manifest-screened-v1.json",
               "--artifact-root", rendered, "--out", package])
    qc_run = run.dir / "aqc" / f"run-{locale}-seed-{seed}"
    for directory in (qc_run / locale, qc_run / "policies", qc_run / "l3"):
        directory.mkdir(parents=True, exist_ok=True)
    for source_path, target in ((src, qc_run / "source.json"), (anchor, qc_run / "anchor.json"),
                                (policy, qc_run / "policies" / policy.name), (candidate, qc_run / locale / "candidate.json"),
                                (waiver, qc_run / locale / waiver.name), (package, qc_run / "l3/audio-package.json"),
                                (rendered / "asr-screening-receipt-v1.json", qc_run / "l3/asr-screening-receipt-v1.json"),
                                (rendered / "render-manifest-screened-v1.json", qc_run / "l3/render-manifest-screened-v1.json"),
                                (rendered / "job.json", qc_run / "l3/speech-job.json")):
        if target.exists():
            require(target.read_bytes() == source_path.read_bytes(), f"repair QC input changed: {target}")
        else:
            shutil.copyfile(source_path, target)
    mirror_run_to_spark(run)
    out = run.dir / "aqc" / f"{locale}-seed-{seed}"
    authorization = repair_plan / f"qc-{locale}" / "api-budget-authorization.json"
    if not (out / "summary.json").exists():
        run.sh(f"audio-qc.{locale}.seed-{seed}", [*spark, "audio-qc", *common, "--audio-package", package,
               "--state-dir", run.dir / f"textqc-{locale}" / "state", "--api-budget-authorization", authorization,
               "--out", out, "--run-dir", qc_run, "--openai-environment", run.spec["openai"]["environment"],
               "--max-api-calls", "150"], check=False)
    summary = read(out / "summary.json")["locales"][locale]
    attempts[-1].update(status="done" if summary.get("status") == "audio_waiver_issued" else "failed",
                        finishedAt=now(), qcStatus=summary.get("status"), failedGroups=summary.get("failedGroups"),
                        package=str(package), audioQcOut=str(out / locale))
    if summary.get("status") != "audio_waiver_issued":
        run.mark(key, "failed", qcStatus=summary.get("status"), failedGroups=summary.get("failedGroups"),
                 nextActions=summary.get("nextActions"), repairAttempts=attempts)
        raise Stop(f"{key} seed {seed}: {summary.get('status')} {summary.get('failedGroups')} {summary.get('reason')}")
    run.mark(key, "done", package=str(package), audioQcOut=str(out / locale),
             repairedFrom=prior.get("failedGroups"), repairAttempts=attempts)


# ---------------------------------------------------------------- stages: Layer 4 and report


def stage_layer4(run: Run):
    from scripts import clip_e2e_release
    spec, l4 = run.spec, run.dir / "l4"
    page = spec["page"]
    if not (l4 / "prepare-result.json").exists():
        clip = read(spec["clipSpec"])
        lanes = {k: {"candidate": run.stages["qc." + k]["candidate"], "textQcOut": run.stages["qc." + k]["waiverDir"],
                     "audioPackage": run.stages["audio." + k]["package"], "audioQcOut": run.stages["audio." + k]["audioQcOut"]}
                 for k in spec["locales"]}
        result = clip_e2e_release.prepare(l4, page_id=page["pageId"], date=clip["serviceDate"], locales=spec["locales"],
                                          source_path=run.l2 / "src/source.json", anchor_path=run.l2 / "src/anchor.json",
                                          lanes=lanes, display=page["display"],
                                          default_pass=spec["authorization"]["defaultPass"])
        require(result["status"] == "succeeded", f"layer4 prepare: {result}")
    if not (l4 / "baseline").exists():
        cache = (["--cache-public", page["baselineCachePublic"], "--cache-receipt", page["baselineCacheReceipt"]]
                 if page.get("baselineCachePublic") else [])
        run.sh("layer4-baseline", [PY, ROOT / "scripts/prepare_dev_simulated_publication.py", "baseline",
                                   "--environment", "dev", "--out", l4 / "baseline", *cache])
    if not run.publish:
        run.mark("layer4", "prepared_not_published")
        raise Stop("layer4 prepared; publishing to Dev Hosting needs --publish")
    workflow = l4 / "workflow"
    state_path = workflow / "workflow-state.json"
    if not state_path.exists():
        if workflow.exists() and any(workflow.iterdir()):
            raise Stop("Layer 4 publish files exist without a terminal receipt; reconcile before retry")
        run.sh("layer4-publish", [PY, ROOT / "scripts/run_dev_simulated_delivery.py", "--baseline", l4 / "baseline",
                                  "--prepared", l4 / "work/prepared", "--out", workflow, "--machine-checked", "--execute"])
    state = read(state_path)
    report_path = workflow / "run-report.json"
    report = read(report_path) if report_path.exists() else {}
    inputs = state.get("inputs") or {}
    sha = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
    expected = (("preparedManifestSha256", l4 / "work/prepared/preparation-manifest.json"),
                ("baselineReceiptSha256", l4 / "baseline/baseline-receipt.json"),
                ("baselineSealSha256", l4 / "baseline/seal-report.json"))
    if (state.get("status") != "diagnostic_dev_http_verified"
            or report.get("status") != state["status"] or report.get("inputs") != inputs
            or inputs.get("pageId") != page["pageId"]
            or (inputs.get("target") or {}).get("origin") != DEV_ORIGIN
            or inputs.get("contentMode") != "machine_checked"
            or any(not path.is_file() or inputs.get(key) != sha(path) for key, path in expected)
            or any((state.get("stages") or {}).get(stage, {}).get("status") != "succeeded"
                   for stage in ("publish_assets", "verify_assets", "publish_catalog", "live_readback"))):
        raise Stop("Layer 4 publish receipt needs reconciliation; refusing to deploy again")

    def passed_smoke(path):
        try:
            receipt = read(path)
            return (receipt.get("status") == "pass" and receipt.get("pageId") == page["pageId"]
                    and receipt.get("origin") == DEV_ORIGIN
                    and {row["locale"] for row in receipt.get("locales", []) if row.get("status") == "pass"}
                    == set(spec["locales"])
                    and datetime.fromisoformat(receipt["checkedAt"]) >= datetime.fromisoformat(state["completedAt"]))
        except (OSError, ValueError, KeyError, TypeError):
            return False

    receipts = sorted(l4.glob("browser-smoke*.json"), key=lambda path: path.stat().st_mtime, reverse=True)
    smoke = next((path for path in receipts if passed_smoke(path)), None)
    if smoke is None:
        smoke = l4 / f"browser-smoke-retry-{len(receipts) + 1}.json"
        run.sh("layer4-smoke", [PY, ROOT / "scripts/smoke_published_page.py", "--origin", DEV_ORIGIN, "--page-id",
                                page["pageId"], "--settle-ms", "15000", "--no-session", "--out", smoke])
        require(passed_smoke(smoke), "Layer 4 browser smoke did not pass")
    run.mark("layer4", "done", pageId=page["pageId"], smoke="pass", smokeReceipt=str(smoke),
             workflowReceipt=str(workflow / "run-report.json"))


def stage_report(run: Run):
    name = datetime.now(timezone.utc).strftime("%Y%m%d") + "-clip-e2e-" + run.spec["name"]
    run.sh("report", [PY, ROOT / "scripts/export_run_digest.py", run.dir, "--name", name])
    run.mark("report", "done", name=name)


# ---------------------------------------------------------------- driver


def execute(run: Run, *, through: str | None = None) -> dict:
    spec = run.spec
    order = ["inputs", "layer2-setup", "layer2", *[f"qc.{k}" for k in spec["locales"]],
             *[f"audio.{k}" for k in spec["locales"]], "layer4", "report"]
    if through:
        require(through in order, "unknown stage")
        order = order[:order.index(through) + 1]
    simple = {"inputs": stage_inputs, "layer2-setup": stage_layer2_setup, "layer2": stage_layer2,
              "layer4": stage_layer4, "report": stage_report}
    stopped = []
    code = None
    try:
        for name in order:
            if run.done(name):
                continue
            recorded = run.stages.get(name) or {}
            if recorded.get("status") == "failed":
                # A terminal QC or audio failure is evidence to read, never a stage to retry blindly.
                stopped.append(f"{name}: failed earlier ({ {k: v for k, v in recorded.items() if k != 'history'} })")
                continue
            if name.startswith("qc."):
                try:
                    stage_qc(run, name[3:])
                except Stop as stop:
                    stopped.append(str(stop))  # other locales go on; their caps stay counted while open
                continue
            if name.startswith("audio."):
                locale = name[6:]
                if not run.done("qc." + locale):
                    continue
                if code is None:
                    ensure_session(run)
                    code = stage_code(run)
                try:
                    stage_audio(run, locale, code)
                except Stop as stop:
                    stopped.append(str(stop))
                continue
            if name == "layer4":
                finish_session(run)
                missing = [k for k in spec["locales"] if not run.done("audio." + k)]
                if missing:
                    stopped.append(f"layer4 needs every locale; not finished: {missing}")
                    break
            simple[name](run)
    except Stop as stop:
        stopped.append(str(stop))
    finally:
        finish_session(run)
    summary = {"run": str(run.dir), "stages": run.stages, "stopped": stopped, "settledUsd": run.settled()}
    write(run.dir / "summary.json", summary)
    return summary


def _route(out: Path):
    """Inside the explicit launcher: the non-secret route and the credential fingerprint."""
    from scripts import tongxing_host  # noqa: F401  binds the production package ports
    from tongxing_production.review import qc_budget_authorization as auth
    from tongxing_production.compute.openai_runtime import selected_route
    route = selected_route()
    require(route is not None, "run inside scripts/run_with_openai_environment.py")
    write(out, {"openaiRoute": route, "credentialSha256": auth.credential_fingerprint(os.environ["OPENAI_API_KEY"])})


def _drive(execution: Path, authorization: Path, locales: list[str], out: Path):
    from scripts import tongxing_host  # noqa: F401  binds the production package ports
    from tongxing_production.text.controller import drive
    results = {}
    for locale in locales:
        result = drive(execution, locale, budget_authorization=authorization)
        results[locale] = {k: result.get(k) for k in ("status", "reason", "dispatched")}
    write(out, results)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    go = commands.add_parser("run", help="run or resume every stage")
    go.add_argument("--spec", type=Path, required=True)
    go.add_argument("--run-dir", type=Path, required=True, help="New or resumed directory under artifacts/")
    go.add_argument("--through", help="Stop after this stage (e.g. layer2, qc.ko, audio.es, layer4)")
    go.add_argument("--publish", action="store_true", help="Allow the guarded Dev Hosting publish in stage layer4")
    show = commands.add_parser("status", help="print the recorded stages and settled spend")
    show.add_argument("--spec", type=Path, required=True)
    show.add_argument("--run-dir", type=Path, required=True)
    repair = commands.add_parser("repair-audio", help="resume a failed audio locale with a new TTS seed")
    repair.add_argument("--spec", type=Path, required=True)
    repair.add_argument("--run-dir", type=Path, required=True)
    repair.add_argument("--locale", required=True, choices=LOCALES)
    repair.add_argument("--seed", required=True, type=int)
    repair.add_argument("--unit-instructions", type=Path,
                        help="Frozen per-unit delivery instructions under this run directory")
    route = commands.add_parser("_route")
    route.add_argument("--out", type=Path, required=True)
    drive = commands.add_parser("_drive")
    drive.add_argument("--execution", type=Path, required=True)
    drive.add_argument("--authorization", type=Path, required=True)
    drive.add_argument("--locales", required=True)
    drive.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.command == "_route":
        _route(args.out)
        return 0
    if args.command == "_drive":
        _drive(args.execution, args.authorization, args.locales.split(","), args.out)
        return 0
    run = Run(args.spec, args.run_dir, publish=getattr(args, "publish", False))
    if args.command == "status":
        print(json.dumps({"stages": run.stages, "settledUsd": run.settled(), "openQcCapsUsd": run.open_qc_caps()},
                         ensure_ascii=False, indent=1))
        return 0
    if args.command == "repair-audio":
        prior = run.stages.get("audio." + args.locale) or {}
        require(prior.get("status") == "failed",
                "repair requires a recorded terminal audio failure")
        require(prior.get("nextActions") and set(prior["nextActions"].values()) == {"resynthesize_new_seed"},
                "audio QC did not request resynthesize_new_seed")
        require(args.seed >= 0 and args.seed != 42, "repair seed must differ from the original seed 42")
        if args.unit_instructions is not None:
            args.unit_instructions = args.unit_instructions.resolve()
            require(args.unit_instructions.is_file() and args.unit_instructions.is_relative_to(run.dir),
                    "repair instructions must be a file under this run directory")
        run.plan(run.dir / "plans" / f"qc-{args.locale}-audio-seed-{args.seed}",
                 [f"qc.{args.locale}"], [args.locale], extra=["--qc-inputs", run.l2 / "qc-inputs.json"])
        stopped = []
        try:
            ensure_session(run)
            repair_audio(run, args.locale, args.seed, stage_code(run), unit_instructions=args.unit_instructions)
        except Stop as stop:
            stopped.append(str(stop))
        finally:
            finish_session(run)
        summary = {"run": str(run.dir), "stages": run.stages, "stopped": stopped, "settledUsd": run.settled()}
        write(run.dir / "summary.json", summary)
        print(json.dumps({"stopped": stopped, "settledUsd": summary["settledUsd"],
                          "audioStatus": run.stages["audio." + args.locale]["status"]}, ensure_ascii=False))
        return 1 if stopped else 0
    summary = execute(run, through=args.through)
    print(json.dumps({"stopped": summary["stopped"], "settledUsd": summary["settledUsd"],
                      "stages": {k: v["status"] for k, v in summary["stages"].items()}}, ensure_ascii=False, indent=1))
    return 1 if summary["stopped"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
