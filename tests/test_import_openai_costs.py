import contextlib
import copy
from decimal import Decimal, localcontext
import io
import json
from pathlib import Path
import tempfile
import unittest

from jsonschema import Draft202012Validator

from scripts import import_openai_costs as importer
from scripts import sermon_cost_isolation as costs
from tests.test_sermon_cost_isolation import config, attempts, attempt


def row(project="proj_dev", key=None, line=None, value="0.1"):
    return {"object": "organization.costs.result", "project_id": project,
            "api_key_id": key, "line_item": line,
            "amount": {"currency": "usd", "value": Decimal(value)}}


def day(offset=0, *rows):
    start = 1790985600 + offset * 86400  # 2026-10-03 UTC
    return {"object": "bucket", "start_time": start, "end_time": start + 86400, "results": list(rows)}


def page(*days, cursor=None, next_cursor=None):
    return {"requestCursor": cursor, "response": {"object": "page", "data": list(days),
            "has_more": next_cursor is not None, "next_page": next_cursor}}


def export(*pages, groups=None):
    return {"schemaVersion": importer.VERSION,
            "queryWindow": {"startDay": "2026-10-03", "endDayExclusive": "2026-10-05"},
            "groupBy": groups or ["project_id", "api_key_id", "line_item"], "pages": list(pages)}


