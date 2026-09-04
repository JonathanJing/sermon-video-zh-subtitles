from __future__ import annotations

import argparse
import json
from pathlib import Path

from .content_pack import build_weekly_pack, read_jsonl, sha256_file, write_pack


def parser() -> argparse.ArgumentParser:
    command = argparse.ArgumentParser(description="Build a guarded Weekly Pack from Saturday caption JSONL.")
    command.add_argument("--segments", required=True, help="JSONL containing Saturday English/Chinese segments")
    command.add_argument("--service-date", required=True, help="Saturday service date as YYYY-MM-DD")
    command.add_argument("--source-id", required=True, help="Stable livestream or recording identifier")
    audio = command.add_mutually_exclusive_group(required=True)
    audio.add_argument("--audio", help="Source audio file; SHA-256 is calculated")
    audio.add_argument("--audio-sha256", help="Already-calculated source audio SHA-256")
    command.add_argument("--valid-until", required=True, help="Last eligible date as YYYY-MM-DD")
    command.add_argument("--output", required=True, help="Destination weekly-pack.json")
    return command


def main() -> None:
    arguments = parser().parse_args()
    audio_sha256 = sha256_file(arguments.audio) if arguments.audio else arguments.audio_sha256
    segments = read_jsonl(arguments.segments)
    pack = build_weekly_pack(
        segments,
        service_date=arguments.service_date,
        source_id=arguments.source_id,
        audio_sha256=audio_sha256,
        valid_until=arguments.valid_until,
    )
    write_pack(pack, arguments.output)
    print(json.dumps({
        "output": str(Path(arguments.output).resolve()),
        "packVersion": pack["packVersion"],
        "segmentCount": pack["provenance"]["segmentCount"],
        "machineTranslationInjectable": pack["policy"]["machineTranslationInjectable"],
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
