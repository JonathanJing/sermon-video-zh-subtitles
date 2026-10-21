"""Build a clip-scoped copy of the source-bound 15030286 Layer 2 plugin set.

The three 15030286 plugins force ``SOURCE_SHA256`` in
``weekly_15030286_common.py`` to equal the *full-week* English source package
hash, so a clip built from the same sermon (which necessarily has its own
source package) is rejected before any model call. This tool writes a clip
variant into the run directory: only that one hash literal changes, every
approved correction rule is byte-for-byte the week's own, and the write is
refused unless a diff of the clone against the original shows exactly that
one line. The variant is a run artifact, not a repo file: it keeps the week's
pluginId so nobody mistakes it for a newly approved week plugin.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

BINDING = re.compile(r'^SOURCE_SHA256 = "([0-9a-f]{64})"$', re.M)
FILES = ("weekly_15030286_common.py", "zh_hans_weekly_15030286.py", "ko_weekly_15030286.py", "es_weekly_15030286.py")


def build(source_plugin_dir: Path, out: Path, *, expected_week_sha256: str, clip_source_sha256: str) -> dict:
    source_plugin_dir, out = Path(source_plugin_dir).resolve(), Path(out).resolve()
    common = source_plugin_dir / "weekly_15030286_common.py"
    original = common.read_bytes().decode("utf-8")
    found = BINDING.findall(original)
    if found != [expected_week_sha256]:
        raise SystemExit(f"expected exactly one SOURCE_SHA256 == {expected_week_sha256}, found {found}")
    if not re.fullmatch(r"[0-9a-f]{64}", clip_source_sha256):
        raise SystemExit("clip source hash must be a lowercase 64-character hex digest")
    pinned = out / "plugins"
    pinned.mkdir(parents=True, exist_ok=True)
    for name in FILES:
        if not (source_plugin_dir / name).is_file():
            raise SystemExit(f"missing source plugin {name}")
        shutil.copyfile(source_plugin_dir / name, pinned / name)
    changed = BINDING.sub(f'SOURCE_SHA256 = "{clip_source_sha256}"', original)
    (pinned / "weekly_15030286_common.py").write_text(changed, encoding="utf-8")
    diff = subprocess.run(["diff", "-u", str(pinned / "weekly_15030286_common.py"), str(common)],
                          capture_output=True, text=True).stdout
    removed = [line for line in diff.splitlines() if line.startswith("-") and not line.startswith("---")]
    added = [line for line in diff.splitlines() if line.startswith("+") and not line.startswith("+++")]
    if len(removed) != 1 or len(added) != 1 or not BINDING.match(removed[0][1:]) or not BINDING.match(added[0][1:]):
        raise SystemExit(f"clip variant must differ from the week plugin by the binding line only:\n{diff}")
    return {"weekSourceSha256": expected_week_sha256, "clipSourceSha256": clip_source_sha256,
            "files": list(FILES), "difference": added[0][1:].strip(), "diffFromWeek": diff}


def main(argv=None) -> int:
    import json
    argv = list(sys.argv[1:] if argv is None else argv)
    if len(argv) != 4:
        print("usage: build_clip_plugin_variant.py SOURCE_PLUGIN_DIR OUT_DIR EXPECTED_WEEK_SHA256 CLIP_SOURCE_SHA256")
        return 2
    src, out, week, clip = argv
    sys.path.insert(0, str(ROOT))
    from scripts import tongxing_host  # noqa: F401  binds the production package ports
    from tongxing_production.text import candidate as producer
    receipt = build(Path(src), Path(out), expected_week_sha256=week, clip_source_sha256=clip)
    receipt["pluginImplementationSha256"] = {
        name: producer.plugin_implementation_sha256(Path(out).resolve() / "plugins" / name)
        for name in ("zh_hans_weekly_15030286.py", "ko_weekly_15030286.py", "es_weekly_15030286.py")}
    (Path(out) / "plugin-variant-receipt.json").write_text(json.dumps(receipt, indent=1) + "\n")
    print(json.dumps(receipt["pluginImplementationSha256"], indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
