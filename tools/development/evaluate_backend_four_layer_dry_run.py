#!/usr/bin/env python3
"""Required local/CI regression for the isolated four-layer backend simulation."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import tempfile

try:
    from scripts import backend_four_layer_dry_run as dry
    from scripts.firebase_dev_weekly_dry_run import checked_backend_run
except ImportError:
    import backend_four_layer_dry_run as dry
    from firebase_dev_weekly_dry_run import checked_backend_run


FAILURE_POINTS = ("layer1", "layer2:ko:unit-0:sol", "layer3:es", "layer4")


def evaluate() -> dict:
    with tempfile.TemporaryDirectory(prefix="sermon-backend-dry-run-") as folder:
        root = Path(folder)
        passed = dry.run(dry.ROOT / "config/backend-four-layer-dry-run.fixture.json",
                         root / "pass")
        if (passed["status"] != "pass_simulated"
                or passed["formalApproval"] is not False
                or passed["productionReleaseEligible"] is not False
                or any(passed["externalCalls"].values())
                or set(passed["layers"]) != {"layer1", "layer2", "layer3", "layer4"}
                or passed["layers"]["layer4"].get("assetAssembly") != "copy_bound_asset_v1"
                or len(passed["layers"]["layer4"].get("assets", [])) != 3
                or any(passed["layers"]["layer2"][locale]["modelCalls"] != 4
                       for locale in dry.LOCALES)
                or not all(event["status"] == "pass" and "elapsedMs" in event
                           for event in passed["events"])):
            raise ValueError("Successful simulation lost its four-layer or safety contract")
        checked_backend_run(root / "pass")
        cases = []
        for index, failure_point in enumerate(FAILURE_POINTS):
            path = root / f"failure-{index}"
            result = dry.run(dry.ROOT / "config/backend-four-layer-dry-run.fixture.json",
                             path, fail_at=failure_point)
            if (result["status"] != "failed" or result["formalApproval"] is not False
                    or result["productionReleaseEligible"] is not False
                    or (path / "public/flow/index.html").exists()):
                raise ValueError(f"Failure did not stop preview publication: {failure_point}")
            try:
                checked_backend_run(path)
            except ValueError:
                pass
            else:
                raise ValueError(f"Dev importer accepted a failed run: {failure_point}")
            cases.append({"failurePoint": failure_point, "status": "blocked_as_expected",
                          "failedStep": next(event["step"] for event in reversed(result["events"])
                                             if event["status"] == "fail")})
        unreachable = dry.run(dry.ROOT / "config/backend-four-layer-dry-run.fixture.json",
                              root / "unreachable", fail_at="layer2:ko:unit-7:sol")
        if (unreachable["status"] != "failed"
                or "was not reached" not in unreachable.get("failure", "")
                or (root / "unreachable/public/flow/index.html").exists()):
            raise ValueError("Unreachable failure injection reported success")
        cases.append({"failurePoint": "layer2:ko:unit-7:sol",
                      "status": "rejected_unreachable", "failedStep": None})
        return {"schemaVersion": "sermon-backend-dry-run-evaluation-v1",
                "status": "pass", "simulationOnly": True,
                "successfulRun": {"events": len(passed["events"]),
                                  "sourceUnits": passed["layers"]["layer1"]["sourceUnits"],
                                  "modelCalls": sum(passed["layers"]["layer2"][locale]["modelCalls"]
                                                    for locale in dry.LOCALES),
                                  "sharedControlLoops": passed["sharedControlLoops"],
                                  "externalCalls": passed["externalCalls"]},
                "failureCases": cases}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, help="Optional machine-readable evaluation receipt")
    args = parser.parse_args()
    result = evaluate()
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
                            encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
