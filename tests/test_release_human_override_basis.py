"""Layer 4 releases text approved through a human-override receipt (v2) as human reviewed, and says so publicly.

The user approved every group in a bound review sheet while the machine review kept failures; the
v3 release carries ``textReviewBasis`` with the receipt hash, the machine status and each accepted
exception, unchanged. The receipt itself is checked by ``human_override.validate_override_receipt``
(its own tests); here it is stubbed so the release wiring is exercised on the real builder.
"""
import copy
import json
import subprocess

import jsonschema
import pytest

from scripts import tongxing_host  # noqa: F401  binds the production package ports
from tongxing_production.delivery import app_release as builder
from tongxing_production.delivery import contract as d
from tongxing_production.delivery import unified_stage as delivery
from tests.test_public_study_delivery import prepared, save  # noqa: F401  fixture


def override_receipt(candidate):
    group = candidate["groups"][0]
    return {"schemaVersion": builder.OVERRIDE_RECEIPT_V2, "decision": "approved_with_exceptions",
            "modelReview": {"status": "fail", "reviewedGroupIds": [g["translationGroupId"] for g in candidate["groups"]]},
            "groupOverrides": [{"translationGroupId": group["translationGroupId"], "sourceUnitIds": group["sourceUnitIds"],
                                "machineFindings": [{"gate": "languageReview", "checkId": "untranslated_source",
                                                     "machineStatus": "fail"}],
                                "disposition": "accepted_as_is", "rationale": "Approved in the bound review sheet."}],
            "humanApproval": True, "machineEvidenceChanged": False, "releaseEligible": False}


@pytest.fixture
def override_args(prepared, monkeypatch):  # noqa: F811
    f = prepared
    calls = []
    monkeypatch.setattr(builder.human_override, "validate_override_receipt",
                        lambda source, anchor, candidate, receipt: calls.append(receipt["schemaVersion"]))
    receipt = save(f["root"], "override-receipt.json", override_receipt(f["documents"]["full_candidate"]))
    _, _, _, args, _, _ = delivery.load(f["frozen"])
    args.full_review_receipt = [f"{f['locale']}={receipt}"]
    args.spoken_review_receipt = [f"{f['locale']}={receipt}"]
    args.out = f["root"] / "override-prepared"
    return f, args, calls


def built_release(f, args):
    return builder.read(args.out / "public/releases-v2" / f["page"] / (f["locale"] + ".json"))


def test_override_text_is_human_reviewed_and_keeps_machine_failures_public(override_args):
    f, args, calls = override_args
    builder.prepare(args)
    release = built_release(f, args)
    assert calls == [builder.OVERRIDE_RECEIPT_V2] * 2
    assert release["schemaVersion"] == "sermon-target-language-release-package-v3"
    assert (release["contentStatus"], release["audioStatus"]) == ("human_reviewed", "human_reviewed")
    basis = release["textReviewBasis"]
    assert basis["fullText"] == basis["spokenText"]
    assert basis["fullText"]["kind"] == "human_override" and basis["fullText"]["machineReviewStatus"] == "fail"
    receipt = builder.read(f["root"] / "override-receipt.json")
    assert basis["fullText"]["receiptSha256"] == d.sha(receipt)
    assert basis["fullText"]["acceptedExceptions"] == [
        {k: row[k] for k in ("translationGroupId", "sourceUnitIds", "machineFindings")} for row in receipt["groupOverrides"]]
    d.validate_release_schema(release)
    assert "disclosure" not in release and "reviewBasis" not in release


def test_web_reader_loads_a_sealed_release_with_text_review_basis(override_args):
    f, args, _ = override_args
    builder.prepare(args)
    manifest, assets = builder.verified_assets(args.out)
    receipt = save(f["root"], "override-http.json", {
        "schemaVersion": "sermon-app-assets-http-verification-v1", "status": "pass",
        "origin": f["config"]["intent"]["origin"], "verifiedAt": "2026-10-22T20:00:00Z",
        "assets": [{**row, "status": "pass"} for row in assets]})
    sealed = f["root"] / "override-sealed"
    builder.seal(builder.argparse.Namespace(prepared=args.out, http_verification=receipt, out=sealed))
    d.validate_catalog_snapshot(sealed)
    published = builder.read(sealed / "public/releases-v2" / f["page"] / (f["locale"] + ".json"))
    assert published["status"] == "published_http_verified" and "textReviewBasis" in published
    module = (builder.ROOT / "apps/listening-web/published-weeks.mjs").as_uri()
    script = """
import {readFile} from 'node:fs/promises';
const {loadPublishedWeeks}=await import(process.argv[1]);
const fetchImpl=async path=>{try{return new Response(await readFile(process.argv[2]+path));}catch{return new Response('',{status:404});}};
const result=await loadPublishedWeeks(fetchImpl);
if(result.weeks.length!==1||result.weeks[0].studyStatus!=='human_reviewed')throw new Error(JSON.stringify(result));
console.log('passed');
"""
    result = subprocess.run(["node", "--input-type=module", "-e", script, module, str(sealed / "public")],
                            capture_output=True, text=True)
    assert result.returncode == 0 and result.stdout.strip() == "passed", result.stderr


