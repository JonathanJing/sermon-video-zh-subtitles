#!/usr/bin/env python3
"""Inspect frozen App products and supplied review evidence, offline and read-only.

This gate never generates content, approval, device evidence, or a publication.
The legacy dual_pdf supervisor and its completion scope are intentionally separate.
Input and receipt shapes live in sermon-app-delivery-v1.schema.json ($defs).
"""
from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
import math
from pathlib import Path
import re
import subprocess

from jsonschema import Draft202012Validator, FormatChecker

try:
    from scripts import stage_formal_multilingual_dev as stage
    from scripts import build_english_source_package as source_builder
except ImportError:
    import stage_formal_multilingual_dev as stage
    import build_english_source_package as source_builder


ROOT = Path(__file__).resolve().parents[1]
SCHEMA = ROOT / "schemas/sermon-app-delivery-v1.schema.json"
FORMATS = FormatChecker()


@FORMATS.checks("date-time", raises=(ValueError, TypeError))
def valid_timestamp(value):
    # jsonschema's optional RFC3339 dependency may be absent in an offline venv.
    return (not isinstance(value, str) or
            bool(re.fullmatch(r"\d{4}-\d\d-\d\d[Tt]\d\d:\d\d:\d\d(?:\.\d+)?(?:[Zz]|[+-]\d\d:\d\d)", value))
            and datetime.fromisoformat(value.upper().replace("Z", "+00:00")).utcoffset() is not None)
PRODUCTS = ("translation", "audio", "outline", "reflection")
TEST_ENVIRONMENTS = ("ios_beta", "firebase_dev")
PRODUCTION_ENVIRONMENTS = ("ios_prod", "firebase_prod")
PRODUCT_NAMES = {"translation": "翻译", "audio": "配音", "outline": "大纲", "reflection": "默想"}
SCHEMA_NAMES = {
    "sermon-target-language-candidate-v2": "翻译候选",
    "sermon-target-language-audio-package-v1": "配音与同步",
    "sermon-app-study-product-v1": "大纲或默想",
    "sermon-target-language-release-package-v1": "开发页面交付包",
    "sermon-target-language-release-package-v2": "正式页面交付包",
}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def digest(value):
    return stage.canonical_sha(value)


def json_value(data):
    def unique_object(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, "duplicate_json_field")
            result[key] = value
        return result
    def finite_constant(value):
        raise ValueError("nonfinite_json_number")
    return json.loads(data, object_pairs_hook=unique_object, parse_constant=finite_constant)


def read(path):
    value = json_value(path.read_text(encoding="utf-8"))
    require(isinstance(value, dict), "expected_json_object")
    return value


def validate(value, name):
    schema = read(SCHEMA)
    schema["$ref"] = "#/$defs/" + name
    schema.pop("oneOf", None)
    errors = list(Draft202012Validator(schema, format_checker=FORMATS).iter_errors(value))
    require(not errors, name + "_invalid_schema")


def existing_schema(value, name):
    definition = read(ROOT / "schemas" / name)
    require(Draft202012Validator(definition, format_checker=FORMATS).is_valid(value),
            "existing_package_invalid_schema")


def local_file(root, base, path):
    raw = Path(path)
    require(isinstance(path, str) and path.strip() and "\\" not in path
            and ".." not in raw.parts and "://" not in path, "unsafe_artifact_path")
    target = raw if raw.is_absolute() else base / raw
    require(target.resolve().is_relative_to(root), "artifact_outside_root")
    cursor = target
    while cursor != root and cursor != cursor.parent:
        require(not cursor.is_symlink(), "symlink_artifact")
        cursor = cursor.parent
    require(target.is_file(), "artifact_missing")
    return target


