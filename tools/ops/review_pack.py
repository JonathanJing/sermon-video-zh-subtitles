#!/usr/bin/env python3
"""Build a static review pack from a sentence-first run directory.

    python3 tools/ops/review_pack.py build \
        --run artifacts/sentence-first-agent/20261108-jesus-is-just-zh \
        --locale zh-Hans --checkpoint audio --out artifacts/review-pack/20261108-zh

The pack is a plain directory that any static host can serve (an Aliyun OSS
Hong Kong bucket, a plain `python3 -m http.server`, or Firebase Hosting):

    index.html app.js styles.css   copied from apps/review-web/
    pack.json                     sentence-first-review-pack-v1
    audio/review.mp3              the reviewer's mixed track (audio checkpoint only)
    audio/clip-<id>.mp3           only the flagged sentences, cut from tts/<id>.wav

Why a static pack: the reviewer sits behind a network where the production
machine cannot be reached. A pack can be opened without an API, without a
session, and without the run directory ever leaving the producer.

Nothing here writes into the run directory, and nothing leaves the machine
until someone uploads the directory. `--checkpoint text` omits every audio
file so a text review survives an unusable network.

The page reports the verdict as one short command line to paste back into the
review channel (see docs/design/unattended-cross-pacific-production.zh.md
§6.5). It never posts anything by itself.
"""
from __future__ import annotations

import argparse
import base64
import configparser
import hashlib
import hmac
import json
from email.utils import formatdate
from pathlib import Path
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request

SCHEMA = "sentence-first-review-pack-v1"
DEFAULT_ENDPOINT = "oss-cn-hongkong.aliyuncs.com"
CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".mp3": "audio/mpeg",
    ".wav": "audio/wav",
    ".png": "image/png",
    ".svg": "image/svg+xml",
}
APP_DIR = Path(__file__).resolve().parents[2] / "apps" / "review-web"
REPO_ROOT = Path(__file__).resolve().parents[2]
LAG_FLAG_SECONDS = 0.8
MAX_CLIPS_DEFAULT = 120
CLIP_BITRATE = "48k"
CLIP_SAMPLE_RATE = "24000"


def read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            rows.append(json.loads(line))
    return rows


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def short_code(seed: str) -> str:
    """Four unambiguous characters; the reviewer types this in the chat."""
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    value = int(hashlib.sha256(seed.encode("utf-8")).hexdigest()[:12], 16)
    return "".join(alphabet[value >> (5 * i) & 0x1F] for i in range(4))


def quiet_note(note: str) -> bool:
    return note == "pass" or str(note or "").startswith("reused")


def flags_for(sentence: dict, translated: dict, spoken: dict, scheduled: dict,
              notes: dict, doubt: dict) -> list[str]:
    flags = []
    note = str(translated.get("reviewNote") or "pass")
    if not quiet_note(note):
        flags.append("revised")
    if notes.get(sentence["id"]):
        flags.append("note")
    if sentence.get("speakerReview") == "check":
        flags.append("speaker")
    spoken_text = str(spoken.get("spokenText") or "")
    target = str(translated.get("target") or "")
    if spoken_text and target and spoken_text.strip() != target.strip():
        flags.append("spoken")
    if re.search(r"\d", spoken_text):
        flags.append("digits")
    lag = float(scheduled.get("lagSeconds") or 0.0)
    if lag > LAG_FLAG_SECONDS:
        flags.append("lag")
    if doubt.get(sentence["id"]):
        flags.append("doubt")
    return flags


def make_clip(source: Path, target: Path) -> bool:
    """Transcode one sentence to a small mp3; returns False when it cannot be read."""
    if target.exists() and target.stat().st_mtime >= source.stat().st_mtime:
        return True
    target.parent.mkdir(parents=True, exist_ok=True)
    command = ["ffmpeg", "-v", "error", "-y", "-i", str(source), "-ac", "1",
               "-ar", CLIP_SAMPLE_RATE, "-b:a", CLIP_BITRATE, str(target)]
    try:
        result = subprocess.run(command, capture_output=True, text=True, check=False)
    except FileNotFoundError:
        return False
    if result.returncode != 0:
        target.unlink(missing_ok=True)
        return False
    return True


