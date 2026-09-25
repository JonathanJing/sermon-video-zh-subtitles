#!/usr/bin/env python3
"""Fail-closed documentation-only classification for the required unittest check."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import unquote, urlsplit


IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}
INLINE_LINK = re.compile(r"!?\[[^\]]*\]\(([^)]+)\)")
REFERENCE_LINK = re.compile(r"^ {0,3}\[[^\]]+\]:\s*(\S+)", re.MULTILINE)
HTML_LINK = re.compile(r"\b(?:src|href)\s*=\s*[\"']([^\"']+)[\"']", re.IGNORECASE)


def is_documentation_path(path: str) -> bool:
    if path in {"README.md", "README.zh.md"}:
        return True
    file = Path(path)
    if not path.startswith("docs/") or ".." in file.parts:
        return False
    return file.suffix.lower() in {".md", ".svg", *IMAGE_SUFFIXES} or path == "docs/diagrams/diagram-specs.json"


def documentation_only(paths: list[str]) -> bool:
    return bool(paths) and all(is_documentation_path(path) for path in paths)


def changed_paths(base: str, head: str, event: str) -> list[str]:
    if not base or not head or set(base) == {"0"}:
        return []
    if not re.fullmatch(r"[0-9a-f]{40}", base) or not re.fullmatch(r"[0-9a-f]{40}", head):
        raise ValueError("Expected full Git commit SHAs")
    revision = f"{base}...{head}" if event == "pull_request" else f"{base}..{head}"
    result = subprocess.check_output(["git", "diff", "--no-renames", "--name-only", "-z", revision])
    return [part.decode("utf-8") for part in result.split(b"\0") if part]


def local_link_targets(path: Path):
    # Examples inside fenced code blocks are not live Markdown links.
    lines = []
    fence = None
    for line in path.read_text(encoding="utf-8").splitlines():
        marker = re.match(r"^\s{0,3}(`{3,}|~{3,})", line)
        if marker:
            if fence is None:
                fence = marker.group(1)[0]
            elif marker.group(1)[0] == fence:
                fence = None
            continue
        if fence is None:
            lines.append(line)
    content = "\n".join(lines)
    for raw in (*INLINE_LINK.findall(content), *REFERENCE_LINK.findall(content), *HTML_LINK.findall(content)):
        target = raw.strip().split(" ", 1)[0].strip("<>")
        url = urlsplit(target)
        if url.scheme or url.netloc or not url.path or url.path.startswith("/"):
            continue
        yield raw, (path.parent / unquote(url.path)).resolve()


def check_markdown_links(path: Path) -> None:
    for raw, candidate in local_link_targets(path):
        if not candidate.exists():
            raise ValueError(f"Broken local link in {path}: {raw}")


def check_inbound_links(root: Path, deleted: list[str]) -> None:
    if not deleted:
        return
    deleted_targets = {(root / name).resolve() for name in deleted}
    tracked = subprocess.check_output(["git", "ls-files", "-z"], cwd=root)
    for part in tracked.split(b"\0"):
        if not part or not part.endswith(b".md"):
            continue
        path = root / part.decode("utf-8")
        if not path.is_file() or path.is_symlink():
            continue
        for raw, candidate in local_link_targets(path):
            if candidate in deleted_targets:
                raise ValueError(f"Deleted documentation asset is still linked in {path}: {raw}")


def check_image(path: Path) -> None:
    data = path.read_bytes()[:16]
    suffix = path.suffix.lower()
    valid = (
        data.startswith(b"\x89PNG\r\n\x1a\n") if suffix == ".png" else
        data.startswith(b"\xff\xd8\xff") if suffix in {".jpg", ".jpeg"} else
        data.startswith(b"RIFF") and data[8:12] == b"WEBP"
    )
    if not valid:
        raise ValueError(f"Image signature does not match extension: {path}")


def check_generated_diagrams(root: Path, paths: list[str]) -> None:
    changed_diagrams = {Path(path).name for path in paths if path.startswith("docs/diagrams/") and path.endswith(".svg")}
    spec_changed = "docs/diagrams/diagram-specs.json" in paths
    if not changed_diagrams and not spec_changed:
        return
    spec = root / "docs/diagrams/diagram-specs.json"
    names = {item["name"] + ".svg" for item in json.loads(spec.read_text(encoding="utf-8"))}
    compared = names if spec_changed else names & changed_diagrams
    if not compared:
        return
    with tempfile.TemporaryDirectory() as destination:
        subprocess.run(
            [sys.executable, str(root / "docs/diagrams/render_diagrams.py"), "--spec", str(spec), "--out-dir", destination],
            check=True, capture_output=True, text=True,
        )
        for name in compared:
            committed = root / "docs/diagrams" / name
            generated = Path(destination) / name
            if committed.read_bytes() != generated.read_bytes():
                raise ValueError(f"Generated diagram differs from diagram-specs.json: {name}")


def check_documentation(root: Path, paths: list[str], base: str, head: str, event: str) -> None:
    revision = f"{base}...{head}" if event == "pull_request" else f"{base}..{head}"
    subprocess.run(["git", "diff", "--check", revision], check=True, cwd=root)
    deleted = []
    for name in paths:
        path = root / name
        if path.is_symlink():
            raise ValueError(f"Documentation symlink needs full review: {name}")
        if not path.exists():  # Deleted documentation does not need content validation.
            deleted.append(name)
            continue
        suffix = path.suffix.lower()
        if suffix == ".md":
            check_markdown_links(path)
        elif suffix == ".svg":
            ET.parse(path)
        elif suffix in IMAGE_SUFFIXES:
            check_image(path)
        elif name == "docs/diagrams/diagram-specs.json":
            json.loads(path.read_text(encoding="utf-8"))
    check_inbound_links(root, deleted)
    check_generated_diagrams(root, paths)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", required=True)
    parser.add_argument("--head", required=True)
    parser.add_argument("--event", choices=("pull_request", "push"), required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        paths = changed_paths(args.base, args.head, args.event)
    except (subprocess.CalledProcessError, ValueError) as exc:
        print(f"Cannot classify changes; running full tests: {exc}", file=sys.stderr)
        paths = []
    docs_only = documentation_only(paths)
    if docs_only:
        check_documentation(Path.cwd(), paths, args.base, args.head, args.event)
    with args.output.open("a", encoding="utf-8") as output:
        output.write(f"docs_only={str(docs_only).lower()}\n")
    print(f"Documentation only: {docs_only}; changed paths: {len(paths)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
