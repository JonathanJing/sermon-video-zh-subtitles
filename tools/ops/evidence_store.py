#!/usr/bin/env python3
"""Private evidence store: a run's small text evidence in a private GCS prefix.

Run evidence lives under ignored ``artifacts/`` on whichever machine ran the
stage, so a retrospective depends on that machine being reachable. The public
run report (tools/development/export_run_digest.py) cannot carry sermon text,
translations, review sheets or listener feedback: the repository is public.
This tool keeps those in a private bucket instead, where any authorised
session can read them.

What a bundle holds: text files (JSON, JSONL, NDJSON, TSV, CSV, Markdown, logs,
SRT, small HTML) of a run directory, up to a per-file size cap. Media, hosting
snapshots (``public/``), sentence slices and binary files are counted, never
copied. Credentials are scrubbed even here: API keys, tokens, bearer values,
private keys and the values of secret-like environment variables are replaced
before upload; credential files are never read. Each bundle has
``_manifest.json`` with the source host and path, every copied file's original
SHA-256 and size, what was omitted and why.

Store layout (``<store>`` is ``gs://bucket/prefix`` or a local directory):

    <store>/runs/<run-directory-name>/<relative path>
    <store>/runs/<run-directory-name>/_manifest.json
    <store>/frontend/<FROM>_<TO>/<report>/summary.json
    <store>/weekly/<YYYYMMDD>/...

Usage (repo root):

    # upload one or more run directories
    .venv/bin/python tools/ops/evidence_store.py push artifacts/sentence-first-agent/20261115-x-zh [...]
    # collect on another machine without this checkout, upload from here
    ssh HOST 'python3 - collect --tar - RUN_DIR [...]' < tools/ops/evidence_store.py > bundle.tar.gz
    .venv/bin/python tools/ops/evidence_store.py push-tar bundle.tar.gz
    # upload a private frontend report or weekly notes
    .venv/bin/python tools/ops/evidence_store.py put artifacts/sermon-dubbing/usage-report-x --dest frontend/20261109_20261115/usage
    # read back
    .venv/bin/python tools/ops/evidence_store.py list [--prefix runs/20261115]
    .venv/bin/python tools/ops/evidence_store.py pull runs/20261115-x-zh --out artifacts/evidence-cache
    # public-safe index (names, counts, hashes) that the weekly rollup reads
    .venv/bin/python tools/ops/evidence_store.py index --out docs/reports/weekly/private-evidence-index.json

The store comes from ``--store``, else ``TONGXING_EVIDENCE_STORE``, else
``DEFAULT_STORE``. ``collect`` uses only the standard library (Python 3.9+), so
it runs over SSH from stdin; uploads to ``gs://`` need google-cloud-storage and
Application Default Credentials. Nothing here publishes: the bucket must keep
uniform bucket-level access with public access prevention enforced, and
``check`` fails when it does not.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import io
import json
import os
import re
import socket
import sys
import tarfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

SCHEMA = "sermon-run-evidence-bundle-v1"
DEFAULT_STORE = "gs://sermon-zh-artifacts-ai-for-god/run-evidence/v1"
STORE_ENV = "TONGXING_EVIDENCE_STORE"
MANIFEST = "_manifest.json"
TEXT_SUFFIXES = {".json", ".jsonl", ".ndjson", ".tsv", ".csv", ".md", ".txt", ".log", ".srt", ".vtt", ".yml", ".yaml"}
HTML_SUFFIXES = {".html", ".htm"}
MAX_FILE_BYTES = 16 * 1024 * 1024
MAX_HTML_BYTES = 2 * 1024 * 1024
MAX_FILES = 5000
# Hosting snapshots (already public bytes), per-sentence audio and tool caches are never evidence.
SKIP_DIRS = {"public", "slices", "node_modules", ".git", "__pycache__", ".venv", "dist"}
# Never read: credentials and the journal's host salt (run_journal.py keeps it out of every export).
DENY_NAME = re.compile(
    r"(?i)^(?:\.env(?:\..*)?|\.journal-host-salt|application_default_credentials\.json|.*service[-_]?account.*\.json"
    r"|.*credentials?.*\.json|.*cookies?.*|.*\.(?:pem|key|p12|pfx|keystore|mobileprovision|lock))$")
DEST_ROOTS = ("frontend", "weekly")
NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")

SCRUBS = [
    ("private_key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.S),
     "<private-key>"),
    ("openai_key", re.compile(r"\bsk-[A-Za-z0-9_-]{16,}"), "<openai-key>"),
    ("github_token", re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})"), "<github-token>"),
    ("google_key", re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b"), "<google-key>"),
    ("bearer", re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]{8,}"), "Bearer <redacted>"),
    ("secret_field", re.compile(
        r"(?i)(\"?[\w-]*(?:api[_-]?key|token|secret|password|passwd|cookie|authorization)\"?\s*[:=]\s*)"
        r"(\"[^\"\n]*\"|'[^'\n]*'|[^\s,;}]+)"),
     lambda m: m[1] + ('"<redacted>"' if m[2][0] == '"' else "'<redacted>'" if m[2][0] == "'" else "<redacted>")),
]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def env_secret_values() -> list[str]:
    marker = re.compile(r"KEY|TOKEN|SECRET|PASSWORD|COOKIE", re.I)
    return sorted({v for k, v in os.environ.items() if marker.search(k) and len(v) >= 8}, key=len, reverse=True)


def scrub(text: str, secrets: list[str]) -> tuple[str, int]:
    """Replace credentials; sermon text, names and paths stay (the store is private)."""
    count = 0
    for _, pattern, replacement in SCRUBS:
        text, n = pattern.subn(replacement, text)
        count += n
    for value in secrets:
        if value in text:
            count += text.count(value)
            text = text.replace(value, "<env-secret>")
    return text, count


def run_name(run_dir: Path) -> str:
    name = re.sub(r"[^A-Za-z0-9._-]+", "-", Path(run_dir).resolve().name).strip("-.")
    if not NAME.fullmatch(name):
        raise ValueError(f"cannot derive a store name from {run_dir}")
    return name


def source_id(host: str, path: str) -> str:
    return hashlib.sha256(f"{host}\n{path}".encode()).hexdigest()[:16]


def collect(run_dir: Path, secrets: list[str] | None = None, host: str | None = None) -> tuple[dict, dict[str, bytes]]:
    """Return (manifest, {relative path: scrubbed bytes}) for one run directory; reads only, never writes."""
    run_dir = Path(run_dir).resolve()
    if not run_dir.is_dir():
        raise ValueError(f"{run_dir} is not a directory")
    secrets = env_secret_values() if secrets is None else secrets
    host = host or socket.gethostname().split(".")[0]
    files: dict[str, bytes] = {}
    entries: list[dict] = []
    omitted: list[dict] = []
    skipped: dict[str, dict[str, int]] = {}

    def count_skip(key: str, size: int, unit: str = "files") -> None:
        row = skipped.setdefault(key, {unit: 0, "bytes": 0})
        row[unit] += 1
        row["bytes"] += size

    for root, dirs, names in os.walk(run_dir, followlinks=False):
        root_path = Path(root)
        for name in sorted(dirs):
            if name in SKIP_DIRS or (root_path / name).is_symlink():
                dirs.remove(name)
                size = files_under(root_path / name)
                count_skip(f"dir:{name}", size, "dirs")
        dirs.sort()
        for name in sorted(names):
            path = root_path / name
            if path.is_symlink() or not path.is_file():
                continue
            rel = path.relative_to(run_dir).as_posix()
            size = path.stat().st_size
            suffix = path.suffix.lower()
            if DENY_NAME.match(name):
                omitted.append({"path": rel, "bytes": size, "reason": "denied_name"})
                continue
            if suffix not in TEXT_SUFFIXES and suffix not in HTML_SUFFIXES:
                count_skip(suffix or "(none)", size)
                continue
            cap = MAX_HTML_BYTES if suffix in HTML_SUFFIXES else MAX_FILE_BYTES
            if size > cap:
                omitted.append({"path": rel, "bytes": size, "reason": "over_size_cap"})
                continue
            if len(entries) >= MAX_FILES:
                omitted.append({"path": rel, "bytes": size, "reason": "over_file_count_cap"})
                continue
            raw = path.read_bytes()
            try:
                text = raw.decode("utf-8")
            except UnicodeDecodeError:
                omitted.append({"path": rel, "bytes": size, "reason": "not_utf8"})
                continue
            cleaned, scrubbed = scrub(text, secrets)
            files[rel] = cleaned.encode("utf-8")
            entries.append({"path": rel, "bytes": size, "sha256": hashlib.sha256(raw).hexdigest(), "scrubbed": scrubbed})
    manifest = {
        "schemaVersion": SCHEMA,
        "runName": run_name(run_dir),
        "collectedAt": utc_now(),
        "source": {"host": host, "path": str(run_dir), "sourceId": source_id(host, str(run_dir))},
        "limits": {"maxFileBytes": MAX_FILE_BYTES, "maxHtmlBytes": MAX_HTML_BYTES, "maxFiles": MAX_FILES},
        "files": entries,
        "omitted": omitted,
        "skipped": dict(sorted(skipped.items())),
        "totals": {"files": len(entries), "bytes": sum(len(v) for v in files.values()),
                   "scrubbed": sum(e["scrubbed"] for e in entries)},
    }
    return manifest, files


def files_under(path: Path) -> int:
    total = 0
    for root, _, names in os.walk(path, followlinks=False):
        for name in names:
            try:
                total += (Path(root) / name).lstat().st_size
            except OSError:
                pass
    return total


def manifest_bytes(manifest: dict) -> bytes:
    return (json.dumps(manifest, ensure_ascii=False, indent=1) + "\n").encode("utf-8")


def write_tar(run_dirs: list[Path], out, secrets: list[str] | None = None) -> list[dict]:
    """Write one gzip tar holding every run as ``<runName>/...``; ``out`` is a binary stream."""
    manifests = []
    seen: set[str] = set()
    with tarfile.open(fileobj=out, mode="w:gz") as archive:
        for run_dir in run_dirs:
            manifest, files = collect(run_dir, secrets)
            name = manifest["runName"]
            if name in seen:
                raise ValueError(f"two run directories share the name {name}")
            seen.add(name)
            for rel, data in [(MANIFEST, manifest_bytes(manifest)), *sorted(files.items())]:
                info = tarfile.TarInfo(f"{name}/{rel}")
                info.size = len(data)
                info.mtime = 0
                archive.addfile(info, io.BytesIO(data))
            manifests.append(manifest)
    return manifests


def read_tar(stream) -> list[tuple[dict, dict[str, bytes]]]:
    """Read a tar written by ``write_tar``; rejects absolute or parent-escaping member names."""
    bundles: dict[str, dict[str, bytes]] = {}
    with tarfile.open(fileobj=stream, mode="r:gz") as archive:
        for member in archive:
            if not member.isfile():
                continue
            parts = PurePosixPath(member.name).parts
            if member.name.startswith("/") or ".." in parts or len(parts) < 2 or not NAME.fullmatch(parts[0]):
                raise ValueError(f"unsafe member in bundle: {member.name}")
            bundles.setdefault(parts[0], {})["/".join(parts[1:])] = archive.extractfile(member).read()
    result = []
    for name, files in sorted(bundles.items()):
        if MANIFEST not in files:
            raise ValueError(f"bundle {name} has no {MANIFEST}")
        manifest = json.loads(files.pop(MANIFEST))
        if manifest.get("schemaVersion") != SCHEMA or manifest.get("runName") != name:
            raise ValueError(f"bundle {name} has an unexpected manifest")
        result.append((manifest, files))
    return result


# ---------------------------------------------------------------- stores

class LocalStore:
    """A directory with the store layout; used for tests, dry runs and an offline cache."""

    def __init__(self, root: Path):
        self.root = Path(root)
        self.uri = str(self.root)

    def read(self, key: str) -> bytes | None:
        path = self.root / key
        return path.read_bytes() if path.is_file() else None

    def md5s(self, prefix: str) -> dict[str, str]:
        base = self.root / prefix
        if not base.is_dir():
            return {}
        return {p.relative_to(self.root).as_posix(): hashlib.md5(p.read_bytes()).hexdigest()
                for p in sorted(base.rglob("*")) if p.is_file()}

    def write(self, key: str, data: bytes) -> None:
        path = self.root / key
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    def names(self, prefix: str) -> list[str]:
        base = self.root / prefix
        parent = base if base.is_dir() else base.parent
        if not parent.is_dir():
            return []
        return sorted(p.relative_to(self.root).as_posix() + ("/" if p.is_dir() else "")
                      for p in parent.iterdir() if p.relative_to(self.root).as_posix().startswith(prefix))

    def check(self) -> list[str]:
        return []


class GcsStore:
    """``gs://bucket/prefix`` through google-cloud-storage and Application Default Credentials."""

    def __init__(self, uri: str, client=None):
        match = re.fullmatch(r"gs://([a-z0-9][a-z0-9._-]{1,220})(?:/(.*))?", uri)
        if not match:
            raise ValueError(f"not a gs:// store: {uri}")
        self.uri = uri.rstrip("/")
        self.prefix = (match[2] or "").strip("/")
        if client is None:
            import warnings
            warnings.filterwarnings("ignore", message="Your application has authenticated using end user credentials")
            from google.cloud import storage  # Imported here so ``collect`` stays standard-library only.
            client = storage.Client(project=os.environ.get("GOOGLE_CLOUD_PROJECT") or "tongxing-evidence-store")
        self.client = client
        self.bucket = client.bucket(match[1])

    def _key(self, key: str) -> str:
        return f"{self.prefix}/{key}" if self.prefix else key

    def _strip(self, name: str) -> str:
        return name[len(self.prefix) + 1:] if self.prefix else name

    def read(self, key: str) -> bytes | None:
        blob = self.bucket.blob(self._key(key))
        return blob.download_as_bytes() if blob.exists() else None

    def md5s(self, prefix: str) -> dict[str, str]:
        result = {}
        for blob in self.client.list_blobs(self.bucket, prefix=self._key(prefix)):
            if blob.md5_hash:
                result[self._strip(blob.name)] = base64.b64decode(blob.md5_hash).hex()
        return result

    def write(self, key: str, data: bytes) -> None:
        suffix = PurePosixPath(key).suffix.lower()
        kind = "application/json" if suffix == ".json" else "text/html" if suffix in HTML_SUFFIXES else "text/plain"
        self.bucket.blob(self._key(key)).upload_from_string(data, content_type=f"{kind}; charset=utf-8")

    def names(self, prefix: str) -> list[str]:
        iterator = self.client.list_blobs(self.bucket, prefix=self._key(prefix), delimiter="/")
        names = [self._strip(blob.name) for blob in iterator]
        return sorted([*names, *(self._strip(p) for p in iterator.prefixes)])

    def check(self) -> list[str]:
        """The reasons this bucket must not hold private evidence (empty when it may)."""
        self.bucket.reload()
        config = self.bucket.iam_configuration
        problems = []
        if not config.uniform_bucket_level_access_enabled:
            problems.append("uniform bucket-level access is off (per-object ACLs could publish a file)")
        if config.public_access_prevention != "enforced":
            problems.append(f"public access prevention is {config.public_access_prevention!r}, not 'enforced'")
        return problems


