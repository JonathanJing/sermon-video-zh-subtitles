import unittest
from pathlib import Path

from backend.app import ApiHandler, WEB_ROOT
from backend.config import AppConfig


class BackendAppTest(unittest.TestCase):
    def test_static_root_serves_web_index(self):
        self.assertEqual(ApiHandler.static_path_for(ApiHandler, "/"), WEB_ROOT / "index.html")

    def test_static_pwa_route_falls_back_to_index(self):
        self.assertEqual(
            ApiHandler.static_path_for(ApiHandler, "/sundays/2026-06-21"),
            WEB_ROOT / "index.html",
        )

    def test_static_admin_route_serves_admin_page(self):
        self.assertEqual(ApiHandler.static_path_for(ApiHandler, "/admin"), WEB_ROOT / "admin.html")
        self.assertEqual(ApiHandler.static_path_for(ApiHandler, "/admin/"), WEB_ROOT / "admin.html")

    def test_static_path_rejects_escape(self):
        with self.assertRaises(FileNotFoundError):
            ApiHandler.static_path_for(ApiHandler, "/../README.md")

    def test_admin_status_sanitizes_secret_resource_names(self):
        test_case = self

        class FakeService:
            def _resolve_sunday(self, sunday):
                test_case.assertEqual(sunday, "current")
                return "2026-06-28"

            def get_public_slice(self, sunday):
                test_case.assertEqual(sunday, "current")
                return {
                    "status": "ready",
                    "artifactCount": 2,
                    "sermonTitle": "Test Sermon",
                    "translationStatus": "ready",
                }

        handler = object.__new__(ApiHandler)
        handler.config = AppConfig(
            artifact_bucket="sermon-zh-artifacts-ai-for-god",
            artifact_prefix="sundays",
            current_manifest_uri=None,
            sunday_manifest_uri_template=None,
            timezone="America/Los_Angeles",
            openai_api_key_secret="projects/123/secrets/openai-api-key/versions/latest",
            operator_admin_token="secret-token",
            internal_task_token=None,
            enable_inline_worker=False,
        )
        handler.service = FakeService()
        status = ApiHandler.admin_status(handler)
        text = str(status)
        self.assertEqual(status["secrets"]["openaiApiKey"], "configured")
        self.assertEqual(status["secrets"]["operatorAdminToken"], "configured")
        self.assertNotIn("projects/123/secrets", text)
        self.assertNotIn("secret-token", text)

    def test_dockerfile_starts_backend_app(self):
        dockerfile = Path(__file__).resolve().parents[1] / "Dockerfile"
        text = dockerfile.read_text(encoding="utf-8")
        self.assertIn("COPY backend/", text)
        self.assertIn('CMD ["python", "-m", "backend.app"]', text)


if __name__ == "__main__":
    unittest.main()
