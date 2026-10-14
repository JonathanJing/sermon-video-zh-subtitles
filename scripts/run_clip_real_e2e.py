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
import math
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

SPEC_SCHEMA = "sermon-clip-real-e2e-run-v1"
SCOPED_REPAIR_SPEC_SCHEMA = "sermon-clip-real-e2e-run-v2"
LOCALES = ("zh-Hans", "ko", "es")
DEV_ORIGIN = "https://ai-for-god-sermon-audio-dev.web.app"
PY = sys.executable
WORKER_PATTERN = "canonical_layer2_controller.py worker"


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
    require(spec.get("schemaVersion") in (SPEC_SCHEMA, SCOPED_REPAIR_SPEC_SCHEMA),
            "unsupported run specification")
    require(set(spec) <= {"schemaVersion", "name", "clipSpec", "locales", "openai", "authorization", "budget", "layer1",
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
    layer1 = spec.setdefault("layer1", {})
    layer1.setdefault("backend", "simulated")
    require(layer1["backend"] in ("simulated", "claude_cli_opus"), "unsupported layer1.backend")
    if layer1["backend"] == "claude_cli_opus":
        require(type(layer1.get("listPriceCapUsd")) in (int, float) and layer1["listPriceCapUsd"] > 0,
                "Opus Layer 1 needs a positive subscription list-price cap")
    layer2, layer3 = spec.get("layer2") or {}, spec.get("layer3") or {}
    layer2.setdefault("backend", "openai_api")
    require(layer2["backend"] in ("openai_api", "claude_cli_opus"),
            "layer2.backend must be openai_api or claude_cli_opus")
    scoped = layer2.get('scopeRegisterRules', [])
    require(isinstance(scoped, list) and len(set(scoped)) == len(scoped) and set(scoped) <= set(locales),
            'layer2.scopeRegisterRules must name distinct run locales')
    cache_sources = layer2.get('initialClaudeCacheSources', {})
    require(isinstance(cache_sources, dict) and set(cache_sources) <= set(locales)
            and (not cache_sources or layer2['backend'] == 'claude_cli_opus'),
            'layer2.initialClaudeCacheSources requires Claude and run locales')
    layer2['initialClaudeCacheSources'] = {k: resolve(v) for k, v in cache_sources.items()}
    if "claudeListPriceCapUsdPerLocale" in layer2:
        cap = layer2["claudeListPriceCapUsdPerLocale"]
        require(layer2["backend"] == "claude_cli_opus" and type(cap) in (int, float)
                and math.isfinite(cap) and 0 < cap <= 100,
                "layer2.claudeListPriceCapUsdPerLocale needs Claude and a cap in (0, 100]")
    repair_fractions = layer2.get("repairSpendFractionByLocale", {})
    require(isinstance(repair_fractions, dict) and set(repair_fractions) <= set(locales)
            and all(type(fraction) in (int, float) and math.isfinite(fraction)
                    and 0.10 <= fraction <= 0.30 for fraction in repair_fractions.values()),
            "layer2.repairSpendFractionByLocale needs run locales and fractions in [0.10, 0.30]")
    require(not repair_fractions or spec["schemaVersion"] == SCOPED_REPAIR_SPEC_SCHEMA,
            "raised Layer 2 repair spend requires run specification v2")
    for field, table in (("policyTemplates", layer2), ("plugins", layer2), ("attestationTemplates", layer3)):
        require(isinstance(table.get(field), dict) and set(locales) <= set(table[field]), f"{field} missing a locale")
        table[field] = {k: resolve(v) for k, v in table[field].items() if k in locales}
    for field in ("adapters", "capabilities"):
        overrides = layer3.get(field, {})
        require(isinstance(overrides, dict) and set(overrides) <= set(locales),
                f"layer3.{field} must name run locales")
        layer3[field] = {k: resolve(v) for k, v in overrides.items()}
    require(isinstance(layer3.get("speakerRegistry"), str), "layer3.speakerRegistry required")
    layer3["speakerRegistry"] = resolve(layer3["speakerRegistry"])
    if layer3.get("audioOperationPolicies"):
        require(isinstance(layer3["audioOperationPolicies"], str),
                "layer3.audioOperationPolicies must be a path")
        layer3["audioOperationPolicies"] = resolve(layer3["audioOperationPolicies"])
    layer3.setdefault("maxEndLagSeconds", 120.0)
    spec["clipSpec"] = resolve(spec["clipSpec"])
    openai = spec.setdefault("openai", {})
    openai.setdefault("environment", "dev")
    require(openai["environment"] in ("dev", "prod"), "openai.environment must be dev or prod")
    require(not repair_fractions or openai["environment"] == "dev",
            "raised Layer 2 repair spend is only supported in isolated Dev runs")
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
    if spark.get("runtimeConfig"):
        spark["runtimeConfig"] = resolve(spark["runtimeConfig"])
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
        runtime_config = self.spec["spark"].get("runtimeConfig")
        self.runtime = (clip_e2e_spark.load_runtime(Path(runtime_config)) if runtime_config
                        else clip_e2e_spark.load_runtime())
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

    def adapter(self, locale: str) -> Path:
        return Path(self.spec["layer3"].get("adapters", {}).get(
            locale, ROOT / "config/layer3-adapters" / f"adapter-{locale}.json"))

    def capability(self, locale: str) -> Path | None:
        value = self.spec["layer3"].get("capabilities", {}).get(locale)
        return Path(value) if value else None

    def spark_command(self) -> list:
        command = [PY, ROOT / "scripts/clip_e2e_spark.py"]
        if self.spec["spark"].get("runtimeConfig"):
            command += ["--runtime", self.spec["spark"]["runtimeConfig"]]
        return command

    def audio_operation_policies(self) -> Path:
        return Path(self.spec["layer3"].get("audioOperationPolicies")
                    or ROOT / "config/layer3-audio-operation-policies.json")

    def impl(self) -> str:
        from scripts import machine_quality_waiver as waiver
        return waiver.implementation_sha256()

    def head(self) -> str:
        return subprocess.run(["git", "-C", str(ROOT), "rev-parse", "HEAD"], check=True, capture_output=True,
                              text=True).stdout.strip()

    # -- budget
    def settled(self) -> float:
        """Approved-dollar spend; Claude subscription list-price equivalents are kept separate."""
        from scripts.export_run_digest import budget_summary
        total = 0
        if self.spec["layer2"]["backend"] == "openai_api":
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

    def claude_list_price_equivalent(self) -> float:
        """Subscription Layer 2 usage at its reserved list-price basis, not cash spend."""
        if self.spec["layer2"]["backend"] != "claude_cli_opus":
            return 0.0
        total = sum(read(path)["result"]["usage"]["costMicrousd"]
                    for path in self.dir.rglob("*.result.json")
                    if "layer2-budget" in str(path) and "responses" not in path.parts)
        return round(total / 1e6, 6)

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
        if "layer2" in stages and "claudeListPriceCapUsdPerLocale" in self.spec["layer2"]:
            argv += ["--claude-list-price-cap-usd-per-locale",
                     self.spec["layer2"]["claudeListPriceCapUsdPerLocale"]]
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
        if run.spec["layer1"]["backend"] == "claude_cli_opus":
            run.sh("inputs", [PY, ROOT / "scripts/prepare_clip_layer1_opus.py", "--clip-spec", run.spec["clipSpec"],
                              "--out", inputs, "--list-price-cap-usd", run.spec["layer1"]["listPriceCapUsd"]])
        else:
            run.sh("inputs", [PY, ROOT / "scripts/build_dev_180s_simulated_inputs.py", "--clip-spec", run.spec["clipSpec"],
                              "--run-id", "clip-e2e-" + run.spec["name"], "--out", inputs])
    if run.spec["layer1"]["backend"] == "claude_cli_opus":
        from scripts import delivery_contract
        layer1 = read(inputs / "layer1-opus-summary.json")
        require(layer1["machineStatus"] == "approved_for_layer2_shadow"
                and layer1["sourcePackageJsonSha256"] == delivery_contract.sha(read(inputs / "source.json")),
                "Opus Layer 1 receipt is missing or changed")
    src = run.l2 / "src"
    src.mkdir(parents=True, exist_ok=True)
    for name in ("source.json", "anchor.json"):
        if not (src / name).exists():
            shutil.copyfile(inputs / name, src / name)
    timeline = run.dir / "l3" / "clip-timeline-map.json"
    if not timeline.exists():
        timeline.parent.mkdir(parents=True, exist_ok=True)
        run.sh("timeline-map", [PY, ROOT / "scripts/clip_timeline_map.py", "--source", src / "source.json",
                                "--anchor", src / "anchor.json", "--clip-media", inputs / "clip/source.mp4",
                                "--out", timeline])
    anchor = read(src / "anchor.json")
    run.mark("inputs", "done", units=len(anchor["sourceUnits"]), inputs=str(inputs),
             layer1Backend=run.spec["layer1"]["backend"])


def clip_plugin(template: Path, policy_template: Path, source: dict, anchor: dict, out: Path) -> Path:
    """Rebind a source-specific weekly plugin to the unchanged units in this test clip."""
    from scripts import produce_target_language_candidate as producer
    from scripts import target_language_policy as tp
    original = read(policy_template)
    require(producer.plugin_implementation_sha256(template) == original['languageReview']['pluginImplementationSha256'],
            'the weekly plugin differs from its frozen policy')
    old = original['sourceScope']
    replacements = {'SOURCE_SHA256': (old['englishSourcePackageJsonSha256'], tp.canonical_sha256(source)),
                    'ANCHOR_SHA256': (old['anchorManifestSha256'], tp.canonical_sha256(anchor))}
    content = template.read_text()
    present = [key for key in replacements if re.search(rf'(?m)^{key}\s*=', content)]
    if not present:
        return template
    require(set(present) == set(replacements), 'source-bound plugin must pin both source and anchor')
    for key, (before, after) in replacements.items():
        pattern = rf'(?m)^({key}\s*=\s*)([\x27\"]){re.escape(before)}\2$'
        content, count = re.subn(pattern, lambda match: match.group(1) + match.group(2) + after + match.group(2), content)
        require(count == 1, f'{key} differs from the weekly policy binding')
    if out.exists():
        require(out.read_text() == content, 'rebased clip plugin changed after freezing')
    else:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(content)
    return out


def scoped_register_rules(rules: list[str], unit_ids: set[str]) -> list[str]:
    """Keep general rules and source-specific evidence that occurs in this complete-unit clip."""
    selected = []
    for rule in rules:
        if 'Pinned approved CUV excerpts for exact English spans, as data: ' in rule:
            prefix, data = rule.split('as data: ', 1)
            entries, end = json.JSONDecoder().raw_decode(data)
            require(isinstance(entries, list), 'invalid pinned CUV rule data')
            kept = [row for row in entries if row['sourceUnitId'] in unit_ids]
            if kept:
                selected.append(prefix + 'as data: ' + json.dumps(kept, ensure_ascii=False)
                                + data[end:])
            continue
        if 'Exact source-unit contextual name interpretations as data: ' in rule:
            before, data = rule.split('Exact source-unit contextual name interpretations as data: ', 1)
            entries, _ = json.JSONDecoder().raw_decode(data)
            require(isinstance(entries, list), 'invalid contextual-name rule data')
            kept = [row for row in entries if row['sourceUnitId'] in unit_ids]
            selected.append(before + ('Exact source-unit contextual name interpretations as data: '
                + json.dumps(kept, ensure_ascii=False)
                + '. These are source-bound agent interpretations, not new human approvals.' if kept else ''))
            continue
        referenced = set(re.findall(r'\b\d+-u\d+\b', rule))
        if not referenced or referenced & unit_ids:
            selected.append(rule)
    require(bool(selected), 'clip removed every language register rule')
    return selected


def freeze_clip_policy(template: Path, source: dict, anchor: dict, *, reviewed_by: str, statement: str,
                       backend: str = "openai_api", plugin: Path | None = None,
                       scope_rules: bool = False) -> dict:
    """The source week's frozen policy narrowed to this clip's source scope and terms, frozen again."""
    from scripts import target_language_policy as tp
    rows = anchor["sourceUnits"]
    observed = tp.source_scoped_proper_names(rows, set())
    frozen = read(template)
    exclusions = sorted(e for e in frozen["sourceScope"]["ordinaryPhraseExclusions"] if e in observed)
    used = sorted(observed - set(exclusions))
    draft = copy.deepcopy(frozen)
    draft.pop("componentSha256")
    draft = tp.apply_layer2_backend(draft, backend)
    if scope_rules:
        draft['languageReview']['registerRules'] = scoped_register_rules(
            draft['languageReview']['registerRules'], {r['sourceUnitId'] for r in rows})
    if plugin is not None:
        from scripts import produce_target_language_candidate as producer
        draft['languageReview']['pluginImplementationSha256'] = producer.plugin_implementation_sha256(plugin)
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
    plugins = {}
    for locale in spec["locales"]:
        template = Path(spec["layer2"]["policyTemplates"][locale])
        plugins[locale] = clip_plugin(Path(spec["layer2"]["plugins"][locale]), template,
                                      source, anchor, l2 / "plugin" / f"{locale}-clip.py")
        path = l2 / "policy" / f"{locale}-policy-clip.json"
        if not path.exists():
            write(path, freeze_clip_policy(template, source, anchor,
                                           reviewed_by=auth["defaultPass"] + "; targets carried from the source week's receipt",
                                           statement=auth["evidence"], backend=spec["layer2"]["backend"],
                                           plugin=plugins[locale],
                                           scope_rules=locale in spec["layer2"].get("scopeRegisterRules", [])))
    if not (l2 / "execution.json").exists():
        write(l2 / "inspection.json", {"schemaVersion": "sermon-canonical-package-inspection-config-v1",
                                       "source": "src/source.json", "anchor": "src/anchor.json",
                                       "locales": {k: {"policy": f"policy/{k}-policy-clip.json"} for k in spec["locales"]}})
        from scripts import canonical_layer2_controller as controller
        from scripts import layer2_auto_repair as auto_repair
        run_id = hashlib.sha256(("clip-real-e2e " + spec["name"] + " " + ",".join(spec["locales"])).encode()).hexdigest()
        write(l2 / "execution.json", {
            "schemaVersion": (controller.DEV_REPAIR_SCHEMA if spec["layer2"].get("repairSpendFractionByLocale")
                              else controller.AUTO_REPAIR_SCHEMA),
            "productionRunId": run_id, "inspectionConfig": "inspection.json",
            "jobRoot": "layer2-jobs",
            "locales": {k: {"outputDirectory": f"text/{k}", "plugin": str(plugins[k])} for k in spec["locales"]},
            "layer2AutoRepair": {"routingVersion": auto_repair.ROUTING_VERSION, "groupWorkers": 8,
                                 "maxActiveLocales": len(spec["locales"]),
                                 **({"repairSpendFractionByLocale": spec["layer2"]["repairSpendFractionByLocale"]}
                                    if spec["layer2"].get("repairSpendFractionByLocale") else {})}})
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


def seed_initial_claude_cache(run: Run, locale: str, source_dir: Path) -> None:
    """Import returned calls with their run identity; the model runner rechecks every fingerprint."""
    from scripts import produce_target_language_candidate as producer
    from scripts import run_target_language_models as models
    from scripts import target_language_policy as tp
    from scripts import sermon_review_contracts as contracts
    source_dir = source_dir.resolve()
    artifacts = (ROOT / 'artifacts').resolve()
    require(str(source_dir).startswith(str(artifacts) + '/')
            and source_dir.name == 'round-001' and source_dir.parent.name == 'repair-rounds',
            'initial Claude cache must be a prior local first-round artifact')
    markers = sorted(source_dir.glob('*.started.json'))
    reconciled = []
    if markers:
        prior_l2 = source_dir.parents[3]
        jobs = list((prior_l2 / 'layer2-jobs').glob('*/state.json'))
        require(jobs and all(read(path).get('status') in {'failed', 'succeeded', 'cancelled'} for path in jobs),
                'prior Claude workers must be terminal before reconciling markers')
        ledgers = list((prior_l2 / '.layer2-jobs.layer2-budget').glob('*/state.json'))
        require(len(ledgers) == 1, 'prior Claude markers need one intact run ledger')
        ledger, _ = contracts.read_snapshot(ledgers[0], max_bytes=8 * 1024 * 1024)
        operation_ids = {row['request']['operationId'] for row in ledger['reservations'].values()}
        for marker in markers:
            stem = marker.name.removesuffix('.started.json')
            fingerprint = read(marker).get('payloadSha256')
            require(isinstance(fingerprint, str) and re.fullmatch(r'[0-9a-f]{64}', fingerprint)
                    and 'model.' + fingerprint not in operation_ids
                    and not (source_dir / f'{stem}.json').exists()
                    and not (source_dir / f'{stem}.raw.json').exists(),
                    'prior Claude marker may have reached a paid call; reconcile separately')
            reconciled.append({'marker': marker.name,
                'markerSha256': hashlib.sha256(marker.read_bytes()).hexdigest(),
                'result': 'not_dispatched_no_budget_reservation'})
        reconciled.append({'ledger': str(ledgers[0]),
                           'ledgerSha256': hashlib.sha256(ledgers[0].read_bytes()).hexdigest()})
    source, anchor = read(run.l2 / 'src/source.json'), read(run.l2 / 'src/anchor.json')
    policy = read(run.l2 / 'policy' / f'{locale}-policy-clip.json')
    request = producer.prepare_request(source, anchor, policy, candidate_mode='production')
    require(read(source_dir / 'request.json') == request, 'prior Claude request differs from the frozen clip')
    prior_rules = read(source_dir / 'rule-preflight.json')
    require(prior_rules['translationPolicySha256'] == tp.canonical_sha256(policy)
            and prior_rules['englishSourcePackageJsonSha256'] == tp.canonical_sha256(source)
            and prior_rules['anchorManifestSha256'] == tp.canonical_sha256(anchor)
            and prior_rules['pluginImplementationSha256'] == policy['languageReview']['pluginImplementationSha256'],
            'prior Claude rules differ from the frozen clip')
    listing = [source_dir / name for name in ('run-identity.json', 'request.json', 'rule-preflight.json')]
    require(all(path.is_file() for path in listing), 'prior Claude run identity is incomplete')
    for index, _ in enumerate(models.group_plan(request, anchor), 1):
        for suffix, role in (('astra', 'translator'), ('sol', 'reviewer')):
            stem = f'group-{index:04d}-{suffix}'
            cache, raw = source_dir / f'{stem}.json', source_dir / f'{stem}.raw.json'
            require(cache.is_file() == raw.is_file(), f'incomplete returned Claude pair: {stem}')
            if not cache.is_file():
                continue
            saved, returned = read(cache), read(raw)
            require(saved.get('payloadSha256') == returned.get('payloadSha256')
                    and saved.get('model') == policy[role]['model']
                    and saved.get('requestId') == returned.get('response', {}).get('id')
                    and isinstance(saved.get('result'), dict)
                    and type((returned.get('response', {}).get('claudeCli') or {}).get('listPriceUsd')) in (int, float),
                    f'invalid returned Claude pair: {stem}')
            listing.extend((cache, raw))
    require(len(listing) > 3, 'prior Claude run has no complete returned calls')
    destination = run.l2 / 'text' / locale / 'repair-rounds' / 'round-001'
    manifest = destination / 'initial-cache-import.json'
    identity = {'schemaVersion': 'sermon-clip-initial-claude-cache-import-v1',
                'sourceDirectory': str(source_dir), 'requestSha256': tp.canonical_sha256(request),
                'policySha256': tp.canonical_sha256(policy), 'reconciledMarkers': reconciled,
                'files': [{'name': path.name, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
                          for path in listing]}
    if manifest.exists():
        require(read(manifest) == identity and all(
            hashlib.sha256((destination / row['name']).read_bytes()).hexdigest() == row['sha256']
            for row in identity['files']), 'imported Claude cache changed')
        return
    require(not destination.exists() or not any(destination.iterdir()),
            'initial Claude cache destination already has unrelated files')
    destination.mkdir(parents=True, exist_ok=True)
    for path in listing:
        shutil.copy2(path, destination / path.name)
    write(manifest, identity)


def stage_layer2(run: Run):
    plans = run.dir / "plans" / "layer2"
    run.plan(plans, ["layer2"], run.spec["locales"], extra=["--layer2-execution", run.l2 / "execution.json"],
             include_open_qc=False)
    if not any((run.l2 / "text").glob("*/candidate.json")) and not (run.l2 / 'layer2-jobs').exists():
        run.check("layer2", "--budget-plan", plans, "--spark", "--fresh-dir", run.l2 / "text",
                  "--page-id", run.spec["page"]["pageId"], "--origin", DEV_ORIGIN)
        for locale, path in run.spec['layer2'].get('initialClaudeCacheSources', {}).items():
            seed_initial_claude_cache(run, locale, Path(path))
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
           [PY, ROOT / "scripts/run_machine_qc_clip_test.py", "--run-dir", work, "--out", out, "--state-dir", root / "state",
            "--locales", locale, "--text-backend", "api", "--api-budget-authorization", authorization,
            "--workers", 8, "--expected-implementation", run.impl()], launcher=True, check=False)
    summary = read(out / "summary.json")["locales"][locale]
    waivers = [p for p in (out / locale).glob("text-waiver-*.json") if not p.name.endswith(".inputs.json")]
    return {"status": summary["status"], "failedGroups": summary.get("failedGroups"),
            "receipt": summary.get("textQcReceipt"), "waiverDir": str(out / locale) if waivers else None}


def revision_repair_binding(base: dict, locale: str, receipt: str) -> dict:
    """Keep only the selected locale's scoped allowance in a single-lane QC revision."""
    binding = {**base, "maxActiveLocales": 1, "backTranslationQc": {locale: receipt}}
    fractions = base.get("repairSpendFractionByLocale", {})
    if fractions:
        if locale in fractions:
            binding["repairSpendFractionByLocale"] = {locale: fractions[locale]}
        else:
            binding.pop("repairSpendFractionByLocale", None)
    return binding


def revise(run: Run, locale: str, receipt: str, number: int) -> Path:
    """A Layer 2 revision of one locale carrying its failed QC receipt (execution v5, gate 4)."""
    from scripts import canonical_layer2_controller as controller
    schema = getattr(controller, "DEV_REPAIR_SCHEMA" if run.spec["layer2"].get("repairSpendFractionByLocale")
                     else "QC_REPAIR_SCHEMA", None)
    require(schema is not None, "QC repair needs execution schema v5 (PR #402)")
    revision = run.dir / f"l2-{locale}-r{number}"
    base = read(run.l2 / "execution.json")
    if not (revision / "execution.json").exists():
        write(revision / "execution.json", {
            "schemaVersion": schema, "productionRunId": base["productionRunId"], "inspectionConfig": "../l2/inspection.json",
            "jobRoot": "../l2/layer2-jobs", "locales": {locale: {"outputDirectory": f"text/{locale}",
                                                                 "plugin": base["locales"][locale]["plugin"]}},
            "layer2AutoRepair": revision_repair_binding(base["layer2AutoRepair"], locale,
                                                          str(Path(receipt).resolve()))})
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
    # Validate the single-lane revision shape before buying the first QC pass.
    # Its actual QC receipt path is bound only after that pass exists.
    from scripts import canonical_layer2_controller as controller
    if (run.l2 / "execution.json").is_file():
        base_execution = read(run.l2 / "execution.json")
        controller._auto_repair_binding(
            revision_repair_binding(base_execution["layer2AutoRepair"], locale, "pending-qc-receipt.json"),
            allow_qc=True, allow_scoped_fraction=base_execution["schemaVersion"] == controller.DEV_REPAIR_SCHEMA)
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
        try:
            candidate = revise(run, locale, result["receipt"], revisions + 1)
        except Stop as stop:
            # A durable revision job has terminated; do not leave the QC stage
            # looking active or retry that job on the next driver invocation.
            status = "failed" if "failed_durable_job" in str(stop) else "blocked"
            run.mark("qc." + locale, status, history=history, candidate=str(candidate), reason=str(stop))
            raise
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
    from scripts import sermon_sentence_interpretation as interp
    path = run.dir / "l3" / locale / "clip-user-rights-attestation.json"
    if not path.exists():
        template = read(run.spec["layer3"]["attestationTemplates"][locale])
        clip = read(run.spec["clipSpec"])
        full_source = read(clip["englishSourcePackage"]["path"])
        source = read(run.l2 / "src/source.json")
        require(template.get("schemaVersion") == "sermon-source-user-voice-attestation-v2"
                and template.get("permissionClaimed") is True
                and bool(template.get("userStatement", "").strip())
                and template.get("sourceId") == clip["sourceId"] == source["source"]["sourceId"]
                == full_source["source"]["sourceId"]
                and template.get("sourceMediaSha256") == full_source["source"]["media"]["sha256"]
                and template.get("approvedWindow") == {
                    key: full_source["source"]["approvedWindow"][key] for key in ("startSeconds", "endSeconds")}
                and clip["approvedWindowStartSeconds"] == template["approvedWindow"]["startSeconds"]
                and locale in template.get("targetLocales", []),
                "source voice permission is not bound to this approved clip")
        template_path = Path(run.spec["layer3"]["attestationTemplates"][locale])
        stamp = now()
        write(path, {
            "schemaVersion": "sermon-clip-user-rights-attestation-v1",
            "scope": "isolated-clip-test-dev-app-and-audio_only",
            "englishSourcePackageJsonSha256": interp.json_sha256(source),
            "targetLocales": [locale],
            "speakerId": template["speakerId"],
            "voiceCheckpointSha256": template["voiceCheckpointSha256"],
            "permissionClaimed": True,
            "userStatement": template["userStatement"],
            "taskAuthorizationEvidence": run.spec["authorization"]["evidence"],
            "derivedFrom": {"path": str(template_path.resolve()),
                            "sha256": hashlib.sha256(template_path.read_bytes()).hexdigest()},
            "recordedAt": stamp,
            "attestedAt": stamp,
        })
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
    adapter = run.adapter(locale)
    capability = run.capability(locale)
    capability_args = ["--clip-voice-capability", capability] if capability else []
    policy = run.l2 / "policy" / f"{locale}-policy-clip.json"
    src, anchor, timeline = run.l2 / "src/source.json", run.l2 / "src/anchor.json", run.dir / "l3/clip-timeline-map.json"
    registry = Path(run.spec["layer3"]["speakerRegistry"])
    voice = l3 / "clip-voice-authorization.json"
    job_dir = l3 / "speech-job"
    if not (job_dir / "job.json").exists():
        run.sh(f"voice-auth.{locale}", [PY, ROOT / "scripts/prepare_clip_voice_authorization.py", "--source", src,
                                        "--candidate", candidate, "--adapter", adapter,
                                        "--user-attestation", attestation(run, locale), "--out", voice])
        run.sh(f"speech-job.{locale}", [PY, ROOT / "scripts/prepare_target_language_speech_job.py",
                                        "--english-source-package", src, "--anchor", anchor, "--candidate", candidate,
                                        "--policy", policy, "--text-release-basis", waiver, "--adapter", adapter,
                                        "--speaker-registry", registry, "--clip-voice-authorization", voice,
                                        *capability_args,
                                        "--clip-timeline-map", timeline, "--out", job_dir])
    from scripts import render_formal_target_language_speech as renderer
    renderer.validate_operation_policies(read(run.audio_operation_policies()), read(adapter),
                                         read(job_dir / "job.json"))
    require(run.runtime["speaker"]["id"] == read(adapter)["speakerId"]
            and run.runtime["speaker"]["checkpointRef"] == read(adapter)["conditioningRef"],
            "Spark runtime speaker differs from the speech adapter")
    run.check(f"gpu-{locale}", "--budget-plan", run.dir / "plans" / f"qc-{locale}", "--spark-stages",
              "--spark-code-dir", f"{run.stage_dir}/{code}")
    inputs = ["--source", src, "--anchor", anchor, "--candidate", candidate, "--policy", policy,
              "--human-review-receipt", waiver, "--speaker-registry", registry, "--adapter", adapter,
              "--clip-voice-authorization", voice, "--clip-timeline-map", timeline,
              "--audio-operation-policies", run.audio_operation_policies(),
              *capability_args]
    spark = run.spark_command()
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
        run.sh(f"package.{locale}", [PY, ROOT / "scripts/build_target_language_audio_package.py", "--source", src,
                                     "--anchor", anchor, "--candidate", candidate, "--job", rendered / "job.json",
                                     "--adapter", adapter, "--policy", policy, "--human-review-receipt", waiver,
                                     "--speaker-registry", registry, "--clip-voice-authorization", voice,
                                     *capability_args,
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
    adapter = run.adapter(locale)
    capability = run.capability(locale)
    capability_args = ["--clip-voice-capability", capability] if capability else []
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
    from scripts import render_formal_target_language_speech as renderer
    renderer.validate_operation_policies(read(run.audio_operation_policies()), read(adapter), read(job))
    require(run.runtime["speaker"]["id"] == read(adapter)["speakerId"]
            and run.runtime["speaker"]["checkpointRef"] == read(adapter)["conditioningRef"],
            "Spark runtime speaker differs from the speech adapter")
    repair_plan = run.dir / "plans" / f"qc-{locale}-audio-seed-{seed}"
    run.check(f"gpu-{locale}-seed-{seed}", "--budget-plan", repair_plan,
              "--spark-stages", "--spark-code-dir", f"{run.stage_dir}/{code}")
    inputs = ["--source", src, "--anchor", anchor, "--candidate", candidate, "--policy", policy,
              "--human-review-receipt", waiver, "--speaker-registry", registry, "--adapter", adapter,
              "--clip-voice-authorization", voice, "--clip-timeline-map", timeline,
              "--audio-operation-policies", run.audio_operation_policies(),
              *capability_args]
    spark = run.spark_command()
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
        run.sh(f"package.{locale}.seed-{seed}", [PY, ROOT / "scripts/build_target_language_audio_package.py",
               "--source", src, "--anchor", anchor, "--candidate", candidate, "--job", rendered / "job.json",
               "--adapter", adapter, "--policy", policy, "--human-review-receipt", waiver,
               "--speaker-registry", registry, "--clip-voice-authorization", voice,
               *capability_args,
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
    digest = ROOT / "artifacts/run-reports" / name
    if digest.exists():
        manifest = read(digest / "manifest.json")
        require(manifest.get("name") == name and
                [row.get("label") for row in manifest.get("runs", [])] == [run.dir.name],
                "existing run digest does not match this run")
        run.sh("report-verify", [PY, ROOT / "scripts/export_run_digest.py", digest, "--verify"])
    else:
        run.sh("report", [PY, ROOT / "scripts/export_run_digest.py", run.dir, "--name", name])
    run.mark("report", "done", reportName=name)


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
    summary = {"run": str(run.dir), "stages": run.stages, "stopped": stopped, "settledUsd": run.settled(),
               "claudeListPriceEquivalentUsd": run.claude_list_price_equivalent()}
    write(run.dir / "summary.json", summary)
    return summary


def _route(out: Path):
    """Inside the explicit launcher: the non-secret route and the credential fingerprint."""
    from scripts import machine_qc_budget_authorization as auth
    from scripts.sermon_openai_runtime import selected_route
    route = selected_route()
    require(route is not None, "run inside scripts/run_with_openai_environment.py")
    write(out, {"openaiRoute": route, "credentialSha256": auth.credential_fingerprint(os.environ["OPENAI_API_KEY"])})


def _drive(execution: Path, authorization: Path, locales: list[str], out: Path):
    from scripts.canonical_layer2_controller import drive
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
        print(json.dumps({"stages": run.stages, "settledUsd": run.settled(),
                          "claudeListPriceEquivalentUsd": run.claude_list_price_equivalent(),
                          "openQcCapsUsd": run.open_qc_caps()},
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
        summary = {"run": str(run.dir), "stages": run.stages, "stopped": stopped, "settledUsd": run.settled(),
                   "claudeListPriceEquivalentUsd": run.claude_list_price_equivalent()}
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
