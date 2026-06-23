from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

from .config import AppConfig
from .manifest import SundaySliceService
from .storage import GcsArtifactReader
from .worker import build_generation_command, parse_generation_request


class ApiHandler(BaseHTTPRequestHandler):
    config = AppConfig.from_env()
    service = SundaySliceService(config, GcsArtifactReader())

    def do_GET(self) -> None:
        try:
            path = urlparse(self.path).path
            if path == "/api/health":
                self.write_json({"status": "ok"})
                return
            parts = [part for part in path.split("/") if part]
            if parts[:2] == ["api", "sundays"] and len(parts) == 3:
                self.write_json(self.service.get_public_slice(parts[2]))
                return
            if parts[:2] == ["api", "sundays"] and len(parts) == 5 and parts[3] == "artifacts":
                body, content_type = self.service.read_public_artifact(parts[2], parts[4])
                self.send_response(200)
                self.send_header("Content-Type", content_type)
                self.send_header("Cache-Control", "public, max-age=30")
                self.end_headers()
                self.wfile.write(body)
                return
            self.write_json({"error": "not_found"}, status=404)
        except KeyError:
            self.write_json({"error": "artifact_not_found"}, status=404)
        except Exception as exc:
            self.write_json({"error": str(exc)}, status=400)

    def do_POST(self) -> None:
        try:
            path = urlparse(self.path).path
            parts = [part for part in path.split("/") if part]
            if parts[:3] == ["api", "admin", "sundays"] and len(parts) == 5 and parts[4] == "generate":
                if not self.authorized():
                    self.write_json({"error": "unauthorized"}, status=401)
                    return
                payload = self.read_json_body()
                request = parse_generation_request(payload, parts[3])
                command = build_generation_command(request, self.config)
                if not self.config.enable_inline_worker:
                    self.write_json(
                        {
                            "status": "planned",
                            "message": "Inline worker disabled; run the returned command from a Cloud Run Job or enable ENABLE_INLINE_WORKER=1.",
                            "command": command,
                        },
                        status=202,
                    )
                    return
                import subprocess

                completed = subprocess.run(command, check=True, capture_output=True, text=True)
                self.write_json(
                    {
                        "status": "completed",
                        "stdout": completed.stdout,
                        "stderr": completed.stderr,
                    },
                    status=201,
                )
                return
            self.write_json({"error": "not_found"}, status=404)
        except Exception as exc:
            self.write_json({"error": str(exc)}, status=400)

    def authorized(self) -> bool:
        auth_header = self.headers.get("Authorization", "")
        if self.config.operator_admin_token and auth_header == f"Bearer {self.config.operator_admin_token}":
            return True
        task_token = self.headers.get("X-Internal-Task-Token", "")
        if self.config.internal_task_token and task_token == self.config.internal_task_token:
            return True
        return False

    def read_json_body(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        if length == 0:
            return {}
        return json.loads(self.rfile.read(length).decode("utf-8"))

    def write_json(self, payload: dict, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main() -> None:
    import os

    port = int(os.getenv("PORT", "8080"))
    server = ThreadingHTTPServer(("0.0.0.0", port), ApiHandler)
    server.serve_forever()


if __name__ == "__main__":
    main()