def artifact(root, base, reference, *, object_required=True):
    require(set(reference) <= {"path", "sha256", "jsonSha256"}
            and {"path", "sha256"} <= set(reference), "invalid_artifact_fields")
    path = local_file(root, base, reference["path"])
    data = path.read_bytes()
    require(hashlib.sha256(data).hexdigest() == reference["sha256"], "artifact_sha_mismatch")
    value = json_value(data) if object_required or "jsonSha256" in reference else None
    require(not object_required or isinstance(value, dict), "expected_json_object")
    if "jsonSha256" in reference:
        require(digest(value) == reference["jsonSha256"], "artifact_json_sha_mismatch")
    return path, value


def package_artifact(root, base, reference, *, object_required=True):
    # Existing package artifact schemas permit metadata. Consume only bindings.
    return artifact(root, base, {key: reference[key] for key in ("path", "sha256", "jsonSha256")
                                if key in reference}, object_required=object_required)


def nested_artifacts(root, base, value):
    """Verify only schema-declared local artifacts; never execute an input field."""
    if isinstance(value, dict):
        if {"path", "sha256"} <= set(value):
            # Existing audio artifact schemas allow metadata such as sizeBytes.
            # Only these path/hash fields are consumed; metadata never executes.
            artifact(root, base, {key: value[key] for key in ("path", "sha256", "jsonSha256")
                                  if key in value}, object_required=False)
        else:
            for child in value.values():
                nested_artifacts(root, base, child)
    elif isinstance(value, list):
        for child in value:
            nested_artifacts(root, base, child)


def content_hash(plan):
    """Frozen product states, exact asset bytes and human receipts per locale."""
    return digest({locale: plan["products"][locale] for locale in plan["locales"]})


def candidate_identity(plan):
    # PDF requests and later environment observations cannot invalidate App review.
    fields = ("schemaVersion", "pageId", "sourceId", "sourceUrlHash", "source",
              "contentRevision", "contentHash", "locales", "products", "allowTextOnlyLocales",
              "testEnvironments", "productionEnvironments", "clientCapabilities")
    return digest({key: plan[key] for key in fields})


def review_scope(plan):
    return [{"locale": locale, "product": product,
             "status": plan["products"][locale][product]["status"],
             "artifactSha256": plan["products"][locale][product].get("artifact", {}).get("sha256")}
            for locale in plan["locales"] for product in PRODUCTS]


def source_package(root, plan):
    path, source = artifact(root, root, plan["source"])
    existing_schema(source, "sermon-english-source-package-v1.schema.json")
    source_builder.validate_ready_package(source)
    require(source["source"]["sourceId"] == plan["sourceId"]
            and source["source"]["sourceUrlHash"] == plan["sourceUrlHash"], "source_identity_mismatch")
    nested_artifacts(root, path.parent, source)
    _, anchors = artifact(root, path.parent, source["anchors"]["artifact"])
    ids = [unit["sourceUnitId"] for unit in anchors["sourceUnits"]]
    require(len(ids) == len(set(ids)) and ids == source["review"]["reviewedSourceUnitIds"],
            "source_review_coverage_mismatch")
    review_reference = source["review"]["evidence"]
    require(review_reference is not None, "source_human_review_missing")
    review_path, source_review = artifact(root, path.parent, review_reference)
    existing_schema(source_review, "sermon-english-source-review-v1.schema.json")
    checked, _ = source_builder._review_payload(review_path,
        aligned_sha256=source["transcript"]["artifact"]["sha256"],
        anchor_json_sha256=source["anchors"]["artifact"]["jsonSha256"], source_unit_ids=ids)
    require(checked == source["review"], "source_human_review_binding_mismatch")
    return source


