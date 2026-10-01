#!/usr/bin/env python3
"""Check native symbol coverage, shared SVG bytes and existing web icon references."""
from pathlib import Path
import re
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "experiments/sermon-dubbing-poc/web"
DEV = ROOT / "firebase/dev/public"


def check():
    native = set()
    for folder in ("App", "Shared", "ListeningActivityExtension"):
        for path in (ROOT / "apps/tongxing-ios" / folder).rglob("*.swift"):
            # Covers literal and conditional symbol arguments, including wrapped arguments.
            for expression in re.findall(r"(?:systemName|systemImage):\s*([^\n)]+)", path.read_text()):
                native.update(re.findall(r'"([a-z][a-z0-9.]*)"', expression))
    symbols = [node.attrib["id"] for node in ET.parse(WEB / "icons.svg").getroot()]
    if not native or len(symbols) != len(set(symbols)):
        raise ValueError("Missing native symbols or duplicate SVG IDs")
    missing = native - set(symbols)
    if missing:
        raise ValueError(f"iOS symbols missing SVG drawings: {sorted(missing)}")
    registry = re.search(r"const names = new Set\(\[(.*?)\]\)", (WEB / "icons.mjs").read_text()).group(1)
    if set(re.findall(r"'([^']+)'", registry)) != set(symbols):
        raise ValueError("SVG sprite and runtime registry differ")
    for name in ("icons.svg", "icons.mjs", "brand-icon.svg", "brand-icon-light.svg"):
        if (WEB / name).read_bytes() != (DEV / name).read_bytes():
            raise ValueError(f"Readers use different icon bytes: {name}")
    for path in (WEB / "index.html", DEV / "index.html"):
        for name in re.findall(r'/icons.svg#([^"<>]+)', path.read_text()):
            if name not in symbols:
                raise ValueError(f"Unresolved SVG reference in {path}: {name}")
    if not (DEV / "styles.css").read_bytes().startswith((WEB / "style.css").read_bytes()):
        raise ValueError("Dev reader lost the shared icon CSS prefix")
    print(f"PASS: {len(native)} native symbols covered by {len(symbols)} SVG drawings; both readers synchronized")


if __name__ == "__main__":
    check()
