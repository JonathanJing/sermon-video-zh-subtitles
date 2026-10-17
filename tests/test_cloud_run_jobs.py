import unittest
from types import SimpleNamespace
from unittest import mock

from backend import cloud_run_jobs
from backend import app as backend_app
from tongxing_api import cloud_run_jobs as service_jobs


class FakeResponse:
    def __init__(self, payload, status_code=200):
        self.payload = payload
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self.payload


class FakeSession:
    def __init__(self):
        self.calls = []

    def post(self, url, *, json, timeout):
        self.calls.append({"url": url, "json": json, "timeout": timeout})
        return FakeResponse({"name": "operations/supervisor-run-1"})


class CloudRunJobsTest(unittest.TestCase):
    def test_legacy_service_and_backend_app_share_dispatcher(self):
        self.assertIs(cloud_run_jobs, service_jobs)
        self.assertIs(backend_app.dispatch_cloud_run_job, service_jobs.dispatch_cloud_run_job)
        handler = object.__new__(backend_app.ApiHandler)
        handler.config = SimpleNamespace(supervisor_job_project="ai-for-god",
            supervisor_job_location="us-west1", supervisor_job_name="sermon-production-supervisor",
            supervisor_job_container="supervisor", supervisor_job_timeout_seconds=7200)
        with mock.patch.object(backend_app, "dispatch_cloud_run_job",
                               return_value={"status": "dispatched"}) as dispatch:
            self.assertEqual({"status": "dispatched"},
                             handler.dispatch_production_supervisor_job(["python", "runner.py"]))
        dispatch.assert_called_once_with(project="ai-for-god", location="us-west1",
            job="sermon-production-supervisor", container_name="supervisor",
            args=["runner.py"], timeout_seconds=7200)

    def test_legacy_patch_reaches_service_dispatch_without_credentials(self):
        session = FakeSession()
        with mock.patch.object(cloud_run_jobs, "authorized_session", return_value=session):
            result = service_jobs.dispatch_cloud_run_job(project="ai-for-god", location="us-west1",
                job="sermon-production-supervisor", args=["runner.py"])
        self.assertEqual("dispatched", result["status"])
        self.assertEqual(1, len(session.calls))

    def test_dispatches_job_with_bounded_overrides(self):
        session = FakeSession()

        result = cloud_run_jobs.dispatch_cloud_run_job(
            project="ai-for-god",
            location="us-west1",
            job="sermon-production-supervisor",
            container_name="supervisor",
            args=["/app/scripts/run_sermon_production_supervisor_agent.py", "--mode", "shadow"],
            timeout_seconds=7200,
            session=session,
        )

        self.assertEqual(result["status"], "dispatched")
        self.assertEqual(result["operationName"], "operations/supervisor-run-1")
        call = session.calls[0]
        self.assertTrue(call["url"].endswith("/jobs/sermon-production-supervisor:run"))
        override = call["json"]["overrides"]
        self.assertEqual(override["taskCount"], 1)
        self.assertEqual(override["timeout"], "7200s")
        self.assertEqual(override["containerOverrides"][0]["name"], "supervisor")
        self.assertEqual(override["containerOverrides"][0]["args"][1:], ["--mode", "shadow"])

    def test_rejects_invalid_job_resource(self):
        with self.assertRaises(ValueError):
            cloud_run_jobs.dispatch_cloud_run_job(
                project="ai-for-god",
                location="us-west1",
                job="../other-job",
                args=["runner.py"],
                session=FakeSession(),
            )


if __name__ == "__main__":
    unittest.main()