def translation(root, row, source, locale):
    path, candidate = artifact(root, root, row["artifact"])
    existing_schema(candidate, "sermon-target-language-candidate-v2.schema.json")
    _, receipt = artifact(root, root, row["review"])
    existing_schema(receipt, "sermon-target-language-human-review-receipt-v1.schema.json")
    groups = candidate["groups"]
    ids = [group["translationGroupId"] for group in groups]
    source_ids = set(source["review"]["reviewedSourceUnitIds"])
    covered = [unit_id for group in groups for unit_id in group["sourceUnitIds"]]
    require(stage.reviewed_candidate(candidate) and candidate["targetLocale"] == locale
            and candidate["englishSourcePackageJsonSha256"] == digest(source)
            and candidate["anchorManifestSha256"] == source["anchors"]["artifact"]["jsonSha256"]
            and covered == source["review"]["reviewedSourceUnitIds"] and len(covered) == len(source_ids)
            and all([coverage["sourceUnitId"] for coverage in group["coverage"]] == group["sourceUnitIds"]
                    for group in groups),
            "translation_not_reviewed_for_source")
    require(receipt["decision"] == "approved" and receipt["targetLocale"] == locale
            and receipt["candidateJsonSha256"] == digest(candidate)
            and receipt["englishSourcePackageJsonSha256"] == digest(source)
            and receipt["anchorManifestJsonSha256"] == candidate["anchorManifestSha256"]
            and receipt["translationPolicySha256"] == candidate["translationPolicySha256"]
            and receipt["reviewer"] == candidate["humanReview"]["reviewer"]
            and receipt["reviewedAt"] == candidate["humanReview"]["reviewedAt"]
            and receipt["reviewedGroupIds"] == ids
            and [row["translationGroupId"] for row in receipt["groupReviews"]] == ids
            and all(row["decision"] == "approved" and row["evidence"].strip()
                    for row in receipt["groupReviews"])
            and receipt["reviewer"].strip(), "translation_review_binding_mismatch")
    return candidate


