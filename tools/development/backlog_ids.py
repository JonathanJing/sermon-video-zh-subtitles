#!/usr/bin/env python3
"""Find where a backlog ID is defined and what each row says.

docs/backlog.zh.md is one page of dated sections whose tables restate stable
IDs, so "what is the current status of DEV-R242-011" meant reading a very
large file. This prints every table row that names the ID, newest section
first, with its section heading and line number:

    python3 scripts/backlog_ids.py DEV-R242-011      one ID
    python3 scripts/backlog_ids.py DEV-R242          a prefix
    python3 scripts/backlog_ids.py --prefixes        every prefix with its row count and sections

A row names an ID in its first cell. A cell such as ``DEV-L4-001/005`` names
both ``DEV-L4-001`` and ``DEV-L4-005``. The file is read top to bottom and the
top is the newest section (backlog.zh.md maintenance rule 6), so the first hit
is the one to read first.
"""
from __future__ import annotations

import argparse
import re
import sys
from collections import defaultdict
from pathlib import Path

BACKLOG = Path(__file__).resolve().parents[1] / "docs/backlog.zh.md"
ROW = re.compile(r"^\|\s*(?P<first>[^|]*?)\s*\|(?P<rest>.*)\|\s*$")
ID = re.compile(r"DEV-[A-Z0-9]+-\d{3}(?:/\d{3})*")
HEADING = re.compile(r"^(#{2,4})\s+(.*\S)\s*$")


def expand(token: str) -> list[str]:
    """``DEV-L4-001/005`` -> ``DEV-L4-001``, ``DEV-L4-005``."""
    head, *tails = token.split("/")
    prefix = head.rsplit("-", 1)[0]
    return [head] + [f"{prefix}-{tail}" for tail in tails]


def rows(text: str):
    """Yield (id, section, line number, status cell, first words) for every table row naming an ID."""
    section = ""
    for number, line in enumerate(text.splitlines(), 1):
        heading = HEADING.match(line)
        if heading and len(heading.group(1)) == 2:
            section = heading.group(2)
            continue
        match = ROW.match(line)
        if not match:
            continue
        first = match.group("first")
        cells = [cell.strip() for cell in match.group("rest").split("|")]
        for token in ID.findall(first):
            for identifier in expand(token):
                status = cells[0] if cells else ""
                text_cell = next((cell for cell in cells[1:] if cell), "")
                yield identifier, section, number, status, text_cell


def lookup(query: str, text: str | None = None) -> list[tuple]:
    text = BACKLOG.read_text(encoding="utf-8") if text is None else text
    query = query.strip().upper()
    if not re.fullmatch(r"DEV-[A-Z0-9]+(?:-\d{3})?", query):
        raise ValueError("give an ID such as DEV-R242-011 or a prefix such as DEV-R242")
    exact = bool(re.search(r"-\d{3}$", query))
    return [row for row in rows(text) if (row[0] == query if exact else row[0].startswith(query + "-"))]


def prefixes(text: str | None = None) -> dict[str, dict]:
    text = BACKLOG.read_text(encoding="utf-8") if text is None else text
    result: dict[str, dict] = defaultdict(lambda: {"ids": set(), "rows": 0, "sections": []})
    for identifier, section, *_ in rows(text):
        entry = result[identifier.rsplit("-", 1)[0]]
        entry["ids"].add(identifier)
        entry["rows"] += 1
        if section not in entry["sections"]:
            entry["sections"].append(section)
    return dict(result)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("query", nargs="?", help="An ID (DEV-R242-011) or a prefix (DEV-R242)")
    parser.add_argument("--prefixes", action="store_true", help="List every ID prefix with its sections")
    parser.add_argument("--file", type=Path, default=BACKLOG, help="Backlog file (default docs/backlog.zh.md)")
    args = parser.parse_args(argv)
    text = args.file.read_text(encoding="utf-8")
    if args.prefixes:
        for prefix, entry in sorted(prefixes(text).items()):
            print(f"{prefix}\t{len(entry['ids'])} ids\t{entry['rows']} rows\t" + " | ".join(entry["sections"][:3]))
        return 0
    if not args.query:
        parser.error("give an ID or a prefix, or --prefixes")
    try:
        found = lookup(args.query, text)
    except ValueError as error:
        parser.error(str(error))
    if not found:
        print(f"{args.query}: no table row names it", file=sys.stderr)
        return 1
    for identifier, section, number, status, first_words in found:
        print(f"{identifier}\tL{number}\t{section}\n    {status[:90]}\n    {first_words[:160]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
