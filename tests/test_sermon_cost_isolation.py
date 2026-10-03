"""Synthetic offline acceptance, not provider/project integration evidence."""
import contextlib
import copy
from decimal import Decimal, localcontext
import io
import json
from pathlib import Path
import tempfile
import unittest

import jsonschema

from scripts import sermon_cost_isolation as isolation


def config():
    return {"schemaVersion": isolation.VERSION, "kind": "config", "environments": {
        env: {"projectId": "proj_" + env, "keyAliases": {
            workload: env + "_" + workload for workload in isolation.WORKLOADS}}
        for env in isolation.ENVIRONMENTS}}


def attempt(attempt_id="a1", env="dev", **updates):
    item = {"attemptId": attempt_id, "day": "2026-10-03", "pricingVersion": "fixture-list-price-v1", "environment": env, "workload": "translation", "provider": "openai",
            "status": "completed", "projectId": "proj_" + env, "apiKeyId": "key_id_" + env,
            "keyAlias": env + "_translation", "usage": {"inputTokens": 100, "cachedInputTokens": 60,
            "outputTokens": 10}, "cost": {"status": "estimated", "estimatedUsd": "0.1", "currency": "USD"}}
    item.update(updates)
    return item


def attempts(*items):
    return {"schemaVersion": isolation.VERSION, "kind": "attempts", "scope": "partial_attempts",
            "queryWindow": {"startDay": "2026-10-03", "endDayExclusive": "2026-10-05"}, "attempts": list(items)}


def bucket(bucket_id="b1", **updates):
    item = {"bucketId": bucket_id, "day": "2026-10-03", "projectId": "proj_dev", "apiKeyId": None,
            "amountUsd": "0.3", "currency": "USD"}
    item.update(updates)
    return item


def daily(*items):
    return {"schemaVersion": isolation.VERSION, "kind": "daily_costs", "paginationComplete": True,
            "scope": "project_api_key_partitions", "queryWindow": {"startDay": "2026-10-03", "endDayExclusive": "2026-10-05"},
            "settlementStatus": "settled", "pages": [{"pageId": "p1", "nextPageId": None, "buckets": list(items)}]}


