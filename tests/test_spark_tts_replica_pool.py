"""Exercise real spawn processes without Torch, CUDA, or model downloads."""
import os
import time
import unittest

from scripts import tongxing_host  # noqa: F401  binds the production package ports
from tongxing_production.compute.spark_tts_replica_pool import ReplicaPool, ReplicaPoolError


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



class ReplicaWindowTimingTests(unittest.TestCase):
    def test_each_window_keeps_its_worker_generation_time_once(self):
        pool = ReplicaPool("checkpoint", FakeEngine, {"device": "cuda:0", "dtype": "bfloat16"},
                           replicas=2, memory_reader=enough_memory, startup_timeout=10,
                           generation_timeout=5, poll_interval=0.02)
        with pool:
            pool.start()
            pool.submit(0, requests(0, delay=0.3), seed=1)
            pool.submit(8, requests(8), seed=2)
            pool.result(8)
            self.assertLess(pool.generation_seconds(8), 0.25)
            pool.result(0)
            self.assertGreaterEqual(pool.generation_seconds(0), 0.25)
            with self.assertRaisesRegex(ValueError, "timing is unavailable"):
                pool.generation_seconds(0)


class ParallelBatchEngineTimingTests(unittest.TestCase):
    def test_last_window_seconds_is_the_worker_time_not_the_parent_wait(self):
        import time as clock
        from scripts import tongxing_host  # noqa: F401  binds the production package ports
        from tongxing_production.compute.spark_tts_window_scheduler import ParallelBatchEngine

        class FakePool:
            replicas = 2

            def __init__(self):
                self.outputs, self.seconds = {}, {}

            def start(self):
                pass

            def submit(self, index, requests, *, seed):
                self.outputs[index] = [{"identity": row["identity"], "wave": [seed], "sampleRate": 24000}
                                       for row in requests]
                self.seconds[index] = 31.5 if index == 0 else 30.25

            def result(self, index):
                clock.sleep(0.01)  # the parent's wait is tiny and must not be reported as window time
                return self.outputs.pop(index)

            def generation_seconds(self, index):
                return self.seconds.pop(index)

        windows = {0: [{"identity": {"u": 0}, "text": "a"}], 8: [{"identity": {"u": 8}, "text": "b"}]}
        engine = ParallelBatchEngine(FakePool(), windows, seed=40, frozen_check=lambda: None)
        engine.batch(windows[0], seed=40)
        self.assertEqual(engine.last_window_seconds, 31.5)
        engine.batch(windows[8], seed=48)
        self.assertEqual(engine.last_window_seconds, 30.25)

if __name__ == "__main__":
    unittest.main()


class ReplicaMemoryTelemetryTests(unittest.TestCase):
    """Memory telemetry is metadata only; it never carries rows or sermon text."""
    def pool(self, **kwargs):
        defaults = dict(replicas=1, memory_reader=enough_memory, startup_timeout=10,
                        generation_timeout=5, poll_interval=0.02)
        defaults.update(kwargs)
        return ReplicaPool("checkpoint", FakeEngine, {"device": "cuda:0"}, **defaults)

    def test_every_event_samples_host_memory_and_workers_report_their_own(self):
        events = []
        with self.pool(telemetry=events.append) as pool:
            pool.start()
            pool.submit(0, requests(0), seed=42)
            pool.result(0)
        kinds = [event["kind"] for event in events]
        self.assertEqual(kinds, ["ready", "pool_ready", "submitted", "result", "pool_closed"])
        ready, pool_ready, submitted, result = events[:4]
        for event in (ready, pool_ready, submitted, result):
            self.assertEqual(event["memAvailableBytes"], enough_memory())
        self.assertIn("parentRssBytes", result)
        self.assertEqual(set(ready["memory"]), {"rssBytes", "cuda"})
        self.assertEqual(set(result["memory"]), {"rssBytes", "cuda"})
        self.assertIsNone(result["releaseSeconds"])  # release is off by default
        self.assertFalse(pool_ready["releaseCudaCache"])
        self.assertIn("cudaAllocConf", pool_ready)
        self.assertFalse(any("rows" in event for event in events))

    def test_release_option_is_explicit_and_reported(self):
        with self.assertRaisesRegex(ValueError, "release_cuda_cache"):
            self.pool(release_cuda_cache=1)
        events = []
        with self.pool(telemetry=events.append, release_cuda_cache=True) as pool:
            pool.start()
            pool.submit(0, requests(0), seed=42)
            pool.result(0)
        pool_ready = next(event for event in events if event["kind"] == "pool_ready")
        self.assertTrue(pool_ready["releaseCudaCache"])
        result = next(event for event in events if event["kind"] == "result")
        # Without CUDA in this process tree the worker reports no release timing.
        self.assertIn("releaseSeconds", result)

    def test_reserve_snapshot_keeps_each_workers_last_report(self):
        available = [enough_memory()]
        events = []
        pool = self.pool(memory_reader=lambda: available[0], telemetry=events.append)
        pool.start()
        pool.submit(0, requests(0, delay=0.3), seed=42)
        available[0] = 23 * 1024**3
        with self.assertRaisesRegex(ReplicaPoolError, "reserve"):
            pool.result(0)
        snapshot = next(event for event in events if event["kind"] == "reserve_failure")
        self.assertIn("parentRssBytes", snapshot)
        self.assertEqual(set(snapshot["workers"][0]), {"pid", "rssBytes", "lastReported"})
        self.assertEqual(set(snapshot["workers"][0]["lastReported"]), {"rssBytes", "cuda"})
