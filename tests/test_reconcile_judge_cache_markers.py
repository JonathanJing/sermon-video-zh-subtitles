import json
from pathlib import Path
import tempfile
import unittest

from tests import experiment_modules
from scripts import tongxing_host  # noqa: F401  binds the production package ports
from tongxing_production.source import english_source_judge_cache as cache
from tongxing_production.source.sentence_interpretation_models import RUN_SCHEMA

tool = experiment_modules.load("tools/ops/reconcile_judge_cache_markers.py")

ANSWER = {"schemaVersion": "sermon-english-source-machine-judge-batch-v1", "sentences": [
    {"sourceSentenceId": "chunk-0000-s001", "sourceUnitIds": ["chunk-0000-u001"], "verdict": "pass", "risk": "low",
     "checks": {}, "evidence": "fixture", "unresolvedIssues": []}]}


def payload(sentence_ids):
    return {"model": "claude-opus-5-5", "reasoning_effort": "high", "max_completion_tokens": 4096,
            "messages": [{"role": "system", "content": "Judge."},
                         {"role": "user", "content": json.dumps({"sentences": [{"sourceSentenceId": s} for s in sentence_ids]})}]}


class ReconcileJudgeCacheMarkersTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.cache_root = self.root / "judge-cache"
        self.calls = self.root / "claude-cli-calls"

    def marker(self, sentence_ids):
        request = {"schemaVersion": RUN_SCHEMA, "stage": "english-source-judge", "payload": payload(sentence_ids)}
        request_hash = cache.contract.json_sha256(request)
        (self.cache_root / "cache").mkdir(parents=True, exist_ok=True)
        marker = self.cache_root / "cache" / f"english-source-judge-{request_hash}.started.json"
        marker.write_text(json.dumps({"requestSha256": request_hash, "request": request,
                                      "status": "started_response_unconfirmed"}))
        return request, request_hash

    def call(self, name, sentence_ids, **overrides):
        directory = self.calls / name
        directory.mkdir(parents=True)
        content = dict(ANSWER, sentences=[dict(ANSWER["sentences"][0], sourceSentenceId=s) for s in sentence_ids])
        response = {"schemaVersion": "claude-layer2-cli-response-v1", "id": f"claude:{name}", "sessionId": name,
                    "requestedModel": "claude-opus-5-5", "reportedModels": ["claude-opus-5-5"],
                    "requestedEffort": "high", "completed": True, "exitCode": 0,
                    "content": json.dumps(content), "usage": {"inputTokens": 10, "outputTokens": 300},
                    "modelUsage": {"claude-opus-5-5": {"inputTokens": 10, "outputTokens": 300}},
                    "auxiliaryModelUsage": {}, "listPriceUsd": 0.05, "numTurns": 2, "elapsedSeconds": 18.0,
                    "apiDurationMs": 17000, "enabledTools": []}
        response.update(overrides)
        (directory / "response.json").write_text(json.dumps(response))

    def test_marker_is_bound_to_the_one_returned_call_and_replays_without_a_provider(self):
        request, request_hash = self.marker(["chunk-0000-s001", "chunk-0000-s002"])
        self.call("a", ["chunk-0000-s001", "chunk-0000-s002"])
        self.call("other", ["chunk-0000-s003"])
        report = tool.reconcile(self.cache_root, [self.calls], identity=lambda model, effort: {"test": True})
        self.assertEqual([row["call"] for row in report["reconciled"]], ["a"])
        self.assertEqual(report["unresolved"], [])
        receipt = json.loads((self.cache_root / "cache" / f"english-source-judge-{request_hash}.json").read_text())
        self.assertEqual(receipt["requestSha256"], request_hash)
        self.assertEqual(receipt["response"]["claudeCli"]["executionIdentity"], {"test": True})
        # The cache now replays the answer; no caller runs.
        result, _ = cache.cached_call(out=self.cache_root, stage="english-source-judge", payload=request["payload"],
                                      api_key="", requested_model="claude-opus-5-5",
                                      caller=lambda *args: self.fail("provider must not be called"))
        self.assertEqual([row["sourceSentenceId"] for row in result["sentences"]], ["chunk-0000-s001", "chunk-0000-s002"])

    def test_ambiguous_or_missing_calls_leave_the_marker_unknown(self):
        self.marker(["chunk-0000-s001"])
        self.call("a", ["chunk-0000-s001"])
        self.call("b", ["chunk-0000-s001"])
        report = tool.reconcile(self.cache_root, [self.calls], identity=lambda model, effort: None)
        self.assertEqual(report["reconciled"], [])
        self.assertEqual(report["unresolved"][0]["matches"], 2)
        self.assertEqual(len(list((self.cache_root / "cache").glob("*.started.json"))), 1)
        self.assertEqual(len([p for p in (self.cache_root / "cache").glob("*.json") if not p.name.endswith(".started.json")]), 0)


if __name__ == "__main__":
    unittest.main()