class CostIsolationTests(unittest.TestCase):
    def assertRejected(self, code, function, *values):
        with self.assertRaisesRegex(isolation.IsolationError, "^" + code + "$"):
            function(*values)

    def test_config_routes_all_roles_and_is_read_only(self):
        source = config()
        saved = copy.deepcopy(source)
        for env in isolation.ENVIRONMENTS:
            for role in isolation.WORKLOADS:
                route = isolation.resolve_route(source, env, role)
                self.assertEqual(route["projectId"], "proj_" + env)
                self.assertEqual(route["keyAlias"], env + "_" + role)
        self.assertEqual(source, saved)

    def test_cross_environment_and_role_aliases_rejected(self):
        source = config()
        source["environments"]["prod"]["projectId"] = "proj_dev"
        self.assertRejected("cross_environment_project", isolation.validate_config, source)
        source = config()
        source["environments"]["prod"]["keyAliases"]["reviewer"] = "dev_translation"
        self.assertRejected("reused_key_alias", isolation.validate_config, source)

    def test_unknown_configuration_fields_rejected(self):
        source = config()
        source["environments"]["dev"]["apiKey"] = "private-value"
        self.assertRejected("invalid_fields", isolation.validate_config, source)
        self.assertRejected("unknown_environment", isolation.resolve_route, config(), "staging", "translation")
        self.assertRejected("unknown_workload", isolation.resolve_route, config(), "dev", "interpreting")
        self.assertRejected("unknown_provider", isolation.resolve_route, config(), "dev", "transcription", "guessed")

    def test_local_asr_needs_no_openai_alias(self):
        source = config()
        source["environments"]["dev"]["keyAliases"]["transcription"] = None
        route = isolation.resolve_route(source, "dev", "transcription", "local")
        self.assertIsNone(route["projectId"])
        self.assertIsNone(route["keyAlias"])
        self.assertIsNone(isolation.resolve_route(source, "dev", "transcription", "non_openai")["keyAlias"])
        self.assertRejected("missing_openai_key_alias", isolation.resolve_route, source, "dev", "transcription")
        local = attempt(workload="transcription", provider="local", projectId=None, keyAlias=None, apiKeyId=None)
        result = isolation.reconcile(source, attempts(local), daily())
        self.assertEqual(result["attempts"][0]["provider"], "local")
        self.assertIsNone(result["dailyComparisons"][0]["knownEstimatedUsd"])
        self.assertIsNone(result["dailyComparisons"][0]["estimateActualDifferenceUsd"])
        self.assertEqual(result["dailyComparisons"][0]["nonOpenaiAttempts"], 1)
        local["apiKeyId"] = "key_id_dev"
        self.assertRejected("local_asr_openai_attribution", isolation.reconcile, source, attempts(local), daily())

    def test_wrong_attempt_project_and_alias_rejected(self):
        self.assertRejected("attempt_project_mismatch", isolation.reconcile, config(), attempts(attempt(projectId="proj_prod")), daily())
        self.assertRejected("attempt_alias_mismatch", isolation.reconcile, config(), attempts(attempt(keyAlias="dev_reviewer")), daily())

    def test_observed_key_id_cannot_cross_environments_or_roles(self):
        self.assertRejected("reused_api_key_id", isolation.reconcile, config(),
                            attempts(attempt(), attempt("a2", "prod", apiKeyId="key_id_dev")), daily())
        reviewer = attempt("a2", workload="reviewer", keyAlias="dev_reviewer")
        self.assertRejected("reused_api_key_id", isolation.reconcile, config(), attempts(attempt(), reviewer), daily())

    def test_unknown_and_retries_are_individual_attempts(self):
        unknown = attempt("retry", status="unknown_outcome", projectId=None, apiKeyId=None, keyAlias=None,
                          usage={}, cost={"status": "unknown", "estimatedUsd": None, "currency": "USD"})
        result = isolation.reconcile(config(), attempts(attempt(), unknown), daily(bucket()))
        self.assertEqual(len(result["attempts"]), 2)
        summary = result["environments"]["dev"]
        self.assertEqual(summary["unknownCostAttempts"], 1)
        self.assertEqual(summary["unknownOutcomeAttempts"], 1)
        self.assertEqual(summary["unattributedAttempts"], 1)
        self.assertIsNone(result["attempts"][1]["cost"]["estimatedUsd"])
        self.assertIsNone(result["attempts"][1]["usage"]["inputTokens"])

    def test_duplicates_fail_instead_of_silently_deduplicating(self):
        self.assertRejected("duplicate_attempt", isolation.reconcile, config(), attempts(attempt(), attempt()), daily())
        self.assertRejected("duplicate_cost_bucket", isolation.reconcile, config(), attempts(), daily(bucket(), bucket("other")))

    def test_cached_tokens_are_input_subset_and_never_added(self):
        result = isolation.reconcile(config(), attempts(attempt()), daily())
        row = result["attempts"][0]
        self.assertEqual(row["usage"]["inputTokens"], 100)
        self.assertEqual(row["nonCachedInputTokens"], 40)
        self.assertRejected("cached_tokens_exceed_input", isolation.reconcile, config(),
                            attempts(attempt(usage={"inputTokens": 10, "cachedInputTokens": 11})), daily())
        unknown = isolation.reconcile(config(), attempts(attempt(usage={"cachedInputTokens": 5})), daily())
        self.assertIsNone(unknown["attempts"][0]["nonCachedInputTokens"])

    def test_decimal_arithmetic_and_actual_estimate_remain_separate(self):
        rows = attempts(attempt(), attempt("a2", cost={"status": "estimated", "estimatedUsd": "0.2", "currency": "USD"}))
        with localcontext() as context:
            context.prec = 2
            result = isolation.reconcile(config(), rows, daily(bucket(amountUsd="0.333333333333333333")))
        self.assertEqual(result["environments"]["dev"]["knownEstimatedUsd"], "0.3")
        self.assertEqual(result["environments"]["dev"]["observedDailyActualUsd"], "0.333333333333333333")
        comparison = result["dailyComparisons"][0]
        self.assertEqual(comparison["estimateActualDifferenceUsd"], "-0.033333333333333333")
        self.assertEqual(comparison["comparisonCompleteness"], "partial")
        self.assertFalse(result["requestActualCostsAvailable"])
        self.assertFalse(result["invoiceVerified"])
        self.assertNotIn("actualUsd", result["attempts"][0]["cost"])

    def test_unattributed_actual_does_not_guess_from_key(self):
        result = isolation.reconcile(config(), attempts(attempt()), daily(bucket(projectId=None, apiKeyId="key_id_dev")))
        self.assertEqual(result["unattributedActualUsd"], "0.3")
        self.assertEqual(result["environments"]["dev"]["actualBucketCount"], 0)
        self.assertIsNone(result["dailyActualBuckets"][0]["environment"])

    def test_cost_keys_mapped_to_wrong_environment_rejected(self):
        self.assertRejected("cost_api_key_environment_mismatch", isolation.reconcile, config(), attempts(attempt()),
                            daily(bucket(projectId="proj_prod", apiKeyId="key_id_dev")))
        self.assertRejected("duplicate_api_key_partition", isolation.reconcile, config(), attempts(),
                            daily(bucket(apiKeyId="shared_id"), bucket("b2", projectId="proj_prod", apiKeyId="shared_id")))

    def test_partial_pages_and_pending_settlement_explicit(self):
        evidence = daily(bucket())
        evidence["paginationComplete"] = False
        evidence["pages"][0]["nextPageId"] = "p2"
        result = isolation.reconcile(config(), attempts(), evidence)
        self.assertEqual(result["actualCoverage"], "partial")
        evidence["pages"].append({"pageId": "p2", "nextPageId": None,
                                  "buckets": [bucket("b2", day="2026-10-04", amountUsd="0.2")]})
        evidence["paginationComplete"] = True
        evidence["settlementStatus"] = "pending"
        result = isolation.reconcile(config(), attempts(), evidence)
        self.assertEqual(result["actualCoverage"], "partial")
        self.assertEqual(result["environments"]["dev"]["observedDailyActualUsd"], "0.5")
        evidence["settlementStatus"] = "settled"
        self.assertEqual(isolation.reconcile(config(), attempts(), evidence)["actualCoverage"], "complete")

    def test_broken_page_chain_and_false_completion_rejected(self):
        evidence = daily()
        evidence["paginationComplete"] = False
        self.assertRejected("inconsistent_pagination_completion", isolation.reconcile, config(), attempts(), evidence)
        evidence = daily()
        evidence["pages"].append({"pageId": "p2", "nextPageId": None, "buckets": []})
        self.assertRejected("broken_page_chain", isolation.reconcile, config(), attempts(), evidence)

    def test_overlapping_aggregate_and_key_cost_buckets_rejected(self):
        self.assertRejected("overlapping_cost_buckets", isolation.reconcile, config(), attempts(),
                            daily(bucket(), bucket("b2", apiKeyId="key_id_dev")))

    def test_invalid_costs_and_tokens_fail_closed(self):
        for value in (0.1, "NaN", "-1", True, "1e9"):
            with self.subTest(value=value):
                self.assertRejected("invalid_decimal_amount", isolation.reconcile, config(), attempts(), daily(bucket(amountUsd=value)))
        self.assertRejected("invalid_token_count", isolation.reconcile, config(), attempts(attempt(usage={"inputTokens": True})), daily())
        self.assertRejected("unknown_cost_project", isolation.reconcile, config(), attempts(), daily(bucket(projectId="proj_foreign")))

    def test_not_dispatched_is_only_explicit_zero_billing_path(self):
        zero = attempt(status="not_dispatched", cost={"status": "not_incurred", "estimatedUsd": "0", "currency": "USD"})
        self.assertEqual(isolation.reconcile(config(), attempts(zero), daily())["attempts"][0]["cost"]["estimatedUsd"], "0")
        zero["status"] = "failed"
        self.assertRejected("inconsistent_cost_evidence", isolation.reconcile, config(), attempts(zero), daily())

    def test_secret_like_identifiers_rejected_without_echo(self):
        source = config()
        secret = "sk-proj-super-private"
        source["environments"]["dev"]["keyAliases"]["translation"] = secret
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            path.write_text(json.dumps(source))
            out, err = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                self.assertEqual(isolation.main(["validate-config", "--config", str(path)]), 2)
            self.assertNotIn(secret, out.getvalue() + err.getvalue())
            self.assertNotIn(str(path), err.getvalue())

    def test_cli_reads_decimal_json_without_network_or_output_files(self):
        with tempfile.TemporaryDirectory() as directory:
            paths = []
            for name, evidence in (("config", config()), ("attempts", attempts(attempt())), ("daily", daily(bucket()))):
                path = Path(directory) / (name + ".json")
                path.write_text(json.dumps(evidence))
                paths.append(str(path))
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = isolation.main(["reconcile", "--config", paths[0], "--attempts", paths[1], "--daily-costs", paths[2]])
            self.assertEqual(code, 0)
            self.assertFalse(json.loads(out.getvalue())["providerDispatch"])
            self.assertEqual(len(list(Path(directory).iterdir())), 3)

    def test_duplicate_json_fields_are_not_silently_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            path.write_text('{"kind": "config", "kind": "ignored"}')
            self.assertRejected("duplicate_json_field", isolation._read, path)

    def test_daily_comparison_complete_requires_matching_openai_scope(self):
        evidence = attempts(attempt(), attempt("a2", day="2026-10-04"))
        evidence["scope"] = "complete_openai_project_attempts"
        result = isolation.reconcile(config(), evidence, daily(bucket(), bucket("b2", day="2026-10-04", amountUsd="0.05")))
        self.assertEqual([r["estimateActualDifferenceUsd"] for r in result["dailyComparisons"]], ["-0.2", "0.05"])
        self.assertTrue(all(r["comparisonCompleteness"] == "complete" for r in result["dailyComparisons"]))
        evidence["attempts"][0]["status"] = "unknown_outcome"
        result = isolation.reconcile(config(), evidence, daily(bucket()))
        self.assertEqual(result["dailyComparisons"][0]["comparisonCompleteness"], "partial")
        self.assertIsNone(result["dailyComparisons"][1]["observedActualUsd"])
        self.assertIsNone(result["dailyComparisons"][1]["estimateActualDifferenceUsd"])

    def test_query_window_is_explicit_bound_and_shared(self):
        for evidence in (attempts(attempt(day="2026-10-02")), attempts(attempt(day="2026-10-05"))):
            self.assertRejected("outside_query_window", isolation.reconcile, config(), evidence, daily())
        self.assertRejected("outside_query_window", isolation.reconcile, config(), attempts(), daily(bucket(day="2026-10-05")))
        evidence = daily()
        evidence["queryWindow"]["startDay"] = "2026-10-04"
        self.assertRejected("query_window_mismatch", isolation.reconcile, config(), attempts(), evidence)

    def test_estimate_requires_pricing_identity_and_nullable_context_is_kept(self):
        self.assertRejected("missing_pricing_version", isolation.reconcile, config(), attempts(attempt(pricingVersion=None)), daily())
        row = attempt(model="fixture-model", jobId="fixture-job", stage="layer2", providerRequestId="fixture-response")
        result = isolation.reconcile(config(), attempts(row), daily())
        self.assertEqual(result["attempts"][0]["model"], "fixture-model")
        self.assertEqual(result["attempts"][0]["pricingVersion"], "fixture-list-price-v1")

    def test_aggregate_scope_and_empty_actual_cannot_claim_reconciliation(self):
        evidence = daily()
        evidence["scope"] = "organization_aggregate"
        self.assertRejected("unsupported_cost_scope", isolation.reconcile, config(), attempts(), evidence)
        result = isolation.reconcile(config(), attempts(), daily())
        self.assertEqual(result["dailyComparisons"], [])
        self.assertIsNone(result["environments"]["dev"]["observedDailyActualUsd"])
        self.assertEqual(result["actualCoverage"], "partial")
        evidence = attempts(attempt())
        evidence["scope"] = "complete_openai_project_attempts"
        result = isolation.reconcile(config(), evidence, daily(bucket(), bucket("unattributed", projectId=None)))
        self.assertEqual(result["dailyComparisons"][0]["comparisonCompleteness"], "partial")
        self.assertEqual(result["dailyComparisons"][0]["estimateActualDifferenceUsd"], "-0.2")

    def test_argparse_errors_do_not_echo_credentials(self):
        for argv in (["validate-config", "--config", "ignored", "--api-key", "sk-private-sentinel"],
                     ["sk-private-sentinel"], ["reconcile", "--api-key", "sk-private-sentinel"]):
            out, err = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                self.assertEqual(isolation.main(argv), 2)
            self.assertNotIn("sk-private-sentinel", out.getvalue() + err.getvalue())
            self.assertEqual(json.loads(err.getvalue())["reasonCode"], "invalid_cli_arguments")

    def test_distinct_attempts_cannot_rebill_same_openai_request(self):
        one = attempt(providerRequestId="response-1")
        two = attempt("a2", workload="reviewer", keyAlias="dev_reviewer", apiKeyId="reviewer-id", providerRequestId="response-1")
        self.assertRejected("duplicate_provider_request", isolation.reconcile, config(), attempts(one, two), daily())
        two["providerRequestId"] = None
        self.assertEqual(len(isolation.reconcile(config(), attempts(one, two), daily())["attempts"]), 2)

    def test_key_partition_coverage_must_match_attempt_keys(self):
        evidence = attempts(attempt())
        evidence["scope"] = "complete_openai_project_attempts"
        result = isolation.reconcile(config(), evidence, daily(bucket(apiKeyId="different-key")))
        self.assertEqual(result["dailyComparisons"][0]["comparisonCompleteness"], "partial")
        self.assertFalse(result["dailyComparisons"][0]["keyCoverageMatches"])
        result = isolation.reconcile(config(), evidence, daily(bucket(apiKeyId="key_id_dev")))
        self.assertEqual(result["dailyComparisons"][0]["comparisonCompleteness"], "complete")
        evidence["attempts"][0]["apiKeyId"] = None
        self.assertEqual(isolation.reconcile(config(), evidence, daily(bucket(apiKeyId="key_id_dev")))["dailyComparisons"][0]["comparisonCompleteness"], "partial")
        self.assertEqual(isolation.reconcile(config(), evidence, daily(bucket()))["dailyComparisons"][0]["comparisonCompleteness"], "complete")

    def test_key_known_and_unattributed_partitions_cannot_overlap(self):
        self.assertRejected("duplicate_api_key_partition", isolation.reconcile, config(), attempts(),
                            daily(bucket(apiKeyId="key-1"), bucket("b2", projectId=None, apiKeyId="key-1")))

    def test_schema_accepts_fixtures_and_safe_result(self):
        path = Path(__file__).resolve().parents[1] / "schemas/sermon-cost-isolation-v1.schema.json"
        schema = json.loads(path.read_text())
        jsonschema.Draft202012Validator.check_schema(schema)
        for value in (config(), attempts(attempt()), daily(bucket()),
                      isolation.validate_config(config()), isolation.reconcile(config(), attempts(attempt()), daily(bucket()))):
            jsonschema.validate(value, schema)


if __name__ == "__main__":
    unittest.main()
