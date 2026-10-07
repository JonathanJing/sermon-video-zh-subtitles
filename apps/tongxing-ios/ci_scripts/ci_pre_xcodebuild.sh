#!/bin/sh
# Source admission only: Xcode Cloud owns xcodebuild and its real exit status.
set -eu
case "${CI_XCODEBUILD_ACTION-}" in
    build|analyze|build-for-testing|test-without-building)
        exit 0
        ;;
    archive)
        script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
        exec python3 "$script_dir/validate_archive_intent.py"
        ;;
    *)
        echo 'error: archive admission blocked: missing or unsupported CI_XCODEBUILD_ACTION' >&2
        exit 1
        ;;
esac
