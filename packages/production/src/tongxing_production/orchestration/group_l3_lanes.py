"""Run several locales' Layer 3 stage plans as lanes that share one GPU.

Each lane is one locale's ``sermon-group-l3-stages-v1`` plan and its own output directory;
its stages still run in order through group_l3.run_stages. Across lanes, stages marked
``gpu`` take turns on a single GPU slot (the Spark 8x8 render saturates the GPU, so two
renders at once gain nothing and would not fit the memory admission); stages marked ``cpu``
(compaction, packaging, copies) run while another lane holds the GPU. When several lanes
wait for the GPU the lowest lane index goes first, so the earliest locale finishes first;
lanes are started one at a time, each only after the previous lane has claimed its first
stage, so that order holds from the first render on.

A failing lane stops only that lane (a Layer 3 change invalidates one locale). The lanes
report is run evidence with the per-stage timeline and the observed overlaps; it is never
release material, and dry-run only plans.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
import threading
import time

from . import group_l3

CONFIG_SCHEMA = "sermon-group-l3-lanes-v1"
REPORT_SCHEMA = "sermon-group-l3-lanes-report-v1"
GPU_SLOTS = 1
FIRST_CLAIM_TIMEOUT_SECONDS = 60


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def load_configuration(path: Path) -> dict:
    path = Path(path).resolve()
    config = json.loads(path.read_text(encoding="utf-8"))
    _require(isinstance(config, dict) and config.get("schemaVersion") == CONFIG_SCHEMA,
             "invalid_group_l3_lanes_config")
    _require({"schemaVersion", "lanes"} <= set(config) <= {"schemaVersion", "lanes", "note"},
             "unknown_group_l3_lanes_field")
    lanes = config["lanes"]
    _require(isinstance(lanes, list) and lanes, "group_l3_lanes_needs_lanes")
    resolved, locales, outs, configs = [], set(), set(), set()
    for lane in lanes:
        _require(isinstance(lane, dict) and set(lane) == {"locale", "config", "out"}
                 and all(isinstance(lane[key], str) and lane[key] for key in lane), "invalid_group_l3_lane")
        stage_config = path.parent / lane["config"] if not Path(lane["config"]).is_absolute() else Path(lane["config"])
        out = path.parent / lane["out"] if not Path(lane["out"]).is_absolute() else Path(lane["out"])
        _require(lane["locale"] not in locales and out.resolve() not in outs
                 and stage_config.resolve() not in configs, "duplicate_group_l3_lane")
        locales.add(lane["locale"]); outs.add(out.resolve()); configs.add(stage_config.resolve())
        resolved.append({"locale": lane["locale"], "config": group_l3.load_configuration(stage_config),
                         "configPath": stage_config.resolve(), "out": out.resolve()})
    return {"path": path, "lanes": resolved}


class ResourceGate:
    """One slot per gated resource; waiting lanes are served by lane index, then arrival."""
    def __init__(self, slots: dict[str, int]):
        self._condition = threading.Condition()
        self._slots = dict(slots)
        self._in_use = {name: 0 for name in slots}
        self._waiting: dict[str, list[tuple[int, int]]] = {name: [] for name in slots}
        self._arrivals = 0
        self.timeline: list[dict] = []

    def for_lane(self, lane_index: int, locale: str, first_claim: threading.Event | None = None):
        @contextmanager
        def gate(stage_name: str, resource: str):
            if first_claim is not None:
                first_claim.set()
            if resource not in self._slots:
                started_at = _now()
                yield {"waitSeconds": 0.0}
                self._record(locale, stage_name, resource, started_at, 0.0)
                return
            waited = time.monotonic()
            with self._condition:
                self._arrivals += 1
                ticket = (lane_index, self._arrivals)
                queue = self._waiting[resource]
                queue.append(ticket)
                queue.sort()
                while not (queue[0] == ticket and self._in_use[resource] < self._slots[resource]):
                    self._condition.wait()
                queue.pop(0)
                self._in_use[resource] += 1
                self._condition.notify_all()
            wait_seconds = time.monotonic() - waited
            started_at = _now()
            try:
                yield {"waitSeconds": wait_seconds}
            finally:
                with self._condition:
                    self._in_use[resource] -= 1
                    self._condition.notify_all()
                self._record(locale, stage_name, resource, started_at, wait_seconds)
        return gate

    def _record(self, locale, stage_name, resource, started_at, wait_seconds):
        with self._condition:
            self.timeline.append({"locale": locale, "stage": stage_name, "resource": resource,
                                  "startedAt": started_at, "endedAt": _now(),
                                  "waitSeconds": round(wait_seconds, 3)})


def run_lanes(config: dict, out: Path, *, dry_run: bool = False) -> dict:
    out = Path(out)
    report = {"schemaVersion": REPORT_SCHEMA, "mode": "dry_run" if dry_run else "execute",
              "startedAt": _now(), "gpuSlots": GPU_SLOTS, "lanes": [], "overlaps": [],
              "releaseEligible": False, "humanApproval": False}
    gate = ResourceGate({"gpu": GPU_SLOTS})
    results: dict[int, dict] = {}

    def run_lane(index: int, lane: dict, first_claim: threading.Event) -> None:
        entry = {"locale": lane["locale"], "config": str(lane["configPath"]), "out": str(lane["out"])}
        try:
            lane_report = group_l3.run_stages(lane["config"], lane["out"], dry_run=dry_run,
                                              gate=gate.for_lane(index, lane["locale"], first_claim))
            entry.update(status=lane_report["status"], stages=_stage_rows(lane_report))
        except group_l3.StageRefused as exc:
            entry.update(status="failed", stage=exc.stage, reason=exc.reason, groupIds=exc.group_ids,
                         stages=_stage_rows(_read_report(lane["out"])))
        except Exception as exc:  # a lane's refusal must not take the other lanes down
            entry.update(status="failed", reason=f"{type(exc).__name__}:{exc}",
                         stages=_stage_rows(_read_report(lane["out"])))
        finally:
            first_claim.set()
        results[index] = entry

    if dry_run:
        for index, lane in enumerate(config["lanes"]):
            run_lane(index, lane, threading.Event())
    else:
        threads = []
        for index, lane in enumerate(config["lanes"]):
            # The next lane starts only once this one has claimed (or been refused) its first
            # stage, so lane order decides who renders first instead of thread scheduling.
            first_claim = threading.Event()
            thread = threading.Thread(target=run_lane, args=(index, lane, first_claim),
                                      name=f"l3-lane-{lane['locale']}")
            threads.append(thread)
            thread.start()
            first_claim.wait(timeout=FIRST_CLAIM_TIMEOUT_SECONDS)
        for thread in threads:
            thread.join()
    report["lanes"] = [results[index] for index in range(len(config["lanes"]))]
    report["timeline"] = sorted(gate.timeline, key=lambda row: row["startedAt"])
    report["overlaps"] = _overlaps(report["timeline"])
    report["endedAt"] = _now()
    report["status"] = ("planned" if dry_run else
                        "completed" if all(lane["status"] == "completed" for lane in report["lanes"]) else "failed")
    _write_report(out, report)
    return report


def _stage_rows(lane_report: dict | None) -> list[dict]:
    rows = []
    for row in (lane_report or {}).get("stages", []):
        rows.append({key: row[key] for key in ("name", "resource", "status", "startedAt", "endedAt",
                                                "seconds", "waitSeconds", "exitCode") if key in row})
    return rows


def _overlaps(timeline: list[dict]) -> list[dict]:
    """CPU stages that ran while another lane held the GPU: the gain this scheduler exists for."""
    found = []
    gpu = [row for row in timeline if row["resource"] == "gpu"]
    for row in timeline:
        if row["resource"] == "gpu":
            continue
        for other in gpu:
            if other["locale"] != row["locale"] and other["startedAt"] < row["endedAt"] and row["startedAt"] < other["endedAt"]:
                found.append({"cpuStage": {"locale": row["locale"], "stage": row["stage"]},
                              "gpuStage": {"locale": other["locale"], "stage": other["stage"]}})
    return found


def _read_report(out: Path) -> dict | None:
    path = Path(out) / "stage-report.json"
    try:
        return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None
    except (OSError, ValueError):
        return None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _write_report(out: Path, report: dict) -> None:
    out.mkdir(parents=True, exist_ok=True)
    path = out / "lanes-report.json"
    temporary = out / f".lanes-report.{os.getpid()}.tmp"
    temporary.write_text(json.dumps(report, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def main(argv=None) -> int:
    import argparse
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True, help="Directory for lanes-report.json")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    report = run_lanes(load_configuration(args.config), args.out, dry_run=args.dry_run)
    print(json.dumps({"status": report["status"],
                      "lanes": {lane["locale"]: lane["status"] for lane in report["lanes"]},
                      "overlaps": len(report["overlaps"])}))
    return 0 if report["status"] in ("completed", "planned") else 5


if __name__ == "__main__":
    sys.exit(main())
