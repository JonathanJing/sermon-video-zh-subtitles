from __future__ import annotations

import argparse
import json
import os
import re
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from collections.abc import Callable
from typing import Any
from urllib.parse import parse_qs, urlparse

from .asr_client import AsrError, MlxAudioWebSocketClient, WhisperCliClient
from .content_pack import (
    CONTEXT_POLICIES,
    PackValidationError,
    alignment_summary,
    load_pack,
    prompt_context,
    retrieve,
)
from .firebase_publisher import FirebaseCaptionPublisher, FirebasePublisherConfig
from .ollama_client import OllamaClient, OllamaError
from .session_store import SessionStore, SessionStoreError
from .viewer_server import CaptionHub, ViewerService, viewer_urls


DEFAULT_OLLAMA_MODEL = "sermon-milmmt-46-4b-v1-q8:benchmark"
RUNTIME_RESTART_EXIT_CODE = 75


class GatewayState:
    def __init__(
        self,
        pack_path: str = "",
        ollama_model: str = "",
        ollama_url: str = "http://127.0.0.1:11434",
        session_root: str = "artifacts/sessions",
        asr_model: str = "",
        whisper_binary: str = "whisper-cli",
        vad_threshold_rms: int = 150,
        vad_silence_ms: int = 500,
        vad_max_segment_ms: int = 3000,
        ws_port: int = 8767,
        asr_provider: str = "whisper-cli",
        mlx_audio_url: str = "ws://127.0.0.1:18766/v1/audio/transcriptions/realtime",
        mlx_audio_model: str = "",
        viewer_port: int = 8780,
        default_context_policy: str = "none",
    ) -> None:
        self.pack_path = pack_path
        self.pack = load_pack(pack_path) if pack_path else None
        self.ollama = OllamaClient(ollama_model, ollama_url)
        self.sessions = SessionStore(session_root)
        if asr_provider == "qwen-mlx-websocket":
            self.asr = MlxAudioWebSocketClient(mlx_audio_model, mlx_audio_url)
        elif asr_provider == "whisper-cli":
            self.asr = WhisperCliClient(asr_model, whisper_binary)
        else:
            raise ValueError(f"unsupported ASR provider: {asr_provider}")
        self.vad_threshold_rms = vad_threshold_rms
        self.vad_silence_ms = vad_silence_ms
        self.vad_max_segment_ms = vad_max_segment_ms
        self.ws_port = ws_port
        self.viewer_port = viewer_port
        if default_context_policy not in CONTEXT_POLICIES:
            raise ValueError(f"unsupported default context policy: {default_context_policy}")
        self.default_context_policy = (
            default_context_policy if self.pack and default_context_policy != "none" else "none"
        )
        self.caption_hub = CaptionHub()
        firebase_config = FirebasePublisherConfig.from_environment()
        self.public_caption_publisher = (
            FirebaseCaptionPublisher(firebase_config) if firebase_config else None
        )
        self.asr_warmup: dict[str, Any] | None = None
        self.ollama_warmup: dict[str, Any] | None = None
        self.runtime_restart: Callable[[], None] = lambda: os._exit(RUNTIME_RESTART_EXIT_CODE)

    def translate(
        self,
        source_text: str,
        cursor_sequence: int | None,
        context_policy: str,
    ) -> dict[str, Any]:
        pack = self.pack
        hits = (
            retrieve(pack, source_text, limit=5, cursor_sequence=cursor_sequence)
            if pack and context_policy != "none" else []
        )
        context = prompt_context(hits, policy=context_policy)
        result = self.ollama.translate(source_text, context)
        return {
            "sourceTextEn": source_text,
            **result,
            "requestedContextPolicy": context_policy,
            "contextPolicy": context_policy if hits else "none",
            "contextHitIds": [hit["entryId"] for hit in hits],
            "alignment": alignment_summary(hits, cursor_sequence),
        }

    def translate_stream(
        self,
        source_text: str,
        cursor_sequence: int | None,
        context_policy: str,
        on_partial: Callable[[str, str], None],
    ) -> dict[str, Any]:
        pack = self.pack
        hits = (
            retrieve(pack, source_text, limit=5, cursor_sequence=cursor_sequence)
            if pack and context_policy != "none" else []
        )
        context = prompt_context(hits, policy=context_policy)
        result = self.ollama.translate(source_text, context, on_partial=on_partial)
        return {
            "sourceTextEn": source_text,
            **result,
            "requestedContextPolicy": context_policy,
            "contextPolicy": context_policy if hits else "none",
            "contextHitIds": [hit["entryId"] for hit in hits],
            "alignment": alignment_summary(hits, cursor_sequence),
        }


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

    def _raw_body(self, max_bytes: int = 10 * 1024 * 1024) -> bytes:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError as error:
            raise PackValidationError("invalid Content-Length") from error
        if length < 1 or length > max_bytes:
            raise PackValidationError(f"body must be between 1 and {max_bytes} bytes")
        return self.rfile.read(length)

    def do_OPTIONS(self) -> None:
        self.send_response(HTTPStatus.NO_CONTENT)
        self.send_header("Access-Control-Allow-Origin", self._origin())
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Vary", "Origin")
        self.end_headers()

    def do_GET(self) -> None:
        if urlparse(self.path).path != "/api/health":
            self._send(HTTPStatus.NOT_FOUND, {"error": "not_found"})
            return
        ollama = self.server.state.ollama.status()
        asr = self.server.state.asr.status()
        storage = self.server.state.sessions.health()
        pack = self.server.state.pack
        self._send(HTTPStatus.OK, {
            "service": "local-live-caption-gateway",
            "status": "ready" if (
                ollama.get("configuredModelInstalled")
                and asr.get("available")
                and storage.get("available")
            ) else "degraded",
            "contentPack": None if not pack else {
                "packVersion": pack["packVersion"],
                "serviceDate": pack["serviceDate"],
                "validUntil": pack["validUntil"],
                "entryCount": len(pack["entries"]),
            },
            "defaultContextPolicy": self.server.state.default_context_policy,
            "ollama": ollama,
            "ollamaWarmup": self.server.state.ollama_warmup,
            "asr": asr,
            "asrWarmup": self.server.state.asr_warmup,
            "liveStream": {
                "available": asr.get("available", False),
                "webSocketUrl": f"ws://127.0.0.1:{self.server.state.ws_port}/api/live",
                "format": "pcm_s16le/16000/mono/100ms",
                "asrFinalPolicy": {
                    "silenceMs": self.server.state.vad_silence_ms,
                    "maxSegmentMs": self.server.state.vad_max_segment_ms,
                },
                "translationStreaming": True,
            },
            "viewer": {
                "available": True,
                "port": self.server.state.viewer_port,
                "networkAddresses": viewer_urls("{session-token}", self.server.state.viewer_port),
                "readOnly": True,
            },
            "publicViewer": (
                self.server.state.public_caption_publisher.status()
                if self.server.state.public_caption_publisher
                else {"configured": False, "mode": "disabled"}
            ),
            "sessionStorage": storage,
        })

    def do_POST(self) -> None:
        try:
            parsed = urlparse(self.path)
            audio_match = re.fullmatch(r"/api/sessions/([^/]+)/audio", parsed.path)
            session_match = re.fullmatch(r"/api/sessions/([^/]+)/(events|finalize)", parsed.path)
            if audio_match:
                values = parse_qs(parsed.query).get("sequence", [])
                if len(values) != 1:
                    raise PackValidationError("audio sequence query parameter is required")
                try:
                    sequence = int(values[0])
                except ValueError as error:
                    raise PackValidationError("audio sequence must be an integer") from error
                result = self.server.state.sessions.append_audio(
                    audio_match.group(1), sequence, self._raw_body()
                )
                self._send(HTTPStatus.OK, result)
                return

            payload = self._body()
            if parsed.path == "/api/runtime/restart":
                if self.client_address[0] not in {"127.0.0.1", "::1"}:
                    self._send(HTTPStatus.FORBIDDEN, {"error": "local_only"})
                    return
                self._send(HTTPStatus.ACCEPTED, {"status": "restarting"})
                threading.Timer(0.1, self.server.state.runtime_restart).start()
            elif parsed.path == "/api/sessions/start":
                self._send(HTTPStatus.CREATED, self.server.state.sessions.create(payload))
            elif session_match and session_match.group(2) == "events":
                self._send(
                    HTTPStatus.OK,
                    self.server.state.sessions.append_event(
                        session_match.group(1), payload, assign_sequence=True
                    ),
                )
            elif session_match and session_match.group(2) == "finalize":
                self._send(
                    HTTPStatus.OK,
                    self.server.state.sessions.finalize(session_match.group(1), payload),
                )
            elif parsed.path == "/api/context/retrieve":
                self._retrieve(payload)
            elif parsed.path == "/api/translate":
                self._translate(payload)
            else:
                self._send(HTTPStatus.NOT_FOUND, {"error": "not_found"})
        except (PackValidationError, SessionStoreError) as error:
            self._send(HTTPStatus.BAD_REQUEST, {"error": "invalid_request", "message": str(error)})
        except OSError as error:
            self._send(HTTPStatus.INTERNAL_SERVER_ERROR, {
                "error": "session_storage_failed",
                "message": str(error),
                "recordingShouldContinue": True,
            })

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
        cursor_sequence = self._cursor_sequence(payload)
        context_policy = self._context_policy(payload)
        if payload.get("useContext") is False:
            context_policy = "none"
        try:
            result = self.server.state.translate(source_text, cursor_sequence, context_policy)
        except OllamaError as error:
            pack = self.server.state.pack
            hits = (
                retrieve(pack, source_text, limit=5, cursor_sequence=cursor_sequence)
                if pack and context_policy != "none" else []
            )
            alignment = alignment_summary(hits, cursor_sequence)
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
            **result,
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
    command.add_argument(
        "--ollama-model",
        default=os.environ.get("LOCAL_LIVE_OLLAMA_MODEL", DEFAULT_OLLAMA_MODEL),
    )
    command.add_argument("--ollama-url", default=os.environ.get("LOCAL_LIVE_OLLAMA_URL", "http://127.0.0.1:11434"))
    command.add_argument(
        "--session-root",
        default=os.environ.get("LOCAL_LIVE_SESSION_ROOT", "artifacts/sessions"),
    )
    command.add_argument(
        "--asr-model",
        default=os.environ.get("LOCAL_LIVE_ASR_MODEL", "artifacts/models/ggml-base.en.bin"),
    )
    command.add_argument(
        "--whisper-binary",
        default=os.environ.get("LOCAL_LIVE_WHISPER_BINARY", "whisper-cli"),
    )
    command.add_argument(
        "--asr-provider",
        choices=("whisper-cli", "qwen-mlx-websocket"),
        default=os.environ.get("LOCAL_LIVE_ASR_PROVIDER", "whisper-cli"),
    )
    command.add_argument(
        "--mlx-audio-url",
        default=os.environ.get(
            "LOCAL_LIVE_MLX_AUDIO_URL",
            "ws://127.0.0.1:18766/v1/audio/transcriptions/realtime",
        ),
    )
    command.add_argument(
        "--mlx-audio-model",
        default=os.environ.get("LOCAL_LIVE_QWEN_ASR_MODEL", ""),
    )
    command.add_argument(
        "--ws-port",
        type=int,
        default=int(os.environ.get("LOCAL_LIVE_WS_PORT", "8767")),
    )
    command.add_argument(
        "--viewer-port",
        type=int,
        default=int(os.environ.get("LOCAL_LIVE_VIEWER_PORT", "8780")),
    )
    command.add_argument(
        "--context-policy",
        choices=tuple(sorted(CONTEXT_POLICIES)),
        default=os.environ.get("LOCAL_LIVE_CONTEXT_POLICY", "none"),
    )
    command.add_argument(
        "--vad-threshold-rms",
        type=int,
        default=int(os.environ.get("LOCAL_LIVE_VAD_THRESHOLD_RMS", "150")),
    )
    command.add_argument(
        "--vad-silence-ms",
        type=int,
        default=int(os.environ.get("LOCAL_LIVE_VAD_SILENCE_MS", "500")),
    )
    command.add_argument(
        "--vad-max-segment-ms",
        type=int,
        default=int(os.environ.get("LOCAL_LIVE_VAD_MAX_SEGMENT_MS", "3000")),
    )
    return command


