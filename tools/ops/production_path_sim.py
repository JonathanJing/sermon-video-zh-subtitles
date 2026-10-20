#!/usr/bin/env python3
"""Compare production path archetypes for one weekly sermon.

This is a planning simulator, not a production runner.  It models the
observed 2026-10-18 stages with a small resource-constrained list
scheduler and compares:

* the current batch, layer-by-layer family release;
* batch per-locale pages;
* per-group streaming with per-locale pages;
* per-group streaming with a text-first page and a later audio update.

The model is deliberately coarse: it keeps the critical resources (API
workers, the Spark TTS window, the operator and the deploy lane) and the
two human gates (text review, audio review).  Streaming paths schedule each
group: groups finish translation in waves of API workers, are reviewed one by
one as they arrive, and render in TTS batch windows once every member is
reviewed.  It does not claim to reproduce every retry of a real run.

A "page" here is the text/audio release of one locale (or the family page)
being deployed.  Layer 4 study products (per-locale outline and meditation
and their human approvals) are not modeled, so a four-product page needs
those on top, including on the machine-checked path.

    .venv/bin/python tools/ops/production_path_sim.py [--trials N] [--audio full] [--sweep]
    .venv/bin/python tools/ops/production_path_sim.py --calibrate

``--calibrate`` compares ``batch_family_actual`` with the observed
2026-10-18 baseline (158 minutes from video to the Chinese page).
"""

from __future__ import annotations

import argparse
import heapq
import json
import math
import random
import statistics
from dataclasses import dataclass, field, replace
from typing import Iterable

# ---------------------------------------------------------------------------
# Observed stage constants (minutes).  Defaults come from the 2026-10-18 run.


@dataclass(frozen=True)
class StageDurations:
    l1: float = 15.0
    text: float = 17.0
    text_review: float = 28.8
    tts: float = 14.0
    post: float = 5.0
    audio_spot: float = 3.0
    audio_full: float = 33.0
    text_package: float = 5.0
    deploy: float = 5.0
    announce: float = 2.0
    family_deploy: float = 5.0


@dataclass(frozen=True)
class Locale:
    locale_id: str
    groups: int


@dataclass(frozen=True)
class Scenario:
    name: str
    description: str
    page_mode: str  # family | separate | text_first
    text_mode: str  # barrier | stream
    rework: str  # none | whole | systemic | group
    audio_review: str = "spot"  # spot | full | none
    text_review: bool = True
    overhead: float = 0.0
    text_override: dict[str, float] = field(default_factory=dict)
    prebuilt: tuple[str, ...] = ()
    audio_minutes_override: float | None = None
    locales: tuple[Locale, ...] = (
        Locale("zh-Hans", 416),
        Locale("es", 402),
        Locale("ko", 402),
    )
    durations: StageDurations = field(default_factory=StageDurations)

    def __post_init__(self) -> None:
        allowed = {"stream": {"none", "group"}, "barrier": {"none", "whole", "systemic"}}[self.text_mode]
        if self.rework not in allowed:
            raise ValueError(f"{self.text_mode} text does not model {self.rework!r} rework")


# API workers translating groups at once, and the TTS renderer's batch window.
API_WORKERS = 16
TTS_BATCH = 8


# ---------------------------------------------------------------------------
# Resource timeline


class Resource:
    """A renewable resource with integer capacity."""

    def __init__(self, capacity: int, name: str = "resource") -> None:
        self.capacity = capacity
        self.name = name
        self.reservations: list[tuple[float, float, int]] = []
        self.horizon = 0.0

    def _free_for(self, start: float, duration: float, units: int) -> bool:
        end = start + duration
        used = 0
        for busy_start, busy_end, busy_units in self.reservations:
            if busy_end <= start or busy_start >= end:
                continue
            used += busy_units
        return used + units <= self.capacity

    def earliest(self, start: float, duration: float, units: int = 1) -> float:
        """Return the earliest time >= start with units free for duration."""
        if start >= self.horizon:
            return start
        candidates = {start}
        for busy_start, busy_end, _ in self.reservations:
            if busy_end > start:
                candidates.add(busy_end)
        for candidate in sorted(candidates):
            if self._free_for(candidate, duration, units):
                return candidate
        raise RuntimeError(f"no slot found for {self.name}")

    def reserve(self, start: float, duration: float, units: int = 1) -> None:
        # Back-to-back per-group work extends the last reservation, so the
        # timeline stays short when hundreds of groups are scheduled one by one.
        self.horizon = max(self.horizon, start + duration)
        if self.reservations:
            last_start, last_end, last_units = self.reservations[-1]
            if last_units == units and abs(last_end - start) < 1e-9:
                self.reservations[-1] = (last_start, start + duration, units)
                return
        self.reservations.append((start, start + duration, units))

    def busy_minutes(self) -> float:
        return sum((end - start) * units for start, end, units in self.reservations)


