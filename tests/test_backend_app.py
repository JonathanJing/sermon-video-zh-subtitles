import unittest
from pathlib import Path

from backend.app import ApiHandler, WEB_ROOT


class BackendAppTest(unittest.TestCase):
    def test_static_root_serves_web_index(self):
        self.assertEqual(ApiHandler.static_path_for(ApiHandler, "/"), WEB_ROOT / "index.html")

    def test_static_pwa_route_falls_back_to_index(self):
        self.assertEqual(
            ApiHandler.static_path_for(ApiHandler, "/sundays/2026-06-21"),
            WEB_ROOT / "index.html",
        )

    def test_static_path_rejects_escape(self):
        with self.assertRaises(FileNotFoundError):
            ApiHandler.static_path_for(ApiHandler, "/../README.md")

    def test_dockerfile_starts_backend_app(self):
        dockerfile = Path(__file__).resolve().parents[1] / "Dockerfile"
        text = dockerfile.read_text(encoding="utf-8")
        self.assertIn("COPY backend/", text)
        self.assertIn('CMD ["python", "-m", "backend.app"]', text)


if __name__ == "__main__":
    unittest.main()