def open_store(uri: str | None, client=None):
    uri = uri or os.environ.get(STORE_ENV) or DEFAULT_STORE
    return GcsStore(uri, client) if uri.startswith("gs://") else LocalStore(Path(uri).expanduser())


def upload_bundle(store, manifest: dict, files: dict[str, bytes], *, replace_source: bool = False,
                  dry_run: bool = False) -> dict:
    """Upload one bundle under ``runs/<runName>/``; unchanged files are not sent again."""
    name = manifest["runName"]
    prefix = f"runs/{name}/"
    previous = store.read(prefix + MANIFEST)
    if previous is not None:
        other = json.loads(previous).get("source", {})
        if other.get("sourceId") != manifest["source"]["sourceId"] and not replace_source:
            raise ValueError(
                f"{store.uri}/{prefix} already holds a bundle from {other.get('host')}:{other.get('path')}; "
                "a run directory with the same name on another machine is a different run. "
                "Rename one, or pass --replace-source to merge this one over it.")
    existing = store.md5s(prefix)
    sent = unchanged = 0
    for rel, data in sorted(files.items()):
        if existing.get(prefix + rel) == hashlib.md5(data).hexdigest():
            unchanged += 1
            continue
        if not dry_run:
            store.write(prefix + rel, data)
        sent += 1
    if not dry_run:
        body = manifest_bytes(manifest)
        store.write(prefix + MANIFEST, body)
        stamp = re.sub(r"[^0-9A-Za-z]", "", manifest["collectedAt"])
        store.write(f"{prefix}_manifests/{stamp}.json", body)
    return {"runName": name, "store": f"{store.uri}/{prefix}", "sent": sent, "unchanged": unchanged,
            "omitted": len(manifest["omitted"]), "scrubbed": manifest["totals"]["scrubbed"], "dryRun": dry_run}