# ---------------------------------------------------------------------------
# Rework sampling
#
# "whole" and "systemic" are whole-text reruns: the operator finds the problem
# during text review, the text is regenerated, and the changed Layer 2
# evidence is reviewed again in full.  "group" fails single groups: a text
# failure found in review regenerates and re-reviews that group alone; a TTS
# failure re-renders the group's batch window, because batch members stay in
# the voice identity (the DEV-GRP-005 A/B did not pass, 2026-10-19).

WHOLE_TEXT_RERUN = {"whole": (0.3, 17.0), "systemic": (0.5, 50.0)}
WHOLE_TTS_RERUN = {"whole": 0.2, "systemic": 0.2}
GROUP_TEXT_FAILURE = 0.05
GROUP_TTS_FAILURE = 0.03


def sample_text_rerun(scenario: Scenario, rng: random.Random) -> float:
    """Minutes of whole-text regeneration found in review (0 when none)."""
    probability, minutes = WHOLE_TEXT_RERUN.get(scenario.rework, (0.0, 0.0))
    return minutes if probability and rng.random() < probability else 0.0


def sample_group_failures(scenario: Scenario, groups: int, probability: float,
                          rng: random.Random) -> list[bool]:
    if scenario.rework != "group":
        return [False] * groups
    return [rng.random() < probability for _ in range(groups)]


def sample_tts_rerun(scenario: Scenario, durations: StageDurations, rng: random.Random) -> float:
    probability = WHOLE_TTS_RERUN.get(scenario.rework, 0.0)
    return durations.tts if probability and rng.random() < probability else 0.0


def audio_review_minutes(scenario: Scenario, durations: StageDurations) -> float:
    if scenario.audio_minutes_override is not None:
        return scenario.audio_minutes_override
    if scenario.audio_review == "none":
        return 0.0
    if scenario.audio_review == "full":
        return durations.audio_full
    return durations.audio_spot


# ---------------------------------------------------------------------------
# One simulated run


@dataclass
class RunResult:
    first_page: float
    first_page_locale: str
    pages: dict[str, float]
    text_pages: dict[str, float]
    human_busy: float
    spark_busy: float
    api_busy: float
    deploy_busy: float


def _review_groups(human: Resource, arrivals: list[float], unit: float,
                   failed: list[bool], redo: float) -> list[float]:
    """Review groups in arrival order; a failed group is regenerated and reviewed again.

    A regenerated group goes ahead of the groups still waiting, so its batch
    window is not held back to the end.  Returns when each group's final
    review ends."""
    order = sorted(range(len(arrivals)), key=arrivals.__getitem__)
    retries: list[tuple[float, int]] = []
    done = [0.0] * len(arrivals)
    free, position = 0.0, 0
    while position < len(order) or retries:
        if retries and (retries[0][0] <= free or position == len(order)
                        or retries[0][0] <= arrivals[order[position]]):
            arrival, group = heapq.heappop(retries)
            retried = True
        else:
            group = order[position]
            arrival, retried = arrivals[group], False
            position += 1
        start = human.earliest(max(free, arrival), unit)
        human.reserve(start, unit)
        free = start + unit
        if failed[group] and not retried:
            heapq.heappush(retries, (free + redo, group))
        else:
            done[group] = free
    return done


def _render_groups(spark: Resource, ready: list[float], unit: float,
                   failed: list[bool]) -> float:
    """Render batch windows as their groups become ready; return the last end."""
    end = 0.0
    for first in range(0, len(ready), TTS_BATCH):
        window = range(first, min(len(ready), first + TTS_BATCH))
        duration = unit * len(window) * (2 if any(failed[i] for i in window) else 1)
        start = spark.earliest(max(end, max(ready[i] for i in window)), duration)
        spark.reserve(start, duration)
        end = start + duration
    return end


