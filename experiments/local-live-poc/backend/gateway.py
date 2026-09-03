from __future__ import annotations

import argparse
import json
import os
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from .content_pack import (
    CONTEXT_POLICIES,
    PackValidationError,
    alignment_summary,
    load_pack,
    prompt_context,
    retrieve,
)
from .ollama_client import OllamaClient, OllamaError


class GatewayState:
    def __init__(self, pack_path: str = "", ollama_model: str = "", ollama_url: str = "http://127.0.0.1:11434") -> None:
        self.pack_path = pack_path
        self.pack = load_pack(pack_path) if pack_path else None
        self.ollama = OllamaClient(ollama_model, ollama_url)


class GatewayServer(ThreadingHTTPServer):
    state: GatewayState


class Handler(BaseHTTPRequestHandler):
    server: GatewayServer

    def log_message(self, format: str, *args: object) -> None:
        return

    def _origin(self) -> str:
        requested = self.headers.get("Origin", "")
        allowed = {
            "http://127.0.0.1:4173",
            "http://localhost:4173",
        }
        return requested if requested in allowed else "http://127.0.0.1:4173"

    def _send(self, status: HTTPStatus, payload: dict[str, Any]) -> None:
        body = (json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", self._origin())
        self.send_header("Vary", "Origin")
        self.end_headers()
        self.wfile.write(body)

    def _body(self) -> dict[str, Any]:
        try:
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length) or b"{}")
        except (ValueError, json.JSONDecodeError) as error:
            raise PackValidationError(f"invalid JSON body: {error}") from error
        if not isinstance(payload, dict):
            raise PackValidationError("request body must be a JSON object")
        return payload

    def do_OPTIONS(self) -> None:
        self.send_response(HTTPStatus.NO_CONTENT)
        self.send_header("Access-Control-Allow-Origin", self._origin())
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Vary", "Origin")
        self.end_headers()

    def do_GET(self) -> None:
        if self.path != "/api/health":
            self._send(HTTPStatus.NOT_FOUND, {"error": "not_found"})
            return
        ollama = self.server.state.ollama.status()
        pack = self.server.state.pack
        self._send(HTTPStatus.OK, {
            "service": "local-live-caption-gateway",
            "status": "ready" if pack and ollama.get("configuredModelInstalled") else "degraded",
            "contentPack": None if not pack else {
                "packVersion": pack["packVersion"],
                "serviceDate": pack["serviceDate"],
                "validUntil": pack["validUntil"],
                "entryCount": len(pack["entries"]),
            },
            "ollama": ollama,
        })

    def do_POST(self) -> None:
        try:
            payload = self._body()
            if self.path == "/api/context/retrieve":
                self._retrieve(payload)
            elif self.path == "/api/translate":
                self._translate(payload)
            else:
                self._send(HTTPStatus.NOT_FOUND, {"error": "not_found"})
        except PackValidationError as error:
            self._send(HTTPStatus.BAD_REQUEST, {"error": "invalid_request", "message": str(error)})

    def _retrieve(self, payload: dict[str, Any]) -> None:
        source_text = str(payload.get("sourceTextEn") or "").strip()
        if not source_text:
            raise PackValidationError("sourceTextEn is required")
        try:
            limit = int(payload.get("limit", 5))
        except (TypeError, ValueError) as error:
            raise PackValidationError("limit must be an integer from 1 to 8") from error
        if not 1 <= limit <= 8:
            raise PackValidationError("limit must be an integer from 1 to 8")
        cursor_sequence = self._cursor_sequence(payload)
        context_policy = self._context_policy(payload)
        pack = self.server.state.pack
        hits = (
            retrieve(pack, source_text, limit=limit, cursor_sequence=cursor_sequence)
            if pack and context_policy != "none" else []
        )
        self._send(HTTPStatus.OK, {
            "sourceTextEn": source_text,
            "packVersion": pack.get("packVersion") if pack else None,
            "contextPolicy": context_policy,
            "hits": hits,
            "promptContext": prompt_context(hits, policy=context_policy),
            "alignment": alignment_summary(hits, cursor_sequence),
            "fallback": "no_context" if not hits else None,
        })

    def _translate(self, payload: dict[str, Any]) -> None:
        source_text = str(payload.get("sourceTextEn") or "").strip()
        if not source_text:
            raise PackValidationError("sourceTextEn is required")
        pack = self.server.state.pack
        cursor_sequence = self._cursor_sequence(payload)
        context_policy = self._context_policy(payload)
        if payload.get("useContext") is False:
            context_policy = "none"
        hits = (
            retrieve(pack, source_text, limit=5, cursor_sequence=cursor_sequence)
            if pack and context_policy != "none" else []
        )
        context = prompt_context(hits, policy=context_policy)
        alignment = alignment_summary(hits, cursor_sequence)
        try:
            result = self.server.state.ollama.translate(source_text, context)
        except OllamaError as error:
            self._send(HTTPStatus.SERVICE_UNAVAILABLE, {
                "error": "translation_unavailable",
                "message": str(error),
                "recordingShouldContinue": True,
                "fallback": "show_english_only",
                "requestedContextPolicy": context_policy,
                "contextPolicy": context_policy if hits else "none",
                "contextHitIds": [hit["entryId"] for hit in hits],
                "alignment": alignment,
            })
            return
        self._send(HTTPStatus.OK, {
            "sourceTextEn": source_text,
            **result,
            "requestedContextPolicy": context_policy,
            "contextPolicy": context_policy if hits else "none",
            "contextHitIds": [hit["entryId"] for hit in hits],
            "alignment": alignment,
        })

    @staticmethod
    def _cursor_sequence(payload: dict[str, Any]) -> int | None:
        value = payload.get("cursorSequence")
        if value is None:
            return None
        try:
            cursor_sequence = int(value)
        except (TypeError, ValueError) as error:
            raise PackValidationError("cursorSequence must be a positive integer") from error
        if cursor_sequence < 1:
            raise PackValidationError("cursorSequence must be a positive integer")
        return cursor_sequence

    @staticmethod
    def _context_policy(payload: dict[str, Any]) -> str:
        value = str(payload.get("contextPolicy") or "saturday_alignment_v1")
        if value not in CONTEXT_POLICIES:
            raise PackValidationError(
                "contextPolicy must be none, weekly_terms_v1, or saturday_alignment_v1"
            )
        return value


