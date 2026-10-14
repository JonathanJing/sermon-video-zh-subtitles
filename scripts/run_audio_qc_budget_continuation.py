#!/usr/bin/env python3
"""Run unchanged audio QC with returned judge calls from one approved prior root.

The prior root is read only. A missing judge operation uses the new QC authority;
the audio driver's secondary ASR also uses only that new authority. This wrapper
changes budget routing, not the frozen QC prompts, scoring or waiver implementation.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import check_run_start, machine_qc_budget_authorization as authorization
from scripts import machine_quality_waiver, run_machine_qc_audio_test as driver


class RoutedJudge:
    def __init__(self, prior, current):
        if prior.identity != current.identity:
            raise ValueError("audio_qc_continuation_judge_identity_changed")
        self.prior, self.current = prior, current
        self.identity = current.identity
        self.ledger = current.ledger  # New secondary ASR calls belong to the new authority.

    def key(self, *args):
        return self.current.key(*args)

    def _prior_returned(self, *args):
        role, system, user, schema = args
        payload = self.prior._payload(role, system, user, schema)
        return self.prior.ledger.returned(self.prior._operation(role, system, user, schema),
                                          self.prior._request_identity(payload))

    def cached(self, *args):
        return self.prior(*args) if self._prior_returned(*args) else self.current.cached(*args)

    def __call__(self, *args):
        return self.prior(*args) if self._prior_returned(*args) else self.current(*args)

    def uncertain(self):
        return sorted(set(self.prior.uncertain() + self.current.uncertain()))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0], add_help=False)
    parser.add_argument("--prior-budget-plan", type=Path, required=True)
    args, driver_args = parser.parse_known_args(argv)
    prior_plan_dir = args.prior_budget_plan.resolve()
    plan = json.loads((prior_plan_dir / "plan.json").read_text())
    receipt = prior_plan_dir / plan["approvalReceipt"]
    approved = json.loads(receipt.read_text())
    frozen = {key: value for key, value in plan.items() if key not in {"approvalReceipt", "approvalSha256"}}
    if (plan.get("schemaVersion") != "sermon-run-budget-plan-v3"
            or hashlib.sha256(receipt.read_bytes()).hexdigest() != plan.get("approvalSha256")
            or approved.get("binding") != frozen or approved.get("humanApproval") is not True
            or approved.get("decision") != "approved"
            or plan.get("expectedImplementation") != machine_quality_waiver.implementation_sha256()):
        raise ValueError("audio_qc_continuation_prior_plan_changed")
    matches = [stage for stage in plan["stages"] if stage["stage"].startswith("qc.")]
    if len(matches) != 1:
        raise ValueError("audio_qc_continuation_needs_one_prior_locale")
    prior_authorization = Path(matches[0]["authorization"])
    prior_value = authorization.validate(prior_authorization, require_scope=True)
    stage = matches[0]
    if (hashlib.sha256(prior_authorization.read_bytes()).hexdigest() != stage["authorizationSha256"]
            or stage["budgetRoot"] != prior_value["budgetRoot"]
            or stage["qcContext"] != prior_value["qcContext"]):
        raise ValueError("audio_qc_continuation_prior_authority_changed")
    authority = {"approvalSha256": prior_value["authority"]["approvalSha256"],
                 "globalBounds": prior_value["authority"]["bounds"]["globalBounds"],
                 "requestLimits": prior_value["authority"]["requestLimits"]}
    check_run_start.inspect_source_root(Path(stage["budgetRoot"]), required=True,
                                        as_reuse_source=True, expected=authority,
                                        reuse_roots=prior_value.get("reuseBudgetRoots", []))
    original_factory = driver.audio_api_judge_for_resolved

    def routed_factory(current_authorization, resolved, *, requested_locales=None):
        current = original_factory(current_authorization, resolved, requested_locales=requested_locales)
        prior = original_factory(prior_authorization, resolved, requested_locales=requested_locales)
        if requested_locales != [matches[0]["stage"].split(".", 1)[1]]:
            raise ValueError("audio_qc_continuation_locale_changed")
        return RoutedJudge(prior, current)

    driver.audio_api_judge_for_resolved = routed_factory
    return driver.main(driver_args)


if __name__ == "__main__":
    from scripts.export_run_digest import write_report
    try:
        code = main()
    finally:
        if driver.REPORT_DIRS:
            write_report(driver.REPORT_DIRS, "machine-qc-audio-budget-continuation")
    raise SystemExit(code)