def test_override_text_is_refused_outside_the_four_product_release(override_args):
    f, args, _ = override_args
    args.require_study = False
    with pytest.raises(ValueError, match="human-override text is released only"):
        builder.prepare(args)


def test_override_receipt_is_checked_against_the_source_package(override_args):
    f, args, _ = override_args
    candidate = f["root"] / "full_candidate.json"
    receipt = f["root"] / "override-receipt.json"
    with pytest.raises(ValueError, match="checked against the source package"):
        builder.admitted_text(candidate, receipt, d.sha(f["source"]), f["locale"])
    other = copy.deepcopy(f["source"])
    other["status"] = "changed"
    with pytest.raises(ValueError, match="checked against the source package"):
        builder.admitted_text(candidate, receipt, d.sha(f["source"]), f["locale"], source=other)


def test_override_track_may_carry_only_its_own_exception_disclosure(override_args):
    f, args, _ = override_args
    candidate = f["documents"]["full_candidate"]
    receipt = builder.read(f["root"] / "override-receipt.json")
    basis = {"kind": "human_override", "receiptSha256": d.sha(receipt), "machineReviewStatus": "fail",
             "acceptedExceptions": [{"translationGroupId": row["translationGroupId"], "sourceUnitIds": row["sourceUnitIds"],
                                     "machineFindings": row["machineFindings"]} for row in receipt["groupOverrides"]]}
    issue = {"type": "human_override_machine_exceptions",
             "status": "human_accepted_as_is_machine_findings_remain_unresolved",
             "topLevelModelReview": receipt["modelReview"],
             "exceptionGroups": [{"translationGroupId": row["translationGroupId"], "machineFindings": row["machineFindings"],
                                  "disposition": "accepted_as_is"} for row in receipt["groupOverrides"]],
             "disclosure": "Human approval accepts the exact target text; it does not change or pass machine findings."}
    assert builder.override_audio_issues([issue], basis, candidate)
    assert not builder.override_audio_issues([issue], {"kind": "human_review", "receiptSha256": "a" * 64}, candidate)
    assert not builder.override_audio_issues([issue, {"type": "other"}], basis, candidate)
    for mutate in (lambda i: i["exceptionGroups"].pop(),
                   lambda i: i["exceptionGroups"][0]["machineFindings"].append({"gate": "x", "checkId": "y", "machineStatus": "fail"}),
                   lambda i: i["topLevelModelReview"].update(status="pass"),
                   lambda i: i.update(note="extra")):
        changed = copy.deepcopy(issue)
        mutate(changed)
        assert not builder.override_audio_issues([changed], basis, candidate)


def test_schema_accepts_only_honest_text_review_bases(override_args):
    f, args, _ = override_args
    builder.prepare(args)
    release = built_release(f, args)
    schema = json.loads((builder.ROOT / "schemas/sermon-target-language-release-package-v3.schema.json").read_text())
    jsonschema.validate(release, schema)
    plain = {k: v for k, v in release.items() if k != "textReviewBasis"}
    jsonschema.validate(plain, schema)
    for mutate in (
        lambda b: b["fullText"].pop("acceptedExceptions"),                        # override must list exceptions
        lambda b: b["fullText"].update(machineReviewStatus="passed"),             # unknown machine status
        lambda b: b.update(fullText={"kind": "human_review", "receiptSha256": "a" * 64},
                           spokenText={"kind": "human_review", "receiptSha256": "a" * 64}),  # nothing to record
        lambda b: b.update(spokenText={"kind": "human_review", "receiptSha256": "a" * 64,
                                       "acceptedExceptions": []}),                # a plain review claims exceptions
        lambda b: b["fullText"].update(kind="machine_quality_waiver"),            # waivers belong to release v4
    ):
        broken = copy.deepcopy(release)
        mutate(broken["textReviewBasis"])
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(broken, schema)