def put_directory(store, directory: Path, dest: str, *, secrets: list[str] | None = None, dry_run: bool = False) -> dict:
    """Upload a private report directory (frontend report, weekly notes) under ``<dest>/``."""
    parts = PurePosixPath(dest).parts
    if not parts or parts[0] not in DEST_ROOTS or ".." in parts or dest.startswith("/") or \
            not all(NAME.fullmatch(part) for part in parts):
        raise ValueError(f"--dest must be a relative path under one of {', '.join(DEST_ROOTS)}/")
    manifest, files = collect(directory, secrets)
    prefix = "/".join(parts) + "/"
    existing = store.md5s(prefix)
    sent = 0
    for rel, data in sorted(files.items()):
        if existing.get(prefix + rel) != hashlib.md5(data).hexdigest():
            if not dry_run:
                store.write(prefix + rel, data)
            sent += 1
    if not dry_run:
        store.write(prefix + MANIFEST, manifest_bytes(manifest))
    return {"store": f"{store.uri}/{prefix}", "sent": sent, "files": len(files), "omitted": len(manifest["omitted"]),
            "dryRun": dry_run}


def pull(store, prefix: str, out: Path) -> list[str]:
    """Download every object under ``prefix`` into ``out``; returns the relative paths written."""
    prefix = prefix.strip("/") + "/"
    if ".." in PurePosixPath(prefix).parts:
        raise ValueError("prefix must not contain '..'")
    written = []
    for key in sorted(store.md5s(prefix)):
        data = store.read(key)
        if data is None:
            continue
        target = Path(out) / key
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        written.append(key)
    return written