class NativeCostImportTests(unittest.TestCase):
    def reject(self, code, value):
        with self.assertRaisesRegex(costs.IsolationError, "^" + code + "$"):
            importer.normalize(config(), value)

    def test_native_partitions_decimal_sum_and_reconciliation(self):
        value = export(page(day(0, row(line="input"), row(line="output", value="0.2")), day(1)))
        original = copy.deepcopy(value)
        with localcontext() as ctx:
            ctx.prec = 2
            normalized = importer.normalize(config(), value)
        self.assertEqual(value, original)
        self.assertEqual(normalized["pages"][0]["buckets"][0]["amountUsd"], "0.3")
        self.assertEqual(normalized["settlementStatus"], "pending")
        result = costs.reconcile(config(), attempts(attempt()), normalized)
        self.assertEqual(result["dailyComparisons"][0]["observedActualUsd"], "0.3")
        self.assertEqual(result["actualCoverage"], "partial")
        self.assertFalse(result["invoiceVerified"])
        self.assertFalse(result["providerDispatch"])

    def test_v2_config_import_and_reconciliation_preserve_version(self):
        source = config()
        source["schemaVersion"] = costs.SHARED_VERSION
        for env in costs.ENVIRONMENTS:
            source["environments"][env]["keyAliases"] = dict.fromkeys(costs.WORKLOADS, env + "_runtime")
        normalized = importer.normalize(source, export(page(day(0, row(key="key_id_dev")), day(1))))
        self.assertEqual(normalized["schemaVersion"], costs.SHARED_VERSION)
        result = costs.reconcile(source, attempts(attempt(keyAlias="dev_runtime")), normalized)
        schema = json.loads(Path("schemas/sermon-cost-isolation-v2.schema.json").read_text())
        for value in (normalized, result):
            Draft202012Validator(schema).validate(value)

    def test_two_pages_and_partial_chain(self):
        value = export(page(day(0, row()), next_cursor="opaque+/=cursor"),
                       page(day(1, row()), cursor="opaque+/=cursor"))
        normalized = importer.normalize(config(), value)
        self.assertTrue(normalized["paginationComplete"])
        self.assertEqual(normalized["pages"][0]["nextPageId"], normalized["pages"][1]["pageId"])
        self.assertNotIn("opaque", json.dumps(normalized))
        value["pages"].pop()
        self.assertFalse(importer.normalize(config(), value)["paginationComplete"])

    def test_null_project_and_missing_key_remain_unknown(self):
        normalized = importer.normalize(config(), export(page(day(0, row(project=None)), day(1)), groups=["project_id"]))
        result = costs.reconcile(config(), attempts(), normalized)
        self.assertEqual(result["unattributedActualUsd"], "0.1")
        self.assertIsNone(result["dailyActualBuckets"][0]["environment"])
        self.assertIsNone(result["dailyActualBuckets"][0]["apiKeyId"])

    def test_missing_cost_and_empty_days_never_become_zero(self):
        normalized = importer.normalize(config(), export(page(day(0), day(1))))
        self.assertEqual(normalized["pages"][0]["buckets"], [])
        result = costs.reconcile(config(), attempts(attempt()), normalized)
        self.assertIsNone(result["dailyComparisons"][0]["observedActualUsd"])
        value = export(page(day(0, row()), day(1)))
        value["pages"][0]["response"]["data"][0]["results"][0]["amount"]["value"] = None
        self.reject("invalid_native_amount", value)

    def test_duplicate_days_and_partitions_rejected(self):
        self.reject("duplicate_or_outside_native_day", export(page(day(0), day(0))))
        self.reject("duplicate_native_cost_partition", export(page(day(0, row(), row()), day(1))))
        self.reject("overlapping_cost_buckets", export(page(day(0, row(), row(key="key_dev")), day(1))))

    def test_missing_grouping_filtered_query_and_contradictions_rejected(self):
        self.reject("unsupported_native_grouping", export(page(day(0), day(1)), groups=["line_item"]))
        self.reject("native_grouping_mismatch", export(page(day(0, row(key="key_dev")), day(1)), groups=["project_id"]))
        self.reject("native_grouping_mismatch", export(page(day(0, row(line="input")), day(1)), groups=["project_id"]))
        value = export(page(day(0), day(1)))
        value["line_items"] = ["input"]
        self.reject("invalid_fields", value)

    def test_broken_cursors_completion_and_cycles_rejected(self):
        self.reject("broken_native_page_chain", export(page(day(0), cursor="later")))
        self.reject("broken_native_page_chain", export(page(day(0), next_cursor="p2"), page(day(1), cursor="wrong")))
        self.reject("broken_native_page_chain", export(page(day(0)), page(day(1))))
        value = export(page(day(0)))
        value["pages"][0]["response"]["has_more"] = True
        self.reject("invalid_native_pagination", value)
        self.reject("invalid_native_pagination", export(page(day(0), next_cursor="p2"), page(day(1), cursor="p2", next_cursor="p2")))

    def test_complete_window_gaps_partial_buckets_and_foreign_projects_rejected(self):
        self.reject("incomplete_native_daily_window", export(page(day(0))))
        self.reject("incomplete_native_daily_window", export(page(day(1), next_cursor="p2")))
        value = export(page(day(0), day(1)))
        value["pages"][0]["response"]["data"][0]["start_time"] += 1
        self.reject("invalid_native_daily_interval", value)
        self.reject("unknown_cost_project", export(page(day(0, row(project="foreign")), day(1))))

    def test_cli_outputs_existing_schema_without_secrets_or_network(self):
        value = export(page(day(0, row()), day(1)))
        # Native JSON uses numeric amounts. _read preserves their Decimal value.
        value["pages"][0]["response"]["data"][0]["results"][0]["amount"]["value"] = 0.1
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root/"config.json").write_text(json.dumps(config()))
            (root/"export.json").write_text(json.dumps(value))
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                status = importer.main(["--config", str(root/"config.json"), "--export", str(root/"export.json")])
        self.assertEqual(status, 0)
        result = json.loads(output.getvalue())
        schema = json.loads(Path("schemas/sermon-cost-isolation-v1.schema.json").read_text())
        Draft202012Validator(schema).validate(result)
        import_schema = json.loads(Path("schemas/sermon-openai-costs-export-v1.schema.json").read_text())
        Draft202012Validator(import_schema).validate(value)

    def test_cli_fixed_error_and_invalid_native_values(self):
        output = io.StringIO()
        with contextlib.redirect_stderr(output):
            self.assertEqual(importer.main(["--credential", "private-input"]), 2)
        self.assertNotIn("private-input", output.getvalue())
        value = export(page(day(0, row()), day(1)))
        value["pages"][0]["response"]["data"][0]["results"][0]["amount"]["currency"] = "eur"
        self.reject("unsupported_currency", value)
        value["pages"][0]["response"]["data"][0]["results"][0]["amount"]["currency"] = "usd"
        value["pages"][0]["response"]["data"][0]["results"][0]["amount"]["value"] = float("nan")
        self.reject("invalid_native_amount", value)

    def test_native_schema_types_and_extreme_dates_fail_safely(self):
        for updates, code in [({"quantity": {}}, "invalid_native_quantity"),
                              ({"quantity": True}, "invalid_native_quantity"),
                              ({"quantity": float("inf")}, "invalid_native_quantity"),
                              ({"quantity_unit": []}, "invalid_native_quantity_unit"),
                              ({"amount": {"value": "0.1", "currency": "usd"}}, "invalid_native_amount")]:
            value = export(page(day(0, row()), day(1)))
            value["pages"][0]["response"]["data"][0]["results"][0].update(updates)
            self.reject(code, value)
        value = export(page({"object": "bucket", "start_time": 253402214400,
                             "end_time": 253402214400, "results": []}))
        value["queryWindow"] = {"startDay": "9999-12-30", "endDayExclusive": "9999-12-31"}
        self.reject("invalid_native_daily_interval", value)


if __name__ == "__main__":
    unittest.main()