def create_server(host: str, port: int, state: GatewayState) -> GatewayServer:
    server = GatewayServer((host, port), Handler)
    server.state = state
    return server


def parser() -> argparse.ArgumentParser:
    command = argparse.ArgumentParser(description="Run the local live caption gateway.")
    command.add_argument("--host", default="127.0.0.1")
    command.add_argument("--port", type=int, default=8766)
    command.add_argument("--pack", default=os.environ.get("LOCAL_LIVE_WEEKLY_PACK", ""))
    command.add_argument("--ollama-model", default=os.environ.get("LOCAL_LIVE_OLLAMA_MODEL", ""))
    command.add_argument("--ollama-url", default=os.environ.get("LOCAL_LIVE_OLLAMA_URL", "http://127.0.0.1:11434"))
    return command


def main() -> None:
    arguments = parser().parse_args()
    if arguments.pack and not Path(arguments.pack).is_file():
        raise SystemExit(f"weekly pack not found: {arguments.pack}")
    state = GatewayState(arguments.pack, arguments.ollama_model, arguments.ollama_url)
    server = create_server(arguments.host, arguments.port, state)
    print(json.dumps({
        "gateway": f"http://{arguments.host}:{arguments.port}",
        "packVersion": state.pack.get("packVersion") if state.pack else None,
        "ollamaModel": arguments.ollama_model or None,
    }, ensure_ascii=False), flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
