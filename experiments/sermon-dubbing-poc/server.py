#!/usr/bin/env python3
"""Loopback-only player server; expose explicit assets, never the repository tree."""
from __future__ import annotations

import argparse
from functools import partial
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import re
from urllib.parse import urlsplit

HERE = Path(__file__).resolve().parent
DEFAULT_PACK = HERE.parents[1] / "artifacts/sermon-dubbing/2026-09-05-weekly-app-v4-dark-final/public"
STATIC = {"/theme.js": ("theme.js", "text/javascript"), "/": ("index.html", "text/html; charset=utf-8"), "/app.mjs": ("app.mjs", "text/javascript"), "/catalog.mjs": ("catalog.mjs", "text/javascript"), "/timing.mjs": ("timing.mjs", "text/javascript"), "/style.css": ("style.css", "text/css")}


def byte_range(value: str | None, size: int) -> tuple[int, int]:
    if not value:
        return 0, size - 1
    match = re.fullmatch(r"bytes=(\d*)-(\d*)", value)
    if not match or size <= 0:
        raise ValueError("Invalid range")
    left, right = match.groups()
    if not left:
        if not right or int(right) <= 0:
            raise ValueError("Invalid suffix")
        return max(0, size - int(right)), size - 1
    start = int(left)
    end = min(int(right), size - 1) if right else size - 1
    if start >= size or start > end:
        raise ValueError("Unsatisfiable range")
    return start, end


def load_library(pack: Path) -> dict:
    library = json.loads((pack / "library.json").read_text())
    if library.get("schemaVersion") != "sermon-audio-library-v1" or not library.get("tracks"):
        raise ValueError("Invalid audio library")
    identifiers = set()
    for track in library["tracks"]:
        name = track["file"]
        path = (pack / name).resolve()
        if path.parent != pack.resolve() or path.suffix != ".mp3" or not path.is_file():
            raise ValueError("Missing or unsafe media path")
        if track["id"] in identifiers:
            raise ValueError("Duplicate track ID")
        identifiers.add(track["id"])
        if track["audioUrl"] != f"/media/{name}" or track["durationSeconds"] <= 0:
            raise ValueError("Invalid track contract")
    return library


def load_weekly(pack: Path) -> dict:
    from build_weekly_app import validate_catalog
    catalog = json.loads((pack / "weekly.json").read_text())
    validate_catalog(catalog)
    for tracks in [w["tracks"] for w in catalog["weeks"]] + [[s["reference"], s["chinese"]] for s in catalog.get("voiceBank", {}).get("speakers", [])]:
        for track in tracks:
            path = (pack / "media" / track["file"]).resolve()
            if path.parent != (pack / "media").resolve() or not path.is_file():
                raise ValueError("Missing or unsafe weekly media")
    return catalog


class Handler(BaseHTTPRequestHandler):
    def __init__(self, *args, pack: Path, **kwargs):
        self.pack = pack.resolve()
        super().__init__(*args, **kwargs)

    def do_HEAD(self):
        self.respond(head=True)

    def do_GET(self):
        self.respond(head=False)

    def respond(self, head: bool):
        route = urlsplit(self.path).path
        weekly = (self.pack / "weekly.json").is_file()
        if route in STATIC:
            filename, mime = STATIC[route]
            static_root = self.pack if weekly else HERE / "web"
            self.send_data((static_root / filename).read_bytes(), mime, head)
            return
        try:
            library = load_weekly(self.pack) if weekly else load_library(self.pack)
        except (OSError, ValueError, KeyError):
            self.send_error(503, "Audio pack is not ready")
            return
        if route == ("/weekly.json" if weekly else "/library.json"):
            self.send_data(json.dumps(library, ensure_ascii=False).encode(), "application/json; charset=utf-8", head)
            return
        tracks = [t for w in library["weeks"] for t in w["tracks"]] if weekly else library["tracks"]
        if weekly:
            tracks += [s[key] for s in library.get("voiceBank", {}).get("speakers", []) for key in ["reference", "chinese"]]
        track = next((t for t in tracks if route == t["audioUrl"]), None)
        if not track:
            self.send_error(404)
            return
        path = (self.pack / "media" if weekly else self.pack) / track["file"]
        size = path.stat().st_size
        requested = self.headers.get("Range")
        try:
            start, end = byte_range(requested, size)
        except ValueError:
            self.send_response(416)
            self.send_header("Content-Range", f"bytes */{size}")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        self.send_response(206 if requested else 200)
        self.send_header("Content-Type", "audio/mpeg")
        self.send_header("Content-Length", str(end - start + 1))
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Cache-Control", "no-cache")
        if requested:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        if urlsplit(self.path).query == "download=1":
            self.send_header("Content-Disposition", f'attachment; filename="{path.name}"')
        self.end_headers()
        if not head:
            try:
                with path.open("rb") as stream:
                    stream.seek(start)
                    remaining = end - start + 1
                    while remaining:
                        chunk = stream.read(min(65536, remaining))
                        if not chunk:
                            break
                        self.wfile.write(chunk)
                        remaining -= len(chunk)
            except (BrokenPipeError, ConnectionResetError):
                pass  # Normal when the user seeks or switches a track.

    def send_data(self, data: bytes, mime: str, head: bool):
        self.send_response(200)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        if not head:
            self.wfile.write(data)


def make_server(pack: Path, port: int = 18780):
    load_weekly(pack) if (pack / "weekly.json").is_file() else load_library(pack)
    return ThreadingHTTPServer(("127.0.0.1", port), partial(Handler, pack=pack))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--pack", type=Path, default=DEFAULT_PACK)
    parser.add_argument("--port", type=int, default=18780)
    args = parser.parse_args()
    server = make_server(args.pack, args.port)
    print(f"Chinese audio player: http://127.0.0.1:{server.server_port}", flush=True)
    server.serve_forever()