def audio(root, row, source, locale, candidate):
    path, package = artifact(root, root, row["artifact"])
    existing_schema(package, "sermon-target-language-audio-package-v1.schema.json")
    if "spokenCandidate" in row:
        require("spokenReview" in row, "spoken_candidate_review_missing")
        candidate = translation(root, {"artifact": row["spokenCandidate"], "review": row["spokenReview"]}, source, locale)
    require(candidate is not None and package["targetLocale"] == locale
            and package["englishSourcePackageJsonSha256"] == digest(source)
            and package["targetLanguageCandidateJsonSha256"] == digest(candidate), "audio_source_binding_mismatch")
    if row["status"] == "audio_unavailable":
        require(package["status"] == "audio_unavailable" and package["voice"] is None
                and not package["units"] and all(package[key] is None for key in ("track", "captions", "schedule")),
                "audio_unavailable_contains_audio")
        return
    _, receipt = artifact(root, root, row["review"])
    schemas = {"sermon-target-language-audio-human-review-receipt-v1",
               "sermon-target-language-audio-human-review-receipt-v2"}
    require(receipt.get("schemaVersion") in schemas, "unsupported_audio_review_schema")
    existing_schema(receipt, receipt["schemaVersion"] + ".schema.json")
    screening = None
    if "screening" in row:
        screening_path, screening = artifact(root, root, row["screening"])
        existing_schema(screening, "sermon-target-language-audio-screening-v1.schema.json")
    ids = [group["translationGroupId"] for group in candidate["groups"]]
    require(package["status"] == "human_reviewed" and not package["issues"]
            and all(package[key] is not None for key in ("track", "captions", "schedule"))
            and package["voice"] is not None
            and package["voice"]["authorizationStatus"] == "authorized"
            and package["voice"]["targetLocaleCapability"] == "reviewed"
            and package["humanReview"]["humanApproval"] is True
            and package["humanReview"]["status"] == "approved"
            and package["humanReview"]["fullPlayback"] == "approved"
            and package["machineScreening"]["coverage"] == 1
            and receipt["decision"] == "approved" and receipt["targetLocale"] == locale
            and receipt["englishSourcePackageJsonSha256"] == digest(source)
            and receipt["targetLanguageCandidateJsonSha256"] == digest(candidate)
            and receipt["targetLanguageAudioPackageJsonSha256"] == digest(package)
            and receipt["trackSha256"] == package["track"]["sha256"]
            and receipt["reviewedBy"] == package["humanReview"]["reviewedBy"]
            and receipt["reviewedAt"] == package["humanReview"]["reviewedAt"]
            and receipt["reviewedUnitIds"] == ids and receipt["reviewedBy"].strip()
            and [unit["textGroupId"] for unit in package["units"]] == ids
            and all(unit["targetTextSha256"] == hashlib.sha256(group["targetText"].encode()).hexdigest()
                    for unit, group in zip(package["units"], candidate["groups"])), "audio_not_reviewed_for_candidate")
    stage.validate_audio_screening_review(package, receipt, screening)
    nested_artifacts(root, path.parent, package)
    # Use the existing fixed ffprobe/ffmpeg validator, not an input command.
    durations = []
    for reference in [package["track"]] + [unit["audio"] for unit in package["units"]]:
        audio_path, _ = package_artifact(root, path.parent, reference, object_required=False)
        durations.append(stage.decode_audio(audio_path, "App audio"))
    _, captions = package_artifact(root, path.parent, package["captions"])
    _, schedule = package_artifact(root, path.parent, package["schedule"])
    measured = schedule.get("trackDurationSeconds")
    require(type(measured) in (int, float) and math.isfinite(measured)
            and abs(measured - durations[0]) <= 0.2
            and schedule.get("timingKind") == "measured_target_audio"
            and schedule.get("status") == "pass" and not schedule.get("issues")
            and schedule.get("targetLocale") == locale
            and captions.get("targetLocale", locale) == locale
            and captions.get("locale", locale) == locale
            and [entry["textGroupId"] for entry in schedule.get("entries", [])] == ids
            and [cue["textGroupId"] for cue in captions.get("cues", [])] == ids
            and [cue["text"] for cue in captions["cues"]] == [group["targetText"] for group in candidate["groups"]],
            "audio_captions_or_schedule_mismatch")
    previous_end = 0
    for unit, group, entry, cue, duration in zip(package["units"], candidate["groups"],
                                               schedule["entries"], captions["cues"], durations[1:]):
        start, end = entry.get("plannedStart"), entry.get("plannedEnd")
        require(type(start) in (int, float) and type(end) in (int, float)
                and math.isfinite(start) and math.isfinite(end)
                and start >= 0 and start >= previous_end - 0.02 and end > start
                and end <= durations[0] + 0.1 and abs((end - start) - duration) <= 0.2
                and abs(duration - unit["durationSeconds"]) <= 0.2
                and entry.get("sourceUnitIds") == group["sourceUnitIds"]
                and cue.get("sourceUnitIds", group["sourceUnitIds"]) == group["sourceUnitIds"]
                and cue.get("start") == start and cue.get("end") == end,
                "audio_measured_timing_mismatch")
        previous_end = end


def study_product(root, row, plan, source, locale, product, candidate):
    _, value = artifact(root, root, row["artifact"])
    _, receipt = artifact(root, root, row["review"])
    validate(value, "studyProduct")
    validate(receipt, "productReview")
    require(candidate is not None, "study_translation_missing")
    for document in (value, receipt):
        require(document["pageId"] == plan["pageId"] and document["targetLocale"] == locale
                and document["product"] == product and document["contentRevision"] == plan["contentRevision"]
                and document["englishSourcePackageJsonSha256"] == digest(source)
                and document["targetLanguageCandidateJsonSha256"] == digest(candidate), "study_product_binding_mismatch")
    require(receipt["decision"] == "approved" and receipt["reviewer"].strip()
            and receipt["artifactSha256"] == row["artifact"]["sha256"]
            and receipt["artifactJsonSha256"] == digest(value)
            and receipt["reviewedItemIds"] == [item["id"] for item in value["items"]], "study_review_binding_mismatch")
    require(len({item["id"] for item in value["items"]}) == len(value["items"])
            and all(item["text"].strip() and set(item["sourceUnitIds"]) <= set(source["review"]["reviewedSourceUnitIds"])
                    for item in value["items"]), "study_content_source_mismatch")


