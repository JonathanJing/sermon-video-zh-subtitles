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
    # The plugins import their shared rules via ``scripts.language_review_plugins.<module>``,
    # which resolves to the week's file rather than to this directory, so the clip binding would
    # never run. A package marker here lets the variant's own copies win the import.
    (pinned / "__init__.py").write_text("")
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


def activate(pinned_dir: Path) -> None:
    """Make the variant's copies win ``scripts.language_review_plugins`` imports in this process.

    ``scripts`` is a namespace package, so each subpackage has a single ``__path__``; putting the
    variant first is what lets its shared-rules module and own modules be the ones that run."""
    import importlib
    import scripts.language_review_plugins as package
    target = pinned_dir.resolve()
    if hasattr(package, "__path__") and str(target) not in package.__path__:
        package.__path__.insert(0, str(target))
        for name in [n for n in FILES if n != "weekly_15030286_common.py"]:
            module = "scripts.language_review_plugins." + name[:-3]
            importlib.invalidate_caches()
            sys.modules.pop(module, None)
    sys.modules.pop("scripts.language_review_plugins.weekly_15030286_common", None)


def checked_import(pinned_dir: Path, clip_source_sha256: str) -> dict:
    """Prove that running a variant plugin loads the variant's shared rules, not the week's.

    Loading a plugin by path makes Python resolve its ``from ... import`` statements through the
    package name, so a plain copy silently keeps executing the week's rules (which is how the
    clip binding appeared to be ignored). This raises instead of returning a false pass."""
    import runpy
    activate(pinned_dir)
    runpy.run_path(str(pinned_dir / "zh_hans_weekly_15030286.py"))
    from scripts.language_review_plugins import weekly_15030286_common as loaded
    resolved = Path(getattr(loaded, "__file__", "")).resolve()
    expected = (pinned_dir / "weekly_15030286_common.py").resolve()
    if resolved != expected:
        raise SystemExit(f"the variant's shared rules did not win the import: {resolved} != {expected}")
    if getattr(loaded, "SOURCE_SHA256", None) != clip_source_sha256:
        raise SystemExit("the loaded shared rules still carry the week's source binding")
    return {"module": str(resolved), "SOURCE_SHA256": loaded.SOURCE_SHA256}


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
    resolved = checked_import(Path(out).resolve() / "plugins", clip)
    receipt["resolvedSharedRules"] = resolved
    (Path(out) / "plugin-variant-receipt.json").write_text(json.dumps(receipt, indent=1) + "\n")
    print(json.dumps(receipt["pluginImplementationSha256"], indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
