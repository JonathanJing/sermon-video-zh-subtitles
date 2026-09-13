"""Synthetic fixture authoring only; impossible to target production evidence."""
from __future__ import annotations

import hashlib
from pathlib import Path

from scripts.sermon_execution_harness import atomic_json
from .contracts import digest
from .local_io import TEMPORAL_ROOT, file_sha, private_directory, read_json


def fixture_root(path: Path) -> Path:
    root = path.resolve()
    if not root.is_relative_to(TEMPORAL_ROOT.resolve()) or root == TEMPORAL_ROOT.resolve():
        raise ValueError("Synthetic fixture must be in its own directory under artifacts/temporal")
    return root


def initialize(path: Path, *, name="fixture-source", sunday="2026-09-06", duration=0.2) -> Path:
    root = fixture_root(path)
    if root.exists() and any(root.iterdir()):
        raise ValueError("Use an empty fixture directory; existing evidence is preserved")
    private_directory(root)
    (root / "source.bin").write_bytes(b"Synthetic test source, never sermon media\n" + name.encode())
    atomic_json(root / "timeline.json", {"status": "requires_operator_review", "fixtureOnly": True, "revision": 1,
                                        "suggestedWindow": {"startTime": "00:00:01", "endTime": "00:00:02"}})
    config = {"schemaVersion": "sermon-temporal-fixture-v1", "fixtureOnly": True, "fixtureRoot": str(root),
              "sunday": sunday, "sourceKey": "fixture:" + name, "sourceId": name,
              "sourceUrl": "https://www.youtube.com/watch?v=fixture-" + name,
              "sourceSha256": file_sha(root / "source.bin"), "durationSeconds": duration}
    path = root / "config.json"
    atomic_json(path, config)
    return path


def write_approval(config_path: Path):
    config = read_json(config_path)
    if config.get("schemaVersion") != "sermon-temporal-fixture-v1" or config.get("fixtureOnly") is not True:
        raise ValueError("Synthetic approval helper refuses non-fixture configurations")
    root = fixture_root(Path(config["fixtureRoot"]))
    if config_path.resolve() != root / "config.json":
        raise ValueError("Fixture configuration path differs from its isolated root")
    timeline = read_json(root / "timeline.json")
    atomic_json(root / "approval.json", {"schemaVersion": 1, "status": "approved", "fixtureOnly": True,
        "humanApproval": True, "sunday": config["sunday"], "approvedBy": "Synthetic test reviewer",
        "approvedAt": "2026-09-06T00:00:00Z", "contentScope": "sermon_only",
        "startTime": "00:00:01", "endTime": "00:00:02",
        "sourceUrlHash": hashlib.sha256(config["sourceUrl"].encode()).hexdigest()[:16],
        "timelineReportSha256": digest(timeline)})
