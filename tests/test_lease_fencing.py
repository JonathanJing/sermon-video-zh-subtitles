"""Lease failure injection uses local processes and an in-memory GCS emulator only."""
import json
import multiprocessing
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from google.api_core.exceptions import NotFound, PreconditionFailed

from backend import leases
from scripts import sermon_production_supervisor as supervisor


def contend(location, start, output):
    start.wait(5)
    handle = leases.acquire_lease(location, owner="contender")
    output.put(None if handle is None else (handle.token, handle.generation))


class FakeGcs:
    """Each blob instance receives only its own upload generation, like GCS."""
    def __init__(self):
        self.payload = None
        self.generation = 0
        self.calls = []
        self.after_upload = None
        self.after_download = None

    def bucket(self, _name):
        return self

    def blob(self, _name):
        store = self

        class Blob:
            generation = None

            def reload(self, **_kwargs):
                if store.payload is None:
                    raise NotFound("missing")
                self.generation = store.generation

            def download_as_bytes(self, *, if_generation_match, **_kwargs):
                store.calls.append(("read", if_generation_match))
                if store.payload is None:
                    raise NotFound("missing")
                if if_generation_match != store.generation:
                    raise PreconditionFailed("changed")
                result = store.payload
                if store.after_download:
                    callback, store.after_download = store.after_download, None
                    callback()
                return result

            def upload_from_string(self, text, *, if_generation_match, **_kwargs):
                store.calls.append(("write", if_generation_match))
                current = store.generation if store.payload is not None else 0
                if if_generation_match != current:
                    raise PreconditionFailed("changed")
                store.generation += 1
                store.payload = text.encode()
                self.generation = store.generation
                if store.after_upload:
                    callback, store.after_upload = store.after_upload, None
                    callback()

            def delete(self, *, if_generation_match, **_kwargs):
                store.calls.append(("delete", if_generation_match))
                if store.payload is None:
                    raise NotFound("missing")
                if if_generation_match != store.generation:
                    raise PreconditionFailed("changed")
                store.payload = None

        return Blob()

    def replace_with_successor(self):
        payload = json.loads(self.payload)
        self.payload = json.dumps({**payload, "token": "successor-token", "owner": "successor"}).encode()
        self.generation += 1


