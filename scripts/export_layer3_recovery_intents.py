#!/usr/bin/env python3
"""Export current formal-producer identities to stdout for read-only recovery planning.

Requires a pre-existing formal lock and explicit complete render settings. This
cache-inspection path validates canonical inputs and declared checkpoint bindings,
but never opens model weights, reads stored intents, dispatches, repairs or releases
an owner. The snapshot is a comparison diagnostic, never synthesis authorization.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import stat
import sys

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts import render_formal_target_language_speech as producer

VERSION = "sermon-l3-recovery-intent-snapshot-v1"


def require(ok, message):
    if not ok:
        raise ValueError(message)


def _unaliased(path):
    path = Path(path).absolute()
    require(not any(p.is_symlink() for p in (path, *path.parents)),
            "Symlinked recovery input/root refused")
    return path


@contextmanager
def read_lock(job_path):
    """Join the producer's lock without creating it or interpreting owner state."""
    job_path = _unaliased(job_path)
    root = job_path.parent
    require(root.is_dir(), "Existing formal render root required")
    root_identity = (root.stat().st_dev, root.stat().st_ino)
    lock_path = _unaliased(root / ".formal-render.lock")
    try:
        fd = os.open(lock_path, os.O_RDONLY | os.O_NOFOLLOW)
    except FileNotFoundError as exc:
        raise ValueError("Existing formal render lock required; exporter never creates one") from exc
    with os.fdopen(fd, "rb") as lock:
        opened = os.fstat(lock.fileno())
        require(stat.S_ISREG(opened.st_mode), "Formal render lock must be a regular file")
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_SH | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ValueError("Formal renderer active; read-only snapshot blocked") from exc

        def check():
            _unaliased(job_path)
            _unaliased(lock_path)
            current = lock_path.stat()
            require((current.st_dev, current.st_ino) == (opened.st_dev, opened.st_ino)
                    and (root.stat().st_dev, root.stat().st_ino) == root_identity,
                    "Formal root/lock replaced during export")
        check()
        yield root, check
        check()


def export_snapshot(paths, checkpoint_map_path, operation_policies_path, settings_path,
                    *, strict_rubric_path=None):
    """Validate and regenerate a complete identity set, preserving all prior evidence."""
    paths = {name: _unaliased(path) for name, path in paths.items()}
    checkpoint_map_path = _unaliased(checkpoint_map_path)
    operation_policies_path = _unaliased(operation_policies_path)
    settings_path = _unaliased(settings_path)
    strict_rubric_path = _unaliased(strict_rubric_path) if strict_rubric_path is not None else None
    # Freeze settings before consuming its optional instruction locator.
    initial_settings_sha = producer.identity.sha256(settings_path)
    settings = producer.recovery_render_settings(producer.package.read_object(settings_path))
    instruction_path = (_unaliased(settings["unitInstructions"])
                        if settings["unitInstructions"] is not None else None)
    strict_rubric = producer.package.read_object(strict_rubric_path) if strict_rubric_path else None
    implementation_paths = [Path(producer.__file__).resolve(), Path(__file__).resolve(),
        Path(producer.replica_pool.__file__).resolve(),
        Path(producer.__file__).resolve().with_name("spark_tts_window_scheduler.py")]
    with read_lock(paths["job"]) as (root, check_lock):
        frozen = producer.integrity.ValidatedJobContext(paths["job"], strict_rubric=strict_rubric,
            extra_paths=[*paths.values(), checkpoint_map_path, operation_policies_path, settings_path,
                         *implementation_paths, *([instruction_path] if instruction_path else []),
                         *([strict_rubric_path] if strict_rubric_path else [])])
        require(frozen.files[settings_path.resolve()][1] == initial_settings_sha,
                "Settings changed before export admission")
        if strict_rubric_path:
            require(producer.identity.json_sha256(producer.package.read_object(strict_rubric_path))
                    == producer.identity.json_sha256(strict_rubric), "Strict rubric changed before admission")
        context = producer.checked_context(paths, checkpoint_map_path, operation_policies_path,
            strict_rubric=strict_rubric, assembly_only=True)
        instructions = producer.unit_instructions(context["job"], instruction_path)
        frozen.check()
        intents = producer.build_expected_intents(context, paths, settings,
            instructions_by_group=instructions if instruction_path else None)
        require(len(intents) == len(frozen.job["units"])
                and {row["unitIndex"] for row in intents} == set(range(len(intents))),
                "Expected intents must cover every formal job unit exactly once")
        require(all(row["jobFileSha256"] == frozen.job_file_sha256
                    and row["jobJsonSha256"] == frozen.job_json_sha256 for row in intents),
                "Expected intents differ from frozen formal job")
        frozen.check(full=True)
        check_lock()
        return {"schemaVersion": VERSION, "jobJsonSha256": frozen.job_json_sha256,
            "jobFileSha256": frozen.job_file_sha256, "renderRoot": str(root),
            "settings": settings, "settingsFileSha256": initial_settings_sha,
            "producerFileSha256": frozen.files[implementation_paths[0]][1],
            "inputBindings": [{"path": str(path), "sha256": digest}
                              for path, (_, digest) in sorted(frozen.files.items())],
            "validation": {"mode": "cache_inspection", "canonicalInputsValidated": True,
                "checkpointDeclaredIdentityValidated": True, "checkpointWeightsVerified": False,
                "formalLock": "existing_shared_lock", "completeCoverage": True,
                "unitCount": len(intents), "modelCalls": 0, "cacheWrites": 0,
                "storedIntentsConsumed": False, "dispatchAuthorized": False,
                "ownerReconciled": False, "resourceReleaseAuthorized": False,
                "crossVersionMigrationImplemented": False},
            "intents": intents}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("source", "anchor", "candidate", "job", "adapter", "policy"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    parser.add_argument("--human-review-receipt", dest="human_receipt", type=Path, required=True)
    parser.add_argument("--speaker-registry", dest="registry", type=Path, required=True)
    authorization = parser.add_mutually_exclusive_group(required=True)
    authorization.add_argument("--clip-voice-authorization", dest="clip_voice_authorization", type=Path)
    authorization.add_argument("--source-voice-authorization", dest="source_voice_authorization", type=Path)
    parser.add_argument("--clip-voice-capability", dest="clip_voice_capability", type=Path)
    parser.add_argument("--clip-timeline-map", dest="clip_timeline_map", type=Path, required=True)
    parser.add_argument("--anchor-exception-receipt", type=Path,
                        help="Existing source/anchor/locale/candidate-bound exception; never creates approval")
    parser.add_argument("--checkpoint-map", type=Path, required=True)
    parser.add_argument("--audio-operation-policies", type=Path, required=True)
    parser.add_argument("--settings", type=Path, required=True,
                        help="Complete sermon-l3-recovery-render-settings-v1 JSON; no inferred defaults")
    parser.add_argument("--strict-rubric", type=Path)
    args = parser.parse_args(argv)
    keys = ("source", "anchor", "candidate", "job", "adapter", "policy", "human_receipt",
            "registry", "clip_voice_authorization", "source_voice_authorization",
            "clip_voice_capability", "clip_timeline_map", "anchor_exception_receipt")
    paths = {key: getattr(args, key) for key in keys if getattr(args, key) is not None}
    result = export_snapshot(paths, args.checkpoint_map, args.audio_operation_policies, args.settings,
                             strict_rubric_path=args.strict_rubric)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
