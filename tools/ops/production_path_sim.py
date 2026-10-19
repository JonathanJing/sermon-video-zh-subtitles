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
two human gates (text review, audio review).  It does not claim to
reproduce every retry of a real run.  Run it with ``--calibrate`` to see
the observed 2026-10-18 baseline.
"""

from __future__ import annotations

import argparse
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


# ---------------------------------------------------------------------------
# Resource timeline


class Resource:
    """A renewable resource with integer capacity."""

    def __init__(self, capacity: int, name: str = "resource") -> None:
        self.capacity = capacity
        self.name = name
        self.reservations: list[tuple[float, float, int]] = []

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
        candidates = {start}
        for busy_start, busy_end, _ in self.reservations:
            if busy_end > start:
                candidates.add(busy_end)
        for candidate in sorted(candidates):
            if self._free_for(candidate, duration, units):
                return candidate
        raise RuntimeError(f"no slot found for {self.name}")

    def reserve(self, start: float, duration: float, units: int = 1) -> None:
        self.reservations.append((start, start + duration, units))

    def busy_minutes(self) -> float:
        return sum((end - start) * units for start, end, units in self.reservations)


# ---------------------------------------------------------------------------
# Rework sampling


def sample_text_rework(scenario: Scenario, locale: Locale, rng: random.Random) -> float:
    if scenario.rework == "systemic":
        return 50.0 if rng.random() < 0.5 else 0.0
    if scenario.rework == "whole":
        return 17.0 if rng.random() < 0.3 else 0.0
    if scenario.rework == "group":
        failures = sum(1 for _ in range(locale.groups) if rng.random() < 0.05)
        return failures * 0.65 / 16.0
    return 0.0


def sample_tts_rework(scenario: Scenario, groups: int, rng: random.Random) -> float:
    if scenario.rework == "whole":
        return 14.0 if rng.random() < 0.2 else 0.0
    if scenario.rework == "group":
        failures = sum(1 for _ in range(groups) if rng.random() < 0.03)
        return failures * 0.269 / 8.0
    if scenario.rework == "systemic":
        return 14.0 if rng.random() < 0.2 else 0.0
    return 0.0


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


def simulate_once(scenario: Scenario, seed: int) -> RunResult:
    rng = random.Random(seed)
    durations = scenario.durations
    api = Resource(16, "api")
    human = Resource(1, "human")
    spark = Resource(1, "spark")
    deploy = Resource(1, "deploy")

    l1_end = durations.l1
    pages: dict[str, float] = {}
    text_pages: dict[str, float] = {}
    deferred_audio: list[tuple[str, float, float]] = []

    for locale in scenario.locales:
        if locale.locale_id in scenario.prebuilt:
            pages[locale.locale_id] = 0.0
            continue
        base_text = scenario.text_override.get(locale.locale_id, durations.text)
        text_duration = base_text + sample_text_rework(scenario, locale, rng)
        text_start = api.earliest(l1_end, text_duration, 16)
        api.reserve(text_start, text_duration, 16)
        text_end = text_start + text_duration

        if scenario.text_review:
            review_start_request = (
                text_start + text_duration / 8.0
                if scenario.text_mode == "stream"
                else text_end
            )
            review_start = human.earliest(
                review_start_request, durations.text_review, 1
            )
            human.reserve(review_start, durations.text_review, 1)
            review_end = review_start + durations.text_review
            if scenario.text_mode == "stream":
                review_end = max(
                    review_end, text_end + durations.text_review / 8.0
                )
        else:
            review_start = review_end = text_end

        if scenario.text_mode == "stream" and scenario.text_review:
            tts_request = max(
                text_start + text_duration / 8.0,
                review_start + durations.text_review / 8.0,
            )
        elif scenario.text_mode == "stream":
            tts_request = text_start + text_duration / 8.0
        else:
            tts_request = max(text_end, review_end)

        tts_duration = durations.tts + sample_tts_rework(
            scenario, locale.groups, rng
        )
        tts_start = spark.earliest(tts_request, tts_duration, 1)
        spark.reserve(tts_start, tts_duration, 1)
        if scenario.text_mode == "stream":
            tts_end = max(
                tts_start + tts_duration,
                review_end + tts_duration / 8.0,
            )
        else:
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
            text_deploy_start = deploy.earliest(review_end, durations.deploy, 1)
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
        api_busy=api.busy_minutes(),
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
        overhead=58.0,
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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trials", type=int, default=2000)
    parser.add_argument("--seed", type=int, default=20261018)
    parser.add_argument("--audio", choices=["spot", "full", "none"])
    parser.add_argument("--text-review", choices=["human", "none"])
    parser.add_argument("--sweep", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
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