class LocalLeaseFencingTests(unittest.TestCase):
    def test_renewal_extends_expiry_without_changing_acquisition_epoch(self):
        with tempfile.TemporaryDirectory() as tmp:
            now = datetime.now(timezone.utc)
            handle = leases.acquire_lease(str(Path(tmp) / "lease.json"), ttl_seconds=10, now=now)
            renewed = leases.renew_lease(handle, ttl_seconds=20, now=now + timedelta(seconds=5))
            self.assertEqual((handle.token, handle.generation), (renewed.token, renewed.generation))
            leases.assert_lease_owned(renewed, now=now + timedelta(seconds=15))
            self.assertIsNone(leases.acquire_lease(handle.location, now=now + timedelta(seconds=15)))

    def test_expired_same_owner_is_fenced_and_cannot_release_successor(self):
        with tempfile.TemporaryDirectory() as tmp:
            now = datetime.now(timezone.utc)
            old = leases.acquire_lease(str(Path(tmp) / "lease.json"), owner="same-owner", ttl_seconds=1, now=now)
            takeover = now + timedelta(seconds=2)
            with self.assertRaises(leases.LeaseLost):
                leases.renew_lease(old, now=takeover)
            new = leases.acquire_lease(old.location, owner="same-owner", now=takeover)
            self.assertNotEqual(old.token, new.token)
            self.assertGreater(new.generation, old.generation)
            for action in (leases.assert_lease_owned, leases.renew_lease):
                with self.assertRaises(leases.LeaseLost):
                    action(old, now=takeover)
            leases.release_lease(old)
            leases.assert_lease_owned(new, now=takeover)
            leases.release_lease(new)
            third = leases.acquire_lease(old.location)
            self.assertGreater(third.generation, new.generation)

    def test_legacy_active_record_is_not_rewritten_or_adopted(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "lease.json"
            raw = json.dumps({"schemaVersion": 1, "owner": "legacy", "status": "active",
                "expiresAt": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()})
            path.write_text(raw)
            self.assertIsNone(leases.acquire_lease(str(path)))
            leases.release_lease(leases.LeaseHandle(str(path), "legacy"))
            self.assertEqual(path.read_text(), raw)

    def test_expired_takeover_has_one_winner_across_real_processes(self):
        with tempfile.TemporaryDirectory() as tmp:
            location = str(Path(tmp) / "lease.json")
            old = leases.acquire_lease(location, ttl_seconds=1, now=datetime.now(timezone.utc) - timedelta(seconds=2))
            context = multiprocessing.get_context("fork")
            start, output = context.Event(), context.Queue()
            processes = [context.Process(target=contend, args=(location, start, output)) for _ in range(6)]
            try:
                for process in processes:
                    process.start()
                start.set()
                results = [output.get(timeout=5) for _ in processes]
                for process in processes:
                    process.join(5)
                    self.assertEqual(process.exitcode, 0)
                self.assertEqual(sum(value is not None for value in results), 1)
                leases.release_lease(old)
                self.assertIsNone(leases.acquire_lease(location))
            finally:
                for process in processes:
                    if process.is_alive():
                        process.kill()
                        process.join()
                output.close()


class GcsLeaseFencingTests(unittest.TestCase):
    def setUp(self):
        self.store = FakeGcs()
        self.client = mock.patch("google.cloud.storage.Client", return_value=self.store)
        self.client.start()
        self.addCleanup(self.client.stop)
        self.location = "gs://test-only/lease.json"

    def test_renewal_and_release_always_use_generation_conditions(self):
        old = leases.acquire_lease(self.location)
        renewed = leases.renew_lease(old)
        self.assertGreater(renewed.generation, old.generation)
        leases.release_lease(old)
        leases.assert_lease_owned(renewed)
        leases.release_lease(renewed)
        self.assertIsNone(self.store.payload)
        self.assertTrue(all(generation is not None for _, generation in self.store.calls))

    def test_same_owner_takeover_cannot_be_renewed_or_released_by_old_handle(self):
        now = datetime.now(timezone.utc)
        old = leases.acquire_lease(self.location, owner="same", ttl_seconds=1, now=now)
        later = now + timedelta(seconds=2)
        with self.assertRaises(leases.LeaseLost):
            leases.renew_lease(old, now=later)
        new = leases.acquire_lease(self.location, owner="same", now=later)
        with self.assertRaises(leases.LeaseLost):
            leases.renew_lease(old, now=later)
        leases.release_lease(old)
        leases.assert_lease_owned(new, now=later)

    def test_takeover_between_read_and_renew_upload_is_fenced(self):
        old = leases.acquire_lease(self.location)
        self.store.after_download = self.store.replace_with_successor
        with self.assertRaises(leases.LeaseLost):
            leases.renew_lease(old)
        leases.release_lease(old)
        self.assertEqual(json.loads(self.store.payload)["owner"], "successor")

    def test_takeover_between_release_read_and_delete_preserves_new_owner(self):
        old = leases.acquire_lease(self.location)
        self.store.after_download = self.store.replace_with_successor
        leases.release_lease(old)
        self.assertEqual(json.loads(self.store.payload)["owner"], "successor")

    def test_acquire_uses_upload_generation_without_reloading_a_successor(self):
        self.store.after_upload = self.store.replace_with_successor
        handle = leases.acquire_lease(self.location)
        self.assertLess(handle.generation, self.store.generation)
        leases.release_lease(handle)
        self.assertEqual(json.loads(self.store.payload)["owner"], "successor")

    def test_expired_acquire_loses_cas_to_another_takeover(self):
        leases.acquire_lease(self.location, ttl_seconds=1, now=datetime.now(timezone.utc) - timedelta(seconds=2))
        self.store.after_download = self.store.replace_with_successor
        self.assertIsNone(leases.acquire_lease(self.location, owner="late-contender"))
        self.assertEqual(json.loads(self.store.payload)["owner"], "successor")


class SupervisorLeaseExecutionTests(unittest.TestCase):
    def fixture(self, root, command, *, ttl=.6):
        config = supervisor.SupervisorConfig(sunday="2026-09-06", state_file=str(root / "unused.json"),
            work_root=root, gcs_bucket=None, lease_ttl_seconds=ttl)
        snapshot = {"recommendedAction": {"action": "run_timeline_probe"}, "locations": {
            "timelineLeaseLocal": str(root / "lease.json"), "timelineReportLocal": str(root / "report.json")}}
        return config, snapshot, [mock.patch.object(supervisor, "production_snapshot", return_value=snapshot),
            mock.patch.object(supervisor, "ensure_source_lock"),
            mock.patch.object(supervisor, "build_timeline_command", return_value=command)]

    def test_real_timeline_child_completes_after_multiple_original_ttls(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            command = [sys.executable, "-c", "import time,json,pathlib;time.sleep(1);pathlib.Path(" + repr(str(root / "report.json")) + ").write_text(json.dumps({'status':'requires_operator_review'}))"]
            config, _, patches = self.fixture(root, command, ttl=.3)
            with patches[0], patches[1], patches[2]:
                result = supervisor.run_timeline_probe(config)
            self.assertEqual(result["status"], "requires_operator_review")
            self.assertFalse((root / "lease.json").exists())

    def test_takeover_kills_real_child_group_and_cannot_release_successor(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            heartbeat = root / "child-heartbeat"
            child = "import pathlib,time; p=pathlib.Path(" + repr(str(heartbeat)) + ");\nwhile True: p.write_text(str(time.monotonic())); time.sleep(.02)"
            code = "import subprocess,sys,time; subprocess.Popen([sys.executable,'-c'," + repr(child) + "]);time.sleep(20)"
            config, snapshot, patches = self.fixture(root, [sys.executable, "-c", code])
            replacement, errors = [], []

            def takeover():
                try:
                    deadline = time.monotonic() + 5
                    while not heartbeat.exists() and time.monotonic() < deadline:
                        time.sleep(.01)
                    if not heartbeat.exists():
                        raise AssertionError("Real grandchild never started")
                    replacement.append(leases.acquire_lease(snapshot["locations"]["timelineLeaseLocal"], owner="successor",
                        now=datetime.now(timezone.utc) + timedelta(seconds=2)))
                except Exception as error:
                    errors.append(error)

            contender = threading.Thread(target=takeover)
            contender.start()
            started = time.monotonic()
            with patches[0], patches[1], patches[2], mock.patch.object(supervisor, "command_result") as result:
                with self.assertRaises(leases.LeaseLost):
                    supervisor.run_timeline_probe(config)
                result.assert_not_called()
            contender.join(5)
            self.assertFalse(errors)
            self.assertLess(time.monotonic() - started, 3)
            self.assertIsNotNone(replacement[0])
            leases.assert_lease_owned(replacement[0])
            last = heartbeat.read_text()
            time.sleep(.15)
            self.assertEqual(heartbeat.read_text(), last, "grandchild kept writing after lease loss")

    def test_hung_renewal_still_terminates_execution_at_local_deadline(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            gate, started = threading.Event(), threading.Event()
            count = 0
            guards = []

            def blocked_renew(handle, **kwargs):
                nonlocal count
                count += 1
                if count > 1:
                    started.set()
                    gate.wait(5)
                return leases.renew_lease(handle, **kwargs)

            def factory(handle, **kwargs):
                guard = leases.LeaseGuard(handle, renewer=blocked_renew, **kwargs)
                guards.append(guard)
                return guard
            config, _, patches = self.fixture(root, [sys.executable, "-c", "import time;time.sleep(20)"])
            before = time.monotonic()
            try:
                with patches[0], patches[1], patches[2], mock.patch.object(supervisor, "LeaseGuard", side_effect=factory):
                    with self.assertRaises(leases.LeaseLost):
                        supervisor.run_timeline_probe(config)
                self.assertTrue(started.is_set())
                self.assertLess(time.monotonic() - before, 3)
            finally:
                gate.set()
                for guard in guards:
                    guard._thread.join(2)
                    self.assertFalse(guard._thread.is_alive())

    def test_publication_stops_between_supporting_evidence_and_commit_marker(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            handle = leases.acquire_lease(str(root / "lease.json"), ttl_seconds=1)
            (root / "status.json").write_text('{"status":"completed"}')
            calls, replacement = [], []

            def writer(location, text):
                calls.append(location)
                replacement.append(leases.acquire_lease(handle.location, owner="successor", now=datetime.now(timezone.utc) + timedelta(seconds=2)))

            with self.assertRaises(leases.LeaseLost), leases.LeaseGuard(handle, ttl_seconds=1) as guard:
                supervisor.publish_generation_evidence({"runStatusLocal": str(root / "status.json"),
                    "runStatusGcs": "gs://test-only/run-status.json", "generationReportGcs": "gs://test-only/commit.json"},
                    {"status": "completed"}, gcs_writer=writer, guard=guard)
            self.assertEqual(calls, ["gs://test-only/run-status.json"])
            leases.assert_lease_owned(replacement[0])

    def test_fenced_generation_result_never_reaches_evidence_publication(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            handle = leases.acquire_lease(str(root / "lease.json"), ttl_seconds=1)
            config = supervisor.SupervisorConfig(sunday="2026-09-06", state_file="unused", gcs_bucket=None)
            replacement = []

            def runner(command, **kwargs):
                replacement.append(leases.acquire_lease(handle.location, owner="successor", now=datetime.now(timezone.utc) + timedelta(seconds=2)))
                return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

            with mock.patch.object(supervisor, "validate_generation_archive_identity"), mock.patch.object(supervisor, "materialize_approval_evidence"), mock.patch.object(supervisor, "build_generation_command", return_value=["fixture"]), mock.patch.object(supervisor, "publish_generation_evidence") as publish, mock.patch.object(supervisor, "write_local_json") as write:
                with self.assertRaises(leases.LeaseLost), leases.LeaseGuard(handle, ttl_seconds=1) as guard:
                    supervisor.execute_reading_pdf_generation(config, {"locations": {"generationReportLocal": str(root / "report.json")}}, {}, runner=runner, guard=guard)
                publish.assert_not_called()
                write.assert_not_called()
            leases.assert_lease_owned(replacement[0])


if __name__ == "__main__":
    unittest.main()