def main() -> None:
    arguments = parser().parse_args()
    if arguments.pack and not Path(arguments.pack).is_file():
        raise SystemExit(f"weekly pack not found: {arguments.pack}")
    state = GatewayState(
        arguments.pack,
        arguments.ollama_model,
        arguments.ollama_url,
        arguments.session_root,
        arguments.asr_model,
        arguments.whisper_binary,
        arguments.vad_threshold_rms,
        arguments.vad_silence_ms,
        arguments.vad_max_segment_ms,
        arguments.ws_port,
        arguments.asr_provider,
        arguments.mlx_audio_url,
        arguments.mlx_audio_model,
        arguments.viewer_port,
        arguments.context_policy,
    )
    server = create_server(arguments.host, arguments.port, state)
    try:
        from .live_server import LiveSocketService
    except ImportError as error:
        raise SystemExit("WebSocket dependency missing; run pip install -r requirements.txt") from error
    live_socket = LiveSocketService(state, arguments.host, arguments.ws_port)
    viewer = ViewerService(state.caption_hub, "0.0.0.0", arguments.viewer_port)
    storage_health = state.sessions.health(probe_write=True)
    recovered_sessions = state.sessions.recover_incomplete() if storage_health.get("available") else []
    try:
        state.ollama_warmup = state.ollama.warmup()
    except OllamaError as error:
        state.ollama_warmup = {"ready": False, "error": str(error)}
    try:
        state.asr_warmup = state.asr.warmup()
    except AsrError as error:
        state.asr_warmup = {"ready": False, "error": str(error)}
    live_socket.start()
    viewer.start()
    print(json.dumps({
        "gateway": f"http://{arguments.host}:{arguments.port}",
        "liveWebSocket": f"ws://{arguments.host}:{arguments.ws_port}/api/live",
        "viewer": viewer_urls("{session-token}", viewer.port),
        "packVersion": state.pack.get("packVersion") if state.pack else None,
        "ollamaModel": arguments.ollama_model or None,
        "asr": state.asr.status(),
        "sessionRoot": str(state.sessions.root),
        "sessionStorage": storage_health,
        "recoveredIncompleteSessions": [session["sessionId"] for session in recovered_sessions],
    }, ensure_ascii=False), flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        live_socket.stop()
        viewer.stop()
        if state.public_caption_publisher:
            state.public_caption_publisher.stop()
        server.server_close()


if __name__ == "__main__":
    main()
