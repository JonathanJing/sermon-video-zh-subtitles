import unittest

from backend import cloud_run_jobs


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
