#!/usr/bin/env python3
"""Dev-only audio entry: consume profile defaults through real producers.

Pass the existing producer's required arguments after the stage. No retries,
model dispatch on merge, approval, deployment or locale orchestration is added.
"""
from __future__ import annotations

import argparse
import sys


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=("tts", "back-asr"))
    parser.add_argument("producer_arguments", nargs=argparse.REMAINDER,
                        help="Existing formal producer arguments; --batch-size may select a baseline/comparison")
    args = parser.parse_args(argv)
    forwarded = list(args.producer_arguments)
    if forwarded[:1] == ["--"]:
        forwarded.pop(0)
    if any(value == "--dev-test" or value.startswith("--dev-test=") for value in forwarded):
        parser.error("Dev mode is already enabled by this entry")
    if args.stage == "tts":
        try:
            from scripts import render_formal_target_language_speech as producer
        except ImportError:
            import render_formal_target_language_speech as producer
    else:
        try:
            from scripts import screen_target_language_audio_units as producer
        except ImportError:
            import screen_target_language_audio_units as producer
    # parse_args in the producer rejects unsupported settings;
    # producer exceptions and exit status propagate without retries.
    producer.main(["--dev-test", *forwarded])


if __name__ == "__main__":
    main(sys.argv[1:])
