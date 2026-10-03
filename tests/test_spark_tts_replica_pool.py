"""Exercise real spawn processes without Torch, CUDA, or model downloads."""
import os
import time
import unittest

from scripts.spark_tts_replica_pool import ReplicaPool, ReplicaPoolError


class FakeEngine:
    def __init__(self, checkpoint, *, load_delay=0, load_error=False, load_crash=False, **kwargs):
        time.sleep(load_delay)
        if load_crash:
            os._exit(9)
        if load_error:
            raise RuntimeError("fake load error")
        self.checkpoint, self.kwargs = checkpoint, kwargs

    def batch(self, requests, *, seed):
        time.sleep(requests[0].get("delay", 0))
        if requests[0].get("crash"):
            os._exit(7)
        if requests[0].get("error"):
            raise RuntimeError("fake inference error")
        return [{"identity": row["identity"], "wave": [seed], "sampleRate": 24000,
                 "pid": os.getpid(), "checkpoint": self.checkpoint,
                 "kwargs": self.kwargs} for row in requests]


def requests(index, **settings):
    return [{"identity": {"unitIndex": index}, "text": f"unit {index}", **settings}]


def enough_memory():
    return 128 * 1024**3


class ReplicaPoolTests(unittest.TestCase):
    def pool(self, **kwargs):
        defaults = dict(replicas=2, memory_reader=enough_memory,
                        startup_timeout=10, generation_timeout=5, poll_interval=0.02)
        defaults.update(kwargs)
        return ReplicaPool("checkpoint", FakeEngine, {"device": "cuda:0", "dtype": "bfloat16"}, **defaults)

    def assert_closed(self, pool):
        self.assertTrue(pool._closed)
        self.assertTrue(all(not process.is_alive() for process in pool.processes))

    def test_lazy_start_all_ready_and_bounded_ordered_consumption(self):
        events = []
        parent_pid = os.getpid()
        pool = self.pool(telemetry=lambda event: events.append((os.getpid(), event)))
        self.assertEqual(pool.processes, [])
        with pool:
            pool.start()
            self.assertEqual(len(pool._ready), 2)
            pool.submit(0, requests(0, delay=0.15), seed=42)
            pool.submit(8, requests(8), seed=50)
            with self.assertRaisesRegex(ValueError, "Consume"):
                pool.submit(16, requests(16), seed=58)
            # Collect the fast window first without consuming its capacity.
            deadline = time.monotonic() + 5
            while 8 not in pool._outputs and time.monotonic() < deadline:
                pool._receive(0.02)
            self.assertIn(8, pool._outputs)
            self.assertEqual(pool.outstanding, 2)
            first = pool.result(0)
            pool.submit(16, requests(16), seed=58)
            second, third = pool.result(8), pool.result(16)
            self.assertEqual([first[0]["wave"], second[0]["wave"], third[0]["wave"]], [[42], [50], [58]])
            self.assertEqual([first[0]["identity"], second[0]["identity"]],
                             [{"unitIndex": 0}, {"unitIndex": 8}])
            self.assertNotEqual(first[0]["pid"], second[0]["pid"])
            self.assertEqual(first[0]["pid"], third[0]["pid"])
            self.assertEqual(first[0]["kwargs"], {"device": "cuda:0", "dtype": "bfloat16"})
            self.assertEqual(pool.outstanding, 0)
        self.assert_closed(pool)
        self.assertTrue(all(pid == parent_pid for pid, _ in events))
        ready = [event for _, event in events if event["kind"] == "ready"]
        self.assertEqual(len(ready), 2)
        self.assertTrue(all("loadSeconds" in event and "timestamp" in event for event in ready))
        self.assertFalse(any("rows" in event for _, event in events))

    def test_batch_order_and_inputs_are_frozen(self):
        with self.pool(replicas=1) as pool:
            pool.start()
            batch = requests(0) + requests(1)
            pool.submit(0, batch, seed=42)
            batch[0]["identity"]["unitIndex"] = 999
            rows = pool.result(0)
            self.assertEqual([row["identity"]["unitIndex"] for row in rows], [0, 1])
            with self.assertRaisesRegex(ValueError, "unique"):
                pool.submit(0, requests(0), seed=42)

    def test_inference_error_or_crash_cleans_owned_workers(self):
        for settings in ({"error": True}, {"crash": True}):
            with self.subTest(settings=settings):
                pool = self.pool()
                pool.start()
                pool.submit(0, requests(0, **settings), seed=42)
                with self.assertRaises(ReplicaPoolError):
                    pool.result(0)
                self.assert_closed(pool)

    def test_guard_before_start_creates_no_processes(self):
        pool = self.pool(memory_reader=lambda: 23 * 1024**3)
        with self.assertRaisesRegex(ReplicaPoolError, "reserve"):
            pool.start()
        self.assertEqual(pool.processes, [])
        self.assert_closed(pool)

    def test_guard_during_wait_closes_workers(self):
        available = [128 * 1024**3]
        events = []
        pool = self.pool(memory_reader=lambda: available[0], telemetry=events.append)
        pool.start()
        pool.submit(0, requests(0, delay=1), seed=42)
        available[0] = 23 * 1024**3
        with self.assertRaisesRegex(ReplicaPoolError, "reserve"):
            pool.result(0)
        self.assert_closed(pool)
        self.assertEqual(pool.min_available_bytes, 23 * 1024**3)
        self.assertEqual(events[-1]["kind"], "pool_closed")
        self.assertEqual(events[-1]["minAvailableBytes"], 23 * 1024**3)

    def test_startup_and_generation_deadlines(self):
        pool = ReplicaPool("checkpoint", FakeEngine, {"load_delay": 2}, replicas=1,
                           memory_reader=enough_memory, startup_timeout=0.1, poll_interval=0.02)
        with self.assertRaisesRegex(ReplicaPoolError, "load timeout"):
            pool.start()
        self.assert_closed(pool)
        pool = self.pool(replicas=1, generation_timeout=0.05)
        pool.start()
        pool.submit(0, requests(0, delay=2), seed=42)
        with self.assertRaisesRegex(ReplicaPoolError, "generation timeout"):
            pool.result(0)
        self.assert_closed(pool)

    def test_model_load_failure_cleanup(self):
        pool = ReplicaPool("checkpoint", FakeEngine, {"load_error": True}, replicas=1,
                           memory_reader=enough_memory, startup_timeout=10, poll_interval=0.02)
        with self.assertRaises(ReplicaPoolError):
            pool.start()
        self.assert_closed(pool)

    def test_model_load_crash_exits_without_waiting_for_deadline(self):
        pool = ReplicaPool("checkpoint", FakeEngine, {"load_crash": True}, replicas=2,
                           memory_reader=enough_memory, startup_timeout=10, poll_interval=0.02)
        started = time.monotonic()
        with self.assertRaises(ReplicaPoolError):
            pool.start()
        self.assertLess(time.monotonic() - started, 5)
        self.assert_closed(pool)

    def test_context_exception_cleanup(self):
        pool = self.pool()
        with self.assertRaisesRegex(ValueError, "caller failure"):
            with pool:
                pool.start()
                raise ValueError("caller failure")
        self.assert_closed(pool)


if __name__ == "__main__":
    unittest.main()
