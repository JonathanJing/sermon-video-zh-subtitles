"""Independent offline audit of concurrent reservations and crash recovery."""
from concurrent.futures import ThreadPoolExecutor
import copy
from pathlib import Path
import tempfile
import threading
import unittest

from scripts.experiments import benchmark_layer2_bounded as subject


class TranslationBudgetSafetyTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.caps = copy.deepcopy(subject.CAPS)
        self.identity = "a" * 64
        policy = {role: {"model": model, "reasoningEffort": "medium"}
                  for role, model in subject.production.MODEL_ROLES.items()}
        self.payload = subject.production.model_payload("translator", {
            "instruction": "Translate the frozen source only.", "input": {"text": "Frozen source"}},
            policy, subject.LIMITS)

    def ledger(self):
        return subject.Ledger(self.root, self.identity, self.caps)

    def reserve(self, ledger, rid="request-0", arm=1):
        ledger.reserve(rid, arm, self.payload, self.root / (rid + ".raw.json"))

    def response(self, **usage):
        return {"id": "offline-response", "model": self.payload["model"], "service_tier": "default",
                "usage": {"prompt_tokens": 100, "completion_tokens": 40,
                          "total_tokens": 140, **usage}}

    def test_eight_threads_cannot_overbook_one_global_call_slot(self):
        self.caps["calls"] = 1
        ledger = self.ledger()
        barrier = threading.Barrier(8)

        def contender(index):
            barrier.wait(timeout=5)
            try:
                self.reserve(ledger, f"request-{index}")
            except ValueError:
                return False
            return True

        with ThreadPoolExecutor(max_workers=8) as pool:
            accepted = list(pool.map(contender, range(8)))
        self.assertEqual(sum(accepted), 1)
        state = subject.read(ledger.path)
        self.assertEqual(len(state["reservations"]), 1)
        self.assertEqual(sum(row["bounds"]["calls"] for row in state["reservations"].values()), 1)

    def test_unknown_reservation_blocks_restart_without_overwriting_evidence(self):
        ledger = self.ledger()
        self.reserve(ledger)
        before = ledger.path.read_bytes()
        with self.assertRaisesRegex(ValueError, "unknown|reconcile"):
            self.ledger()
        self.assertEqual(ledger.path.read_bytes(), before)

    def test_unknown_keeps_entire_worst_cost_reservation(self):
        ledger = self.ledger()
        self.reserve(ledger)
        row = subject.read(ledger.path)["reservations"]["request-0"]
        self.assertEqual(row["status"], "request_unconfirmed")
        self.assertEqual(row["bounds"]["outputTokens"], 2048)
        self.assertEqual(row["bounds"]["costMicrousd"],
            subject.cost(self.payload["model"], row["bounds"]["inputTokens"], 2048))
        self.assertIsNone(row["estimatedCostUpperBoundMicrousd"])

    def test_halt_is_durable_and_blocks_new_request_reservation(self):
        ledger = self.ledger()
        ledger.halt("offline injected unknown")
        with self.assertRaises(ValueError):
            self.reserve(ledger)
        with self.assertRaisesRegex(ValueError, "halted"):
            self.ledger()
        self.assertEqual(subject.read(ledger.path)["reservations"], {})

    def test_completed_request_never_refunds_or_replays_consumed_capacity(self):
        self.caps["calls"] = 1
        ledger = self.ledger()
        self.reserve(ledger)
        bounds = copy.deepcopy(subject.read(ledger.path)["reservations"]["request-0"]["bounds"])
        ledger.returned("request-0", self.response())
        resumed = self.ledger()
        with self.assertRaisesRegex(ValueError, "never replay"):
            self.reserve(resumed)
        with self.assertRaisesRegex(ValueError, "budget exhausted"):
            self.reserve(resumed, "request-1")
        self.assertEqual(subject.read(ledger.path)["reservations"]["request-0"]["bounds"], bounds)

    def test_invalid_usage_return_crash_window_blocks_restart(self):
        variants = [None, {"prompt_tokens": 9000, "completion_tokens": 1},
                    {"prompt_tokens": 1, "completion_tokens": 2049}]
        for index, usage in enumerate(variants):
            with self.subTest(usage=usage):
                self.root = self.root / f"variant-{index}"
                self.root.mkdir()
                ledger = self.ledger()
                self.reserve(ledger)
                response = self.response()
                response["usage"] = usage
                with self.assertRaises(ValueError):
                    ledger.returned("request-0", response)
                # Simulate process death before run_arm's outer halt handler.
                # Restart must fail closed using only the durable row.
                before = ledger.path.read_bytes()
                with self.assertRaises(ValueError):
                    self.ledger()
                self.assertEqual(ledger.path.read_bytes(), before)

    def test_inconsistent_total_cache_and_reasoning_counts_stop_durably(self):
        variants = [self.response(total_tokens=141),
                    self.response(prompt_tokens_details={"cached_tokens": 101}),
                    self.response(completion_tokens_details={"reasoning_tokens": 41})]
        for index, response in enumerate(variants):
            with self.subTest(response=response):
                self.root = self.root / f"counts-{index}"
                self.root.mkdir()
                ledger = self.ledger()
                self.reserve(ledger)
                with self.assertRaises(ValueError):
                    ledger.returned("request-0", response)
                with self.assertRaises(ValueError):
                    self.ledger()


if __name__ == "__main__":
    unittest.main()