def simulate_once(scenario: Scenario, seed: int) -> RunResult:
    rng = random.Random(seed)
    durations = scenario.durations
    api = Resource(API_WORKERS, "api")
    human = Resource(1, "human")
    spark = Resource(1, "spark")
    deploy = Resource(1, "deploy")
    api_redo = 0.0

    l1_end = durations.l1
    pages: dict[str, float] = {}
    text_pages: dict[str, float] = {}
    deferred_audio: list[tuple[str, float, float]] = []

    for locale in scenario.locales:
        if locale.locale_id in scenario.prebuilt:
            pages[locale.locale_id] = 0.0
            continue
        groups = locale.groups
        base_text = scenario.text_override.get(locale.locale_id, durations.text)
        # One group takes text_unit on one of the API workers; review and TTS
        # are the observed whole-locale times spread evenly over the groups.
        text_unit = base_text * API_WORKERS / groups
        review_unit = durations.text_review / groups
        tts_unit = durations.tts / groups
        text_failed = sample_group_failures(scenario, groups, GROUP_TEXT_FAILURE, rng)
        tts_failed = sample_group_failures(scenario, groups, GROUP_TTS_FAILURE, rng)
        rerun = sample_text_rerun(scenario, rng)

        text_start = api.earliest(l1_end, base_text, API_WORKERS)
        api.reserve(text_start, base_text, API_WORKERS)
        text_end = text_start + base_text

        if scenario.text_mode == "stream":
            # Groups finish in waves of API_WORKERS; each is reviewed (and
            # rendered) as soon as it is ready.
            arrivals = [text_start + (index // API_WORKERS + 1) * text_unit for index in range(groups)]
            if scenario.text_review:
                ready = _review_groups(human, arrivals, review_unit, text_failed, text_unit)
            else:
                ready = [arrival + (text_unit if text_failed[i] else 0.0)
                         for i, arrival in enumerate(arrivals)]
            api_redo += text_unit * sum(text_failed)
            review_end = max(ready)
            tts_end = _render_groups(spark, ready, tts_unit, tts_failed)
        else:
            if scenario.text_review:
                review_start = human.earliest(text_end, durations.text_review)
                human.reserve(review_start, durations.text_review)
                review_end = review_start + durations.text_review
                if rerun:
                    # The rerun changes the Layer 2 evidence, so it is reviewed again.
                    rerun_start = api.earliest(review_end, rerun, API_WORKERS)
                    api.reserve(rerun_start, rerun, API_WORKERS)
                    again = human.earliest(rerun_start + rerun, durations.text_review)
                    human.reserve(again, durations.text_review)
                    review_end = again + durations.text_review
            else:
                review_end = text_end
                if rerun:
                    rerun_start = api.earliest(text_end, rerun, API_WORKERS)
                    api.reserve(rerun_start, rerun, API_WORKERS)
                    review_end = rerun_start + rerun
            tts_duration = durations.tts + sample_tts_rerun(scenario, durations, rng)
            tts_start = spark.earliest(review_end, tts_duration)
            spark.reserve(tts_start, tts_duration)
            tts_end = tts_start + tts_duration

        post_end = tts_end + durations.post

        audio_duration = audio_review_minutes(scenario, durations)
        if audio_duration and scenario.page_mode == "family":
            # A family page waits for every locale; a rational operator
            # reviews all text before listening to audio.  Defer audio
            # reviews so they do not block later text reviews.
            deferred_audio.append((locale.locale_id, post_end, audio_duration))
            audio_end = post_end
        elif audio_duration:
            audio_start = human.earliest(post_end, audio_duration, 1)
            human.reserve(audio_start, audio_duration, 1)
            audio_end = audio_start + audio_duration
        else:
            audio_end = post_end

        if scenario.page_mode == "text_first":
            # A text-only release still needs its Layer 3 audio_unavailable
            # package (no producer exists yet; its duration is an assumption).
            package_end = review_end + durations.text_package
            text_deploy_start = deploy.earliest(package_end, durations.deploy, 1)
            deploy.reserve(text_deploy_start, durations.deploy, 1)
            text_pages[locale.locale_id] = (
                text_deploy_start + durations.deploy + scenario.overhead
            )

        if scenario.page_mode == "family":
            pages[locale.locale_id] = audio_end
        else:
            deploy_start = deploy.earliest(audio_end, durations.deploy, 1)
            deploy.reserve(deploy_start, durations.deploy, 1)
            pages[locale.locale_id] = (
                deploy_start + durations.deploy + scenario.overhead
            )

    if scenario.page_mode == "family":
        for locale_id, post_end, audio_duration in deferred_audio:
            audio_start = human.earliest(post_end, audio_duration, 1)
            human.reserve(audio_start, audio_duration, 1)
            pages[locale_id] = audio_start + audio_duration
        family_start = deploy.earliest(
            max(pages.values()), durations.family_deploy, 1
        )
        deploy.reserve(family_start, durations.family_deploy, 1)
        family_page = family_start + durations.family_deploy + scenario.overhead
        pages = {locale.locale_id: family_page for locale in scenario.locales}
        first_page, first_locale = family_page, "family"
    elif scenario.page_mode == "text_first":
        first_locale = min(text_pages, key=text_pages.get)
        first_page = text_pages[first_locale]
    else:
        first_locale = min(pages, key=pages.get)
        first_page = pages[first_locale]

    return RunResult(
        first_page=first_page,
        first_page_locale=first_locale,
        pages=pages,
        text_pages=text_pages,
        human_busy=human.busy_minutes(),
        spark_busy=spark.busy_minutes(),
        api_busy=api.busy_minutes() + api_redo,
        deploy_busy=deploy.busy_minutes(),
    )


# ---------------------------------------------------------------------------
# Monte Carlo summary


def percentile(values: Iterable[float], pct: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    index = (len(ordered) - 1) * pct / 100.0
    lower = math.floor(index)
    upper = math.ceil(index)
    if lower == upper:
        return ordered[int(index)]
    weight = index - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def simulate(scenario: Scenario, trials: int, seed: int) -> dict:
    results = [simulate_once(scenario, seed + i) for i in range(trials)]
    first = [r.first_page for r in results]
    first_audio = [min(r.pages.values()) for r in results]
    all_pages = [max(r.pages.values()) for r in results]
    return {
        "scenario": scenario.name,
        "description": scenario.description,
        "first_p50": percentile(first, 50),
        "first_p90": percentile(first, 90),
        "first_audio_p50": percentile(first_audio, 50),
        "first_audio_p90": percentile(first_audio, 90),
        "all_p50": percentile(all_pages, 50),
        "all_p90": percentile(all_pages, 90),
        "human_busy": statistics.mean(r.human_busy for r in results),
        "spark_busy": statistics.mean(r.spark_busy for r in results),
        "api_busy": statistics.mean(r.api_busy for r in results),
        "deploy_busy": statistics.mean(r.deploy_busy for r in results),
    }


def _with_durations(scenario: Scenario, **kwargs: float) -> Scenario:
    return replace(scenario, durations=replace(scenario.durations, **kwargs))


def sweep_rows(trials: int, seed: int) -> dict[str, list[dict]]:
    """One-parameter sweeps for the four paths that matter."""

    base = {
        "batch_family": SCENARIOS["batch_family_clean"],
        "batch_separate": SCENARIOS["batch_separate_clean"],
        "stream_separate": SCENARIOS["stream_separate"],
        "stream_textfirst": SCENARIOS["stream_textfirst"],
    }
    out: dict[str, list[dict]] = {}

    text_review_values = [0.0, 15.0, 30.0, 45.0, 60.0]
    rows = []
    for value in text_review_values:
        row = {"value": value, "paths": {}}
        for name, scenario in base.items():
            changed = _with_durations(scenario, text_review=value)
            if value == 0:
                changed = replace(changed, text_review=False)
            row["paths"][name] = simulate(changed, trials, seed)["first_p50"]
        rows.append(row)
    out["text_review"] = rows

    audio_values = [0.0, 3.0, 10.0, 33.0]
    rows = []
    for value in audio_values:
        row = {"value": value, "paths": {}}
        for name, scenario in base.items():
            changed = replace(scenario, audio_minutes_override=value)
            row["paths"][name] = simulate(changed, trials, seed)["first_audio_p50"]
        rows.append(row)
    out["audio_review"] = rows

    deploy_values = [5.0, 10.0, 20.0, 30.0]
    rows = []
    for value in deploy_values:
        row = {"value": value, "paths": {}}
        for name, scenario in base.items():
            changed = _with_durations(
                scenario, deploy=value, family_deploy=value
            )
            row["paths"][name] = simulate(changed, trials, seed)["first_p50"]
        rows.append(row)
    out["deploy"] = rows

    tts_values = [10.0, 14.0, 20.0, 28.0]
    rows = []
    for value in tts_values:
        row = {"value": value, "paths": {}}
        for name, scenario in base.items():
            changed = _with_durations(scenario, tts=value)
            row["paths"][name] = simulate(changed, trials, seed)["first_p50"]
        rows.append(row)
    out["tts"] = rows
    return out


def format_sweep_markdown(sweeps: dict[str, list[dict]]) -> str:
    titles = {
        "text_review": "文字审稿（分钟）",
        "audio_review": "音频审听（分钟，影响首个音频页）",
        "deploy": "部署（分钟）",
        "tts": "TTS（分钟）",
    }
    lines: list[str] = []
    for key, rows in sweeps.items():
        lines.append(f"### {titles[key]}")
        lines.append("")
        lines.append("| 值 | 整篇 family | 独立页 | 逐组独立页 | 逐组文字先行 |")
        lines.append("|---:|---:|---:|---:|---:|")
        for row in rows:
            p = row["paths"]
            lines.append(
                "| {value:.0f} | {batch_family:.1f} | {batch_separate:.1f} | "
                "{stream_separate:.1f} | {stream_textfirst:.1f} |".format(
                    value=row["value"], **p
                )
            )
        lines.append("")
    return "\n".join(lines)


SCENARIOS: dict[str, Scenario] = {
    "batch_family_clean": Scenario(
        name="batch_family_clean",
        description="整篇串行、三语同一页面，无返工",
        page_mode="family",
        text_mode="barrier",
        rework="none",
    ),
    "batch_family_rework": Scenario(
        name="batch_family_rework",
        description="整篇串行、三语同一页面，含整篇返工",
        page_mode="family",
        text_mode="barrier",
        rework="whole",
    ),
    "batch_family_actual": Scenario(
        name="batch_family_actual",
        description="按 2026-10-18 实际中文 L2 67 分钟与集成开销校准",
        page_mode="family",
        text_mode="stream",
        rework="none",
        overhead=62.0,
        text_override={"zh-Hans": 67.0},
        prebuilt=("es", "ko"),
    ),
    "batch_separate": Scenario(
        name="batch_separate",
        description="整篇串行、每语独立页面",
        page_mode="separate",
        text_mode="barrier",
        rework="whole",
    ),
    "batch_separate_clean": Scenario(
        name="batch_separate_clean",
        description="整篇串行、每语独立页面，无返工",
        page_mode="separate",
        text_mode="barrier",
        rework="none",
    ),
    "stream_separate": Scenario(
        name="stream_separate",
        description="逐组流式、每语独立页面",
        page_mode="separate",
        text_mode="stream",
        rework="group",
    ),
    "stream_textfirst": Scenario(
        name="stream_textfirst",
        description="逐组流式、先发文字页、音频后补",
        page_mode="text_first",
        text_mode="stream",
        rework="group",
    ),
}


def run_all(trials: int, seed: int = 20261018) -> list[dict]:
    return [simulate(scenario, trials, seed) for scenario in SCENARIOS.values()]


def format_markdown(rows: list[dict]) -> str:
    lines = [
        "| 场景 | 首个页面 P50 | 首个页面 P90 | 首个音频页 P50 | 全部页面 P50 | 人工占用 | Spark 占用 | API 占用 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in rows:
        lines.append(
            "| {scenario} | {first_p50:.1f} | {first_p90:.1f} | "
            "{first_audio_p50:.1f} | {all_p50:.1f} | {human_busy:.1f} | "
            "{spark_busy:.1f} | {api_busy:.1f} |".format(**row)
        )
    return "\n".join(lines)


# 2026-10-18: video at 07:04, Chinese page live at 09:42.
OBSERVED_FIRST_PAGE_MINUTES = 158.0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--trials", type=int, default=2000)
    parser.add_argument("--seed", type=int, default=20261018)
    parser.add_argument("--audio", choices=["spot", "full", "none"])
    parser.add_argument("--text-review", choices=["human", "none"])
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--sweep", action="store_true",
                      help="one-parameter sweeps of the default scenarios (no --audio/--text-review)")
    mode.add_argument("--calibrate", action="store_true",
                      help="compare batch_family_actual with the observed 2026-10-18 run")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    if (args.sweep or args.calibrate) and (args.audio or args.text_review):
        # Sweeps and the calibration vary or pin these settings themselves.
        parser.error("--audio and --text-review apply to the scenario table only")
    if args.calibrate:
        row = simulate(SCENARIOS["batch_family_actual"], args.trials, args.seed)
        result = {"scenario": row["scenario"], "simulatedFirstPageMinutes": round(row["first_p50"], 1),
                  "observedFirstPageMinutes": OBSERVED_FIRST_PAGE_MINUTES,
                  "overheadMinutes": SCENARIOS["batch_family_actual"].overhead}
        print(json.dumps(result, ensure_ascii=False, indent=None if not args.json else 2))
        return 0
    scenarios = list(SCENARIOS.values())
    if args.audio:
        scenarios = [replace(s, audio_review=args.audio) for s in scenarios]
    if args.text_review == "none":
        scenarios = [replace(s, text_review=False) for s in scenarios]
    if args.sweep:
        sweeps = sweep_rows(args.trials, args.seed)
        if args.json:
            print(json.dumps(sweeps, ensure_ascii=False, indent=2))
        else:
            print(format_sweep_markdown(sweeps))
        return 0
    rows = [simulate(s, args.trials, args.seed) for s in scenarios]
    if args.json:
        print(json.dumps(rows, ensure_ascii=False, indent=2))
    else:
        print(format_markdown(rows))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
