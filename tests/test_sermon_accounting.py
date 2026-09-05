import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import urllib.error

from scripts import sermon_accounting as a
from scripts import sermon_pipeline as pipeline


def response(ident="one", **extra):
    return {"id": ident, "model": "gpt-6-astra", "service_tier": "default",
        "usage": {"input_tokens": 1000, "output_tokens": 200,
                  "input_tokens_details": {"cached_tokens": 100, "cache_write_tokens": 400},
                  "output_tokens_details": {"reasoning_tokens": 50}}, **extra}


class AccountingTests(unittest.TestCase):
    def test_cache_writes_and_reasoning_not_double_billed(self):
        c=a.estimate_cost("gpt-6-astra",response()["usage"])
        self.assertAlmostEqual(c["estimatedUsd"], .0201)
        self.assertFalse(c["invoiceVerified"])

    def test_verified_notes_cost(self):
        u={"input_tokens":23779,"output_tokens":4712,"input_tokens_details":{"cached_tokens":0,"cache_write_tokens":23776}}
        self.assertAlmostEqual(a.estimate_cost("gpt-6-astra",u)["estimatedUsd"],.53283)

    def test_long_context_fast_and_unknown_models(self):
        u=response()["usage"];u["input_tokens"]=272001
        c=a.estimate_cost("gpt-6-astra",u,"fast")
        self.assertEqual(c["ratesPerMillion"]["input"],40)
        self.assertEqual(c["ratesPerMillion"]["output"],150)
        self.assertIsNone(a.estimate_cost("unknown-model",u)["estimatedUsd"])
        self.assertIsNone(a.estimate_cost("gpt-6-astra",u,"unknown-tier")["estimatedUsd"])

    def test_missing_usage_and_invalid_cache_are_unknown(self):
        self.assertIsNone(a.estimate_cost("gpt-6-astra",{})["estimatedUsd"])
        u=response()["usage"];u["input_tokens"]=3
        self.assertEqual(a.estimate_cost("gpt-6-astra",u)["reason"],"inconsistent_usage")

    def test_transcription_duration_is_not_execution_time(self):
        c=a.estimate_cost("gpt-transcribe",{"type":"duration","seconds":1771})
        self.assertAlmostEqual(c["estimatedUsd"],1771/60*.0045,places=8)
        self.assertIsNone(a.normalize_usage({"seconds":1771})["inputTokens"])

    def test_resume_separate_runs_duplicate_response_no_double_charge(self):
        with tempfile.TemporaryDirectory() as t:
            for _ in range(2):
                with a.accounting_session(t,"test"):
                    with a.stage("translate",billing="api"):
                        a.record_api_attempt("gpt-6-astra",response(),.1)
            d=a.summarize(t)
            self.assertEqual(len(d["runs"]),2)
            self.assertEqual(sum(r["apiAttempts"] for r in d["runs"]),1)
            self.assertAlmostEqual(sum(r["knownEstimatedUsd"] for r in d["runs"]),.0201)

    def test_failed_attempt_and_stage_persist_without_error_secrets(self):
        with tempfile.TemporaryDirectory() as t:
            with self.assertRaises(ValueError):
                with a.accounting_session(t,"test"):
                    with a.stage("translate",billing="api"):
                        a.record_api_attempt("gpt-6-astra",None,.1,"failed","HTTPError")
                        raise ValueError("secret-body-do-not-log")
            raw=(Path(t)/"events.jsonl").read_text();self.assertNotIn("secret-body",raw)
            d=a.summarize(t);self.assertEqual(d["runs"][0]["status"],"failed")
            self.assertEqual(d["runs"][0]["unknownCostAttempts"],1)
            self.assertFalse(d["unfinishedStages"])

    def test_individual_usage_fields_remain_unknown(self):
        with tempfile.TemporaryDirectory() as t:
            with a.accounting_session(t,"test"):
                a.record_api_attempt("gpt-6-astra",response(usage={"input_tokens":10,"output_tokens":3}),.1)
            row=next(r for r in a.summarize(t)["stages"] if r["apiAttempts"])
            self.assertEqual(row["inputTokens"],10)
            self.assertIsNone(row["cacheWriteTokens"])
            self.assertIsNone(row["reasoningTokens"])
            self.assertEqual(row["costStatus"],"partial")

    def test_subprocess_inherits_and_cache_has_no_api_tokens(self):
        with tempfile.TemporaryDirectory() as t:
            with a.accounting_session(t,"parent"):
                with a.stage("child_stage",billing="orchestrator"):
                    subprocess.run([sys.executable,"-c", "from scripts.sermon_accounting import *; "
                        +"record_api_attempt('gpt-6-astra', {'usage': {'input_tokens': 7, 'output_tokens': 2}}, .1)"],check=True)
                with a.stage("cache",cache_hit=True):pass
            d=a.summarize(t)
            self.assertEqual(len(d["runs"]),1)
            row=next(r for r in d["stages"] if r["stage"]=="child_stage")
            self.assertEqual(row["inputTokens"],7)
            cache=next(r for r in d["stages"] if r["stage"]=="cache")
            self.assertEqual(cache["cacheHits"],1);self.assertIsNone(cache["inputTokens"])

    def test_http_retry_records_each_attempt(self):
        raw=json.dumps(response()).encode()
        ok=unittest.mock.MagicMock();ok.__enter__.return_value.read.return_value=raw
        error=urllib.error.HTTPError("https://api.openai.com",503,"bad",{},io.BytesIO(b"private"))
        with tempfile.TemporaryDirectory() as t, patch.object(pipeline.urllib.request,"urlopen",side_effect=[error,ok]), patch.object(pipeline.time,"sleep"):
            with a.accounting_session(t,"test"):
                r=pipeline.json_request(pipeline.CHAT_URL,"private-key",{"model":"gpt-6-astra"},retries=2)
            rows=[json.loads(x) for x in (Path(t)/"events.jsonl").read_text().splitlines()]
            calls=[r for r in rows if r["event"]=="api_attempt"]
            self.assertEqual([r["status"] for r in calls],["failed","completed"])
            self.assertNotIn("private",(Path(t)/"events.jsonl").read_text())

    def test_unfinished_span_detected(self):
        with tempfile.TemporaryDirectory() as t, patch.dict(os.environ,{"SERMON_ACCOUNTING_DIR":t,"SERMON_ACCOUNTING_RUN_ID":"interrupted"}):
            a._emit({"event":"stage_started","stage":"lost","spanId":"open","startedAt":a.now()})
            d=a.summarize(t);self.assertEqual(len(d["unfinishedStages"]),1)
            self.assertIsNone(d["unfinishedStages"][0]["elapsedSeconds"])

    def test_hard_interruption_preserves_potential_billable_attempt(self):
        with tempfile.TemporaryDirectory() as t:
            code = "import os; from scripts.sermon_accounting import *\nwith accounting_session(" + repr(t) + ", 'killed'):\n record_api_started('gpt-6-astra')\n os._exit(9)\n"
            done = subprocess.run([sys.executable, "-c", code])
            self.assertEqual(done.returncode, 9)
            d = a.summarize(t)
            self.assertEqual(d["runs"][0]["unknownCostAttempts"], 1)
            self.assertEqual(d["runs"][0]["apiAttempts"], 1)
            self.assertEqual(len(d["unfinishedApiAttempts"]), 1)
            row = next(r for r in d["stages"] if r["apiAttempts"])
            self.assertIsNone(row["elapsedSeconds"])
            self.assertIsNone(row["apiLatencySeconds"])
            self.assertEqual(row["missingLatencyAttempts"], 1)

    def test_keyboard_interrupt_records_one_attempt(self):
        with tempfile.TemporaryDirectory() as t, patch.object(pipeline.urllib.request, "urlopen", side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                with a.accounting_session(t, "test"):
                    pipeline.json_request(pipeline.CHAT_URL, "not-recorded", {"model": "gpt-6-astra"})
            d = a.summarize(t)
            self.assertEqual(d["runs"][0]["apiAttempts"], 1)
            self.assertEqual(d["runs"][0]["unknownCostAttempts"], 1)
            self.assertFalse(d["unfinishedApiAttempts"])

    def test_completed_request_with_unfinished_stage_is_not_zero_seconds(self):
        with tempfile.TemporaryDirectory() as t, patch.dict(os.environ, {"SERMON_ACCOUNTING_DIR": t, "SERMON_ACCOUNTING_RUN_ID": "interrupted", "SERMON_ACCOUNTING_STAGE": "generate", "SERMON_ACCOUNTING_SPAN": "open"}):
            a._emit({"event": "stage_started", "stage": "generate", "spanId": "open", "startedAt": a.now()})
            a.record_api_attempt("gpt-6-astra", response(), 8.5)
            row = a.summarize(t)["stages"][0]
            self.assertIsNone(row["elapsedSeconds"])
            self.assertEqual(row["unfinishedStageAttempts"], 1)
            self.assertEqual(row["apiLatencySeconds"], 8.5)

    def test_partial_tail_preserved_and_next_run_can_append(self):
        with tempfile.TemporaryDirectory() as t:
            with a.accounting_session(t, "before"):
                a.record_api_started("gpt-6-astra")
            path = Path(t) / "events.jsonl"
            original = path.read_bytes() + b'{"event":"api_attempt", "truncated":"\xe4'
            path.write_bytes(original)
            first = a.summarize(t)
            self.assertEqual(first["ledgerIntegrity"]["status"], "incomplete_corrupt_events")
            self.assertTrue(first["ledgerIntegrity"]["unattributedCostUnknown"])
            self.assertEqual(first["runs"][0]["unknownCostAttempts"], 1)
            self.assertEqual(path.read_bytes(), original)
            with a.accounting_session(t, "after"):
                pass
            final = a.summarize(t)
            self.assertTrue(path.read_bytes().startswith(original + b"\n"))
            self.assertEqual(len(final["runs"]), 2)
            self.assertEqual(final["runs"][-1]["status"], "completed")
            self.assertEqual(len(final["ledgerIntegrity"]["damagedEvents"]), 1)
            self.assertNotIn('"truncated":', json.dumps(final))

    def test_concurrent_processes_keep_all_runs_and_current_summary(self):
        with tempfile.TemporaryDirectory() as t:
            code = "from scripts.sermon_accounting import *\nwith accounting_session(" + repr(t) + ", 'worker'):\n record_api_attempt('gpt-6-astra', {}, .1)\n"
            children = [subprocess.Popen([sys.executable, "-c", code]) for _ in range(5)]
            self.assertEqual([p.wait() for p in children], [0]*5)
            saved = json.loads((Path(t)/"summary.json").read_text())
            self.assertEqual(len(saved["runs"]), 5)
            self.assertEqual(sum(r["apiAttempts"] for r in saved["runs"]), 5)
            self.assertTrue(all(r["status"] == "completed" for r in saved["runs"]))

if __name__ == "__main__": unittest.main()