def client_capabilities(root, plan, locale, *, text_only=False):
    if text_only:
        require(locale in plan["allowTextOnlyLocales"], "text_only_not_in_release_plan")
    references = plan["clientCapabilities"].get(locale, {})
    if set(references) != set(TEST_ENVIRONMENTS):
        require(not text_only, "text_only_requires_both_clients")
        return False
    for environment in TEST_ENVIRONMENTS:
        _, value = artifact(root, root, references[environment])
        validate(value, "clientCapability")
        expected_schemas, expected_hashes = {}, {}
        for product in PRODUCTS:
            row = plan["products"][locale][product]
            reference = row.get("artifact")
            expected_hashes[product] = reference["sha256"] if reference else None
            expected_schemas[product] = artifact(root, root, reference)[1]["schemaVersion"] if reference else None
        require(value["environment"] == environment
                and value["client"] == plan["testEnvironments"][environment]
                and value["pageId"] == plan["pageId"] and value["targetLocale"] == locale
                and value["contentRevision"] == plan["contentRevision"]
                and value["contentHash"] == plan["contentHash"]
                and (not text_only or value["supportsAudioUnavailable"] is True)
                and value["supportedProductSchemas"] == expected_schemas
                and value["productArtifactSha256s"] == expected_hashes
                and value["decision"] == "approved" and value["reviewer"].strip(), "client_capability_mismatch")
        artifact(root, root, value["evidence"], object_required=False)
    return True


def pdf_status(root, plan):
    value = plan["pdfAdHoc"]
    if value["status"] != "available":
        return dict(value)
    path, _ = artifact(root, root, value["artifact"], object_required=False)
    _, receipt = artifact(root, root, value["review"])
    validate(receipt, "pdfReview")
    require(path.read_bytes().startswith(b"%PDF-") and receipt["decision"] == "approved"
            and receipt["pageId"] == plan["pageId"] and receipt["contentRevision"] == plan["contentRevision"]
            and receipt["contentHash"] == plan["contentHash"]
            and receipt["artifactSha256"] == value["artifact"]["sha256"]
            and receipt["reviewer"].strip(), "pdf_evidence_mismatch")
    parsed = subprocess.run(["pdfinfo", str(path)], capture_output=True, text=True, timeout=10)
    require(parsed.returncode == 0 and re.search(r"^Pages:\s+[1-9]\d*\s*$", parsed.stdout, re.MULTILINE),
            "pdf_not_readable")
    return dict(value)