def build(args: argparse.Namespace) -> dict:
    run = Path(args.run).resolve()
    if not (run / "sentences.jsonl").exists():
        raise SystemExit(f"{run}: sentences.jsonl not found; not a sentence-first run directory")

    sentences = read_jsonl(run / "sentences.jsonl")
    translations = {row["id"]: row for row in read_jsonl(run / "translations.jsonl")}
    speech = {row["id"]: row for row in read_jsonl(run / "speech.jsonl")}
    schedule_rows = (json.loads((run / "schedule.json").read_text(encoding="utf-8"))["sentences"]
                     if (run / "schedule.json").exists() else [])
    scheduled = {row["id"]: row for row in schedule_rows}
    review = (json.loads((run / "review.json").read_text(encoding="utf-8"))
              if (run / "review.json").exists() else {})
    notes = review.get("notes") or {}
    doubt = {}
    decisions = (json.loads((run / "decisions.json").read_text(encoding="utf-8"))
                 if (run / "decisions.json").exists() else {})
    clip = (json.loads((run / "clip.json").read_text(encoding="utf-8"))
            if (run / "clip.json").exists() else {})

    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    (out / "audio").mkdir(exist_ok=True)

    rows = []
    for index, sentence in enumerate(sentences, start=1):
        sid = sentence["id"]
        translated = translations.get(sid, {})
        spoken = speech.get(sid, {})
        sched = scheduled.get(sid, {})
        flags = flags_for(sentence, translated, spoken, sched, notes, doubt)
        rows.append({
            "id": sid,
            "index": index,
            "sourceUnitId": sentence.get("sourceUnitId"),
            "speaker": sentence.get("speakerId") or spoken.get("speaker"),
            "start": round(float(sentence.get("start") or 0.0), 3),
            "end": round(float(sentence.get("end") or 0.0), 3),
            "dubStart": round(float(sched.get("actualStart") or 0.0), 3),
            "dubSeconds": round(float(sched.get("dubSeconds") or 0.0), 3),
            "lag": round(float(sched.get("lagSeconds") or 0.0), 3),
            "english": sentence.get("english") or "",
            "target": translated.get("target") or "",
            "spoken": spoken.get("spokenText") or "",
            "note": translated.get("reviewNote") if not quiet_note(translated.get("reviewNote") or "") else "",
            "flags": flags,
            "clip": None,
        })

    flagged = [row for row in rows if row["flags"]]
    production_id = (args.production_id or decisions.get("productionId")
                     or f"{run.name}-{args.locale}")
    code = args.code or short_code(f"{production_id}|{args.locale}")

    track = None
    if args.checkpoint == "audio":
        source_mp3 = run / "review.mp3"
        if not source_mp3.exists():
            raise SystemExit(f"{source_mp3}: audio checkpoint needs review.mp3 (run finish_run.py first)")
        shutil.copyfile(source_mp3, out / "audio" / "review.mp3")
        track = {
            "url": "audio/review.mp3",
            "sha256": sha256_file(out / "audio" / "review.mp3"),
            "bytes": (out / "audio" / "review.mp3").stat().st_size,
            "seconds": round(float(schedule_rows[-1]["actualStart"]), 3) if schedule_rows else None,
        }

    clipped = 0
    if args.checkpoint == "audio" and args.clips:
        for row in flagged[: args.clips]:
            source = run / "tts" / f"{row['id']}.wav"
            if not source.exists():
                continue
            target = out / "audio" / f"clip-{row['id']}.mp3"
            if make_clip(source, target):
                row["clip"] = f"audio/{target.name}"
                clipped += 1

    pack = {
        "schemaVersion": SCHEMA,
        "productionId": production_id,
        "runId": run.name,
        "locale": args.locale,
        "checkpoint": args.checkpoint,
        "title": args.title or decisions.get("title") or run.name,
        "code": code,
        "builtAt": args.built_at,
        "source": {
            "media": Path(clip["media"]).name if clip.get("media") else None,
            "windowStart": clip.get("windowStart"),
            "clipSeconds": decisions.get("clipSeconds"),
            "sync": decisions.get("sync"),
        },
        "counts": {"sentences": len(rows), "flagged": len(flagged), "clips": clipped},
        "track": track,
        "sentences": rows,
    }

    for name in ("index.html", "app.js", "styles.css"):
        source = APP_DIR / name
        if not source.exists():
            raise SystemExit(f"{source}: review web app asset missing")
        shutil.copyfile(source, out / name)

    (out / "pack.json").write_text(
        json.dumps(pack, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8")
    return pack


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)

    build_parser = sub.add_parser("build", help="write a static review pack directory")
    build_parser.add_argument("--run", required=True, help="sentence-first run directory")
    build_parser.add_argument("--locale", required=True)
    build_parser.add_argument("--out", required=True, help="output directory (ignored path)")
    build_parser.add_argument("--checkpoint", choices=("text", "audio"), default="audio")
    build_parser.add_argument("--title")
    build_parser.add_argument("--production-id")
    build_parser.add_argument("--code", help="override the four-character review code")
    build_parser.add_argument("--clips", type=int, default=MAX_CLIPS_DEFAULT,
                              help=f"per-sentence clips for flagged rows (default {MAX_CLIPS_DEFAULT}, 0 disables)")
    build_parser.add_argument("--built-at", default=None, help="ISO timestamp; defaults to now")
    build_parser.set_defaults(func=build)

    publish_parser = sub.add_parser("publish", help="upload a pack to an Alibaba OSS bucket (dry run by default)")
    publish_parser.add_argument("--pack", required=True)
    publish_parser.add_argument("--bucket", required=True)
    publish_parser.add_argument("--prefix", required=True, help="key prefix, e.g. review/<32 hex>")
    publish_parser.add_argument("--endpoint", default=DEFAULT_ENDPOINT)
    publish_parser.add_argument("--config", type=Path, help="ossutil-style config (default ~/.ossutilconfig)")
    publish_parser.add_argument("--execute", action="store_true", help="really upload; default prints the plan")
    publish_parser.add_argument("--show", type=int, default=5)
    publish_parser.set_defaults(func=publish)

    remove_parser = sub.add_parser("remove", help="delete a whole uploaded pack (dry run by default)")
    remove_parser.add_argument("--pack", required=True)
    remove_parser.add_argument("--bucket", required=True)
    remove_parser.add_argument("--prefix", required=True)
    remove_parser.add_argument("--endpoint", default=DEFAULT_ENDPOINT)
    remove_parser.add_argument("--config", type=Path)
    remove_parser.add_argument("--execute", action="store_true")
    remove_parser.add_argument("--show", type=int, default=5)
    remove_parser.set_defaults(func=remove)

    args = parser.parse_args(argv)
    if getattr(args, "built_at", None) is None and args.func is build:
        import datetime as dt
        args.built_at = dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()
    result = args.func(args)
    if args.func is build:
        result = {
            "ok": True,
            "out": str(Path(args.out).resolve()),
            "productionId": result["productionId"],
            "code": result["code"],
            "checkpoint": result["checkpoint"],
            "counts": result["counts"],
            "trackBytes": result["track"]["bytes"] if result["track"] else 0,
        }
    print(json.dumps(result, ensure_ascii=False))
    return 0



# ---------------------------------------------------------------- OSS publishing
#
# Alibaba OSS has no Homebrew formula and the account may not have ossutil, so the
# upload speaks the OSS REST API directly with the V1 signature. That keeps the
# pack publisher dependency-free and makes `--dry-run` honest: the same code path
# builds the plan whether or not it is executed.
#
# Credentials come from the environment first, then from the ossutil config file so
# one file serves both this tool and a future `ossutil` install:
#
#   ~/.ossutilconfig        [Credentials]
#                           endpoint=oss-cn-hongkong.aliyuncs.com
#                           accessKeyID=...
#                           accessKeySecret=...


class Credentials:
    def __init__(self, key_id: str, key_secret: str, endpoint: str = DEFAULT_ENDPOINT):
        self.key_id = key_id
        self.key_secret = key_secret
        self.endpoint = endpoint

    def __repr__(self) -> str:  # never print the secret
        return f"Credentials(key_id={self.key_id[:4]}…, endpoint={self.endpoint})"


def load_credentials(path: Path | None = None, environ: dict | None = None) -> Credentials:
    env = environ if environ is not None else __import__("os").environ
    key_id = env.get("ALIYUN_OSS_ACCESS_KEY_ID")
    secret = env.get("ALIYUN_OSS_ACCESS_KEY_SECRET")
    endpoint = env.get("ALIYUN_OSS_ENDPOINT", DEFAULT_ENDPOINT)
    if key_id and secret:
        return Credentials(key_id, secret, endpoint)

    config_path = Path(path) if path else Path.home() / ".ossutilconfig"
    if not config_path.exists():
        raise SystemExit(
            f"{config_path}: no OSS credentials. Put accessKeyID/accessKeySecret under "
            "[Credentials] there, or set ALIYUN_OSS_ACCESS_KEY_ID and "
            "ALIYUN_OSS_ACCESS_KEY_SECRET.")
    parser = configparser.ConfigParser()
    parser.read(config_path, encoding="utf-8")
    section = parser["Credentials"] if parser.has_section("Credentials") else parser.defaults()
    key_id = section.get("accessKeyID") or section.get("accesskeyid")
    secret = section.get("accessKeySecret") or section.get("accesskeysecret")
    endpoint = section.get("endpoint") or endpoint
    if not key_id or not secret:
        raise SystemExit(f"{config_path}: accessKeyID/accessKeySecret missing under [Credentials]")
    return Credentials(key_id, secret, endpoint)


def canonical_string(method: str, content_md5: str, content_type: str, date: str,
                     oss_headers: dict, bucket: str, key: str) -> str:
    headers = "".join(f"{name}:{value}\n" for name, value in sorted(oss_headers.items()))
    return f"{method}\n{content_md5}\n{content_type}\n{date}\n{headers}/{bucket}/{key}"


def oss_signature(secret: str, string_to_sign: str) -> str:
    digest = hmac.new(secret.encode("utf-8"), string_to_sign.encode("utf-8"), hashlib.sha1).digest()
    return base64.b64encode(digest).decode("ascii")


def content_type_for(path: Path) -> str:
    return CONTENT_TYPES.get(path.suffix.lower(), "application/octet-stream")


def plan_uploads(pack_dir: Path, prefix: str) -> list[dict]:
    prefix = prefix.strip("/")
    rows = []
    for path in sorted(pack_dir.rglob("*")):
        if not path.is_file():
            continue
        key = f"{prefix}/{path.relative_to(pack_dir).as_posix()}" if prefix else path.relative_to(pack_dir).as_posix()
        rows.append({"path": path, "key": key, "size": path.stat().st_size,
                     "contentType": content_type_for(path)})
    return rows


def object_url(bucket: str, endpoint: str, key: str) -> str:
    return f"https://{bucket}.{endpoint}/{urllib.parse.quote(key)}"


def _request(method: str, url: str, credentials: Credentials, bucket: str, key: str,
             *, body: bytes | None = None, content_type: str = "",
             timeout: float = 120, opener=None) -> tuple[int, dict]:
    date = formatdate(usegmt=True)
    md5 = base64.b64encode(hashlib.md5(body).digest()).decode("ascii") if body is not None else ""
    oss_headers = {"x-oss-object-acl": "public-read"} if method == "PUT" else {}
    string_to_sign = canonical_string(method, md5, content_type, date, oss_headers, bucket, key)
    headers = {
        "Date": date,
        "Authorization": f"OSS {credentials.key_id}:{oss_signature(credentials.key_secret, string_to_sign)}",
    }
    if content_type:
        headers["Content-Type"] = content_type
    if md5:
        headers["Content-MD5"] = md5
    headers.update(oss_headers)
    request = urllib.request.Request(url, data=body, headers=headers, method=method)
    send = opener or urllib.request.urlopen
    try:
        with send(request, timeout=timeout) as response:
            return response.status, dict(response.headers)
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", "replace")[:400]
        raise RuntimeError(f"{method} {key}: HTTP {error.code} {detail}") from error


def publish(args: argparse.Namespace) -> dict:
    pack_dir = Path(args.pack).resolve()
    if not (pack_dir / "pack.json").exists():
        raise SystemExit(f"{pack_dir}: pack.json not found; build the pack first")

    prefix = args.prefix
    rows = plan_uploads(pack_dir, prefix)
    total = sum(row["size"] for row in rows)
    url = object_url(args.bucket, args.endpoint, f"{prefix.strip('/')}/index.html")

    if not args.execute:
        return {"ok": True, "dryRun": True, "bucket": args.bucket, "prefix": prefix,
                "files": len(rows), "bytes": total, "url": url,
                "plan": [{"key": row["key"], "bytes": row["size"], "contentType": row["contentType"]}
                         for row in rows[: args.show]]}

    credentials = load_credentials(args.config)
    uploaded = 0
    for row in rows:
        body = row["path"].read_bytes()
        _request("PUT", object_url(args.bucket, args.endpoint, row["key"]), credentials,
                 args.bucket, row["key"], body=body, content_type=row["contentType"])
        uploaded += 1
    return {"ok": True, "dryRun": False, "bucket": args.bucket, "prefix": prefix,
            "files": uploaded, "bytes": total, "url": url}


def remove(args: argparse.Namespace) -> dict:
    credentials = load_credentials(args.config)
    pack_dir = Path(args.pack).resolve() if args.pack else None
    if pack_dir:
        keys = [row["key"] for row in plan_uploads(pack_dir, args.prefix)]
    else:
        raise SystemExit("remove needs --pack so the key list is derived from real files")
    if not args.execute:
        return {"ok": True, "dryRun": True, "wouldDelete": len(keys), "keys": keys[: args.show]}
    deleted = 0
    for key in keys:
        _request("DELETE", object_url(args.bucket, args.endpoint, key), credentials, args.bucket, key)
        deleted += 1
    return {"ok": True, "dryRun": False, "deleted": deleted}


if __name__ == "__main__":
    sys.exit(main())