INDEX_SCHEMA = "sermon-private-evidence-index-v1"


def build_index(store) -> dict:
    """What the private store holds, in a form a public repository may carry: names, counts and hashes only."""
    runs = []
    for name in store.names("runs/"):
        body = store.read(name + MANIFEST) if name.endswith("/") else None
        if body is None:
            continue
        manifest = json.loads(body)
        runs.append({"runName": manifest["runName"], "files": manifest["totals"]["files"],
                     "collectedAt": manifest["collectedAt"], "manifestSha256": hashlib.sha256(body).hexdigest()})
    weeks = {root: sorted(PurePosixPath(name).name for name in store.names(f"{root}/") if name.endswith("/"))
             for root in DEST_ROOTS}
    return {"schemaVersion": INDEX_SCHEMA, "store": store.uri, "generatedAt": utc_now(),
            "runs": sorted(runs, key=lambda row: row["runName"]), **weeks}


def push_runs(run_dirs: list[Path], store_uri: str | None = None, *, replace_source: bool = False,
              dry_run: bool = False, client=None) -> list[dict]:
    """Collect and upload run directories; the entry point drivers call when a run ends."""
    store = open_store(store_uri, client)
    problems = store.check()
    if problems:
        raise ValueError(f"{store.uri} must not hold private evidence: " + "; ".join(problems))
    results = []
    for run_dir in run_dirs:
        manifest, files = collect(run_dir)
        results.append(upload_bundle(store, manifest, files, replace_source=replace_source, dry_run=dry_run))
    return results


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)

    def store_arg(p):
        p.add_argument("--store", help=f"gs://bucket/prefix or a local directory (default: ${STORE_ENV} or {DEFAULT_STORE})")

    p = sub.add_parser("collect", help="write a tar.gz of the evidence (standard library only; runs over SSH)")
    p.add_argument("run_dirs", nargs="+", type=Path)
    p.add_argument("--tar", required=True, help="output file, or - for stdout")

    p = sub.add_parser("push", help="collect run directories and upload them")
    p.add_argument("run_dirs", nargs="+", type=Path)
    store_arg(p)
    p.add_argument("--replace-source", action="store_true")
    p.add_argument("--dry-run", action="store_true")

    p = sub.add_parser("push-tar", help="upload a tar.gz written by collect")
    p.add_argument("tar", help="tar.gz file, or - for stdin")
    store_arg(p)
    p.add_argument("--replace-source", action="store_true")
    p.add_argument("--dry-run", action="store_true")

    p = sub.add_parser("put", help="upload a private report directory under frontend/ or weekly/")
    p.add_argument("directory", type=Path)
    p.add_argument("--dest", required=True)
    store_arg(p)
    p.add_argument("--dry-run", action="store_true")

    p = sub.add_parser("list", help="list names under a prefix")
    p.add_argument("--prefix", default="runs/")
    store_arg(p)

    p = sub.add_parser("pull", help="download everything under a prefix")
    p.add_argument("prefix")
    p.add_argument("--out", type=Path, required=True)
    store_arg(p)

    p = sub.add_parser("check", help="verify the store cannot be public")
    store_arg(p)

    p = sub.add_parser("index", help="write a public-safe index of the store: names, counts and hashes")
    p.add_argument("--out", type=Path, required=True)
    store_arg(p)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "collect":
            if args.tar == "-":
                manifests = write_tar(args.run_dirs, sys.stdout.buffer)
            else:
                with open(args.tar, "wb") as stream:
                    manifests = write_tar(args.run_dirs, stream)
            for manifest in manifests:
                totals = manifest["totals"]
                print(f"{manifest['runName']}: {totals['files']} files, {totals['bytes']} bytes, "
                      f"{totals['scrubbed']} scrubbed, {len(manifest['omitted'])} omitted", file=sys.stderr)
            return 0
        store = open_store(args.store)
        if args.command == "check":
            problems = store.check()
            print("\n".join(problems) or f"{store.uri}: private (uniform access, public access prevention enforced)")
            return 1 if problems else 0
        if args.command == "list":
            print("\n".join(store.names(args.prefix)))
            return 0
        if args.command == "index":
            index = build_index(store)
            args.out.parent.mkdir(parents=True, exist_ok=True)
            args.out.write_text(json.dumps(index, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            print(f"{args.out}: {len(index['runs'])} runs, {len(index['frontend'])} frontend weeks, "
                  f"{len(index['weekly'])} weekly notes")
            return 0
        if args.command == "pull":
            written = pull(store, args.prefix, args.out)
            print(f"{len(written)} files → {args.out}")
            return 0
        problems = store.check()
        if problems:
            raise ValueError(f"{store.uri} must not hold private evidence: " + "; ".join(problems))
        if args.command == "put":
            print(json.dumps(put_directory(store, args.directory, args.dest, dry_run=args.dry_run), ensure_ascii=False))
            return 0
        if args.command == "push":
            bundles = [collect(run_dir) for run_dir in args.run_dirs]
        else:
            stream = sys.stdin.buffer if args.tar == "-" else open(args.tar, "rb")
            with stream:
                bundles = read_tar(io.BytesIO(stream.read()))
        for manifest, files in bundles:
            result = upload_bundle(store, manifest, files, replace_source=args.replace_source, dry_run=args.dry_run)
            print(json.dumps(result, ensure_ascii=False))
        return 0
    except (ValueError, OSError) as error:
        print(f"evidence_store: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