def inspect(plan_path):
    path = Path(plan_path).absolute()
    require(not path.is_symlink(), "symlink_plan")
    root = path.parent.resolve()
    plan = read(path)
    validate(plan, "plan")
    require(set(plan["products"]) == set(plan["locales"])
            and set(plan["allowTextOnlyLocales"]) <= set(plan["locales"])
            and set(plan["clientCapabilities"]) <= set(plan["locales"]), "locale_plan_mismatch")
    require(content_hash(plan) == plan["contentHash"], "content_hash_mismatch")
    source = source_package(root, plan)
    blockers = []
    for locale in plan["locales"]:
        products = plan["products"][locale]
        for product, row in products.items():
            require(product == "audio" or not ({"screening", "spokenCandidate", "spokenReview"} & set(row)),
                    "audio_fields_on_other_product")
            require(("spokenCandidate" in row) == ("spokenReview" in row), "spoken_review_pair_missing")
        candidate = None
        if products["translation"]["status"] == "available":
            candidate = translation(root, products["translation"], source, locale)
        for product in PRODUCTS:
            row = products[product]
            if row["status"] in {"missing", "failed", "pending"}:
                blockers.append(f"{locale}.{product}.{row['status']}")
            elif row["status"] == "audio_unavailable":
                require(product == "audio", "audio_unavailable_only_for_audio")
                audio(root, row, source, locale, candidate)
                client_capabilities(root, plan, locale, text_only=True)
            elif product == "audio":
                audio(root, row, source, locale, candidate)
            elif product in {"outline", "reflection"}:
                study_product(root, row, plan, source, locale, product, candidate)
    ready = not blockers
    for locale in plan["locales"]:
        if not client_capabilities(root, plan, locale):
            blockers.append(locale + ".client_capabilities_missing")
    candidate_sha = candidate_identity(plan)
    approvals = {}
    for environment in TEST_ENVIRONMENTS:
        reference = plan["approvalReceipts"].get(environment)
        if reference is None:
            blockers.append(environment + ".approval_missing")
            approvals[environment] = "missing"
            continue
        _, receipt = artifact(root, root, reference)
        validate(receipt, "appReview")
        require(receipt["environment"] == environment
                and receipt["client"] == plan["testEnvironments"][environment]
                and receipt["pageId"] == plan["pageId"] and receipt["sourceId"] == plan["sourceId"]
                and receipt["englishSourcePackageJsonSha256"] == digest(source)
                and receipt["contentRevision"] == plan["contentRevision"]
                and receipt["contentHash"] == plan["contentHash"]
                and receipt["candidateJsonSha256"] == candidate_sha
                and receipt["reviewedProducts"] == review_scope(plan)
                and receipt["reviewer"].strip(), "app_approval_binding_mismatch")
        approvals[environment] = receipt["decision"]
        if receipt["decision"] != "approved" or receipt["appVisible"] is not True:
            blockers.append(environment + ".not_approved_visible")
    production = {}
    for environment in PRODUCTION_ENVIRONMENTS:
        reference = plan["productionRuns"].get(environment)
        production[environment] = {"publication": "not_run", "deviceAcceptance": "not_run"}
        if reference is not None:
            _, receipt = artifact(root, root, reference)
            validate(receipt, "productionObservation")
            require(receipt["environment"] == environment
                    and receipt["client"] == plan["productionEnvironments"][environment]
                    and receipt["candidateJsonSha256"] == candidate_sha, "production_observation_binding_mismatch")
            artifact(root, root, receipt["evidence"], object_required=False)
            production[environment] = receipt
    try:
        pdf = pdf_status(root, plan)
    except (ValueError, OSError, KeyError, TypeError, subprocess.SubprocessError):
        pdf = {"status": "failed", "reason": "pdf_evidence_invalid_or_missing"}
    result = {"schemaVersion": "sermon-app-delivery-inspection-v1", "workflowScope": "app_delivery_readiness",
              "pageId": plan["pageId"], "contentRevision": plan["contentRevision"],
              "contentHash": plan["contentHash"], "candidateJsonSha256": candidate_sha,
              "locales": plan["locales"], "appProductsReady": ready,
              "promotion": {"status": "eligible_not_published" if not blockers else "planned",
                            "blockers": blockers}, "approvals": approvals,
              "products": plan["products"], "productNames": PRODUCT_NAMES,
              "schemaNames": SCHEMA_NAMES, "pdfAdHoc": pdf,
              "production": production, "legacyPdfScope": "dual_pdf_unchanged",
              "deviceAcceptance": "not_run", "venueAcceptance": "not_run"}
    validate(result, "inspection")
    return result


class SafeArgumentParser(argparse.ArgumentParser):
    def error(self, message):
        self.exit(2, "App delivery inspection failed: invalid_arguments\n")


def main(argv=None):
    parser = SafeArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("inspect",))
    parser.add_argument("--plan", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        result = inspect(args.plan)
    except (ValueError, OSError, KeyError, TypeError) as exc:
        parser.exit(2, "App delivery inspection failed: invalid_or_unbound_input\n")
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
