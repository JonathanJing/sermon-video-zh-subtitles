from __future__ import annotations

import json
import struct
import threading
from typing import Any

from websockets.exceptions import ConnectionClosed
from websockets.sync.server import ServerConnection, serve

from .content_pack import CONTEXT_POLICIES
from .live_pipeline import LivePipeline, PCM_BYTES_PER_FRAME
from .session_store import SessionStoreError


class LiveSocketService:
    def __init__(self, state: Any, host: str = "127.0.0.1", port: int = 8767) -> None:
        self.state = state
        self.host = host
        self.port = port
        self.server = serve(
            self._handle,
            host,
            port,
            origins=["http://127.0.0.1:4173", "http://localhost:4173", None],
            compression=None,
            max_size=PCM_BYTES_PER_FRAME + 4,
            max_queue=32,
        )
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def start(self) -> None:
        self.thread.start()

    def stop(self) -> None:
        self.server.shutdown()
        self.thread.join(timeout=5)

    def _handle(self, connection: ServerConnection) -> None:
        pipeline: LivePipeline | None = None
        send_lock = threading.Lock()

        def send(payload: dict[str, Any]) -> None:
            with send_lock:
                connection.send(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))

        try:
            request_path = connection.request.path.split("?", 1)[0]
            if request_path != "/api/live":
                send({"type": "stream.error", "message": "unknown WebSocket path"})
                return
            first = connection.recv(timeout=8)
            if not isinstance(first, str):
                send({"type": "stream.error", "message": "stream.start JSON is required"})
                return
            try:
                start = json.loads(first)
            except json.JSONDecodeError:
                send({"type": "stream.error", "message": "invalid stream.start JSON"})
                return
            if start.get("type") != "stream.start":
                send({"type": "stream.error", "message": "first message must be stream.start"})
                return
            session_id = str(start.get("sessionId") or "")
            try:
                self.state.sessions.get_recording(session_id)
            except SessionStoreError as error:
                send({"type": "stream.error", "message": str(error)})
                return
            if (
                start.get("encoding") != "pcm_s16le"
                or int(start.get("sampleRateHz") or 0) != 16000
                or int(start.get("channels") or 0) != 1
                or int(start.get("frameDurationMs") or 0) != 100
            ):
                send({"type": "stream.error", "message": "unsupported PCM stream format"})
                return
            context_policy = str(start.get("contextPolicy") or "none")
            if context_policy not in CONTEXT_POLICIES:
                send({"type": "stream.error", "message": "unsupported context policy"})
                return
            pipeline = LivePipeline(
                session_id=session_id,
                sessions=self.state.sessions,
                asr=self.state.asr,
                translate=self.state.translate,
                send=send,
                context_policy=context_policy,
                vad_threshold_rms=self.state.vad_threshold_rms,
            )
            pipeline.start()
            for message in connection:
                if isinstance(message, bytes):
                    if len(message) != PCM_BYTES_PER_FRAME + 4:
                        send({"type": "audio.frame_rejected", "reason": "invalid_wire_size"})
                        continue
                    sequence = struct.unpack(">I", message[:4])[0]
                    pipeline.process_frame(sequence, message[4:])
                    continue
                try:
                    control = json.loads(message)
                except json.JSONDecodeError:
                    send({"type": "stream.error", "message": "invalid control JSON"})
                    continue
                if control.get("type") == "stream.stop":
                    break
        except (ConnectionClosed, TimeoutError):
            pass
        finally:
            if pipeline:
                pipeline.stop()
