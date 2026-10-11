#!/usr/bin/env python3
"""Bind and audit private Layer 3 archive media without rewriting source evidence.

``prepare`` creates one new sidecar. ``audit`` performs no writes. Neither mode
reads the original package's media paths, searches for files, fetches media,
decodes audio, grants approval, or changes release/staging eligibility.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat
from typing import Any, Iterator

from jsonschema import Draft202012Validator, FormatChecker

SCHEMA = "sermon-private-media-recovery-manifest-v1"
SCOPE = "layer3_package_artifacts_only"
SCHEMA_ROOT = Path(__file__).resolve().parents[1] / "schemas"
JSON_LIMIT = 32 * 1024 * 1024
IDENTITY_KEYS = (
    "packageId", "targetLocale", "englishSourcePackageJsonSha256",
    "targetLanguageCandidateJsonSha256", "targetLanguageSpeechJobJsonSha256",
    "downstreamInvalidationKey",
)


class AuditError(ValueError):
    """A stable, path-free diagnostic safe to include in a report."""


def require(condition: bool, code: str) -> None:
    if not condition:
        raise AuditError(code)


def json_sha256(value: object) -> str:
    try:
        encoded = json.dumps(value, ensure_ascii=False, sort_keys=True,
                             separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (ValueError, UnicodeError, RecursionError):
        raise AuditError("invalid_json") from None
    return hashlib.sha256(encoded).hexdigest()


def _pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        require(key not in result, "duplicate_json_key")
        result[key] = value
    return result


def parse_object(data: bytes) -> dict[str, Any]:
    def invalid_constant(_value: str) -> None:
        raise AuditError("invalid_json")
    def finite_float(value: str) -> float:
        parsed = float(value)
        require(math.isfinite(parsed), "invalid_json")
        return parsed
    try:
        value = json.loads(data, object_pairs_hook=_pairs,
                           parse_constant=invalid_constant, parse_float=finite_float)
    except (ValueError, UnicodeError, RecursionError) as exc:
        if isinstance(exc, AuditError):
            raise
        raise AuditError("invalid_json") from None
    require(isinstance(value, dict), "expected_json_object")
    return value


def read_object(path: Path) -> tuple[dict[str, Any], dict[str, str]]:
    try:
        with archive_directory(path.parent) as parent_fd:
            descriptor = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                                 dir_fd=parent_fd)
            with os.fdopen(descriptor, "rb") as handle:
                before = os.fstat(handle.fileno())
                require(stat.S_ISREG(before.st_mode), "not_regular_json")
                data = handle.read(JSON_LIMIT + 1)
                after = os.fstat(handle.fileno())
                require((before.st_size, before.st_mtime_ns, before.st_ctime_ns)
                        == (after.st_size, after.st_mtime_ns, after.st_ctime_ns),
                        "json_changed_during_read")
    except OSError:
        raise AuditError("json_unreadable") from None
    require(len(data) <= JSON_LIMIT, "json_too_large")
    value = parse_object(data)
    return value, {"sha256": hashlib.sha256(data).hexdigest(),
                   "jsonSha256": json_sha256(value)}


def validate_schema(value: dict[str, Any], filename: str) -> None:
    schema, _ = read_object(SCHEMA_ROOT / filename)
    if next(Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(value), None):
        # Validator messages can contain private paths, reviewer names or text.
        raise AuditError("schema_invalid")


def load_evidence(package_path: Path, approval_path: Path, *, expected_source: str,
                  expected_locale: str, expected_candidate: str) -> tuple[dict, dict, dict, dict]:
    package, package_hash = read_object(package_path)
    approval, approval_hash = read_object(approval_path)
    validate_schema(package, "sermon-target-language-audio-package-v1.schema.json")
    version = approval.get("schemaVersion")
    require(isinstance(version, str)
            and version in {"sermon-target-language-audio-human-review-receipt-v1",
                        "sermon-target-language-audio-human-review-receipt-v2",
                        "sermon-target-language-audio-human-review-receipt-v3",
                        "sermon-target-language-audio-human-review-receipt-v4"},
            "approval_schema_unsupported")
    validate_schema(approval, f"{version}.schema.json")
    require(package["targetLocale"] == expected_locale, "expected_locale_mismatch")
    require(package["englishSourcePackageJsonSha256"] == expected_source,
            "expected_source_mismatch")
    require(package["targetLanguageCandidateJsonSha256"] == expected_candidate,
            "expected_revision_mismatch")
    identity_payload = {key: value for key, value in package.items()
                        if key != "downstreamInvalidationKey"}
    require(package["downstreamInvalidationKey"] == json_sha256(identity_payload),
            "package_identity_mismatch")
    human = package["humanReview"]
    require(package["status"] == "human_reviewed" and package["issues"] == []
            and human["status"] == "approved" and human["humanApproval"] is True
            and human["fullPlayback"] == "approved", "package_not_human_reviewed")
    require(package["track"] is not None and package["captions"] is not None
            and package["schedule"] is not None and bool(package["units"]),
            "incomplete_audio_package")
    for key in ("targetLocale", "englishSourcePackageJsonSha256",
                "targetLanguageCandidateJsonSha256"):
        require(approval[key] == package[key], "approval_identity_mismatch")
    require(approval["targetLanguageAudioPackageJsonSha256"] == package_hash["jsonSha256"]
            and approval["trackSha256"] == package["track"]["sha256"],
            "approval_package_mismatch")
    unit_ids = [unit["textGroupId"] for unit in package["units"]]
    require(len(set(unit_ids)) == len(unit_ids)
            and approval["reviewedUnitIds"] == unit_ids, "approval_unit_mismatch")
    require(all(approval[key] == human[key] for key in ("reviewedBy", "reviewedAt", "fullPlayback")),
            "approval_review_mismatch")
    if version in {"sermon-target-language-audio-human-review-receipt-v2",
                   "sermon-target-language-audio-human-review-receipt-v3",
                   "sermon-target-language-audio-human-review-receipt-v4"}:
        require(approval["machineScreeningStatus"] == package["machineScreening"]["status"],
                "approval_screening_mismatch")
    if version == "sermon-target-language-audio-human-review-receipt-v4":
        exception = approval["publicationException"]
        require(exception["targetLocale"] == expected_locale
                and exception["englishSourcePackageJsonSha256"] == expected_source
                and exception["targetLanguageCandidateJsonSha256"] == expected_candidate
                and exception["targetLanguageAudioPackageJsonSha256"] == package_hash["jsonSha256"]
                and exception["trackSha256"] == package["track"]["sha256"],
                "publication_exception_identity_mismatch")
    return package, approval, package_hash, approval_hash


def artifact_bindings(package: dict) -> dict[str, dict]:
    result = {f"/units/{index}/audio": unit["audio"]
              for index, unit in enumerate(package["units"])}
    result.update({f"/{key}": package[key] for key in ("track", "captions", "schedule")})
    return result


def checked_relative(value: object, locale: str) -> str:
    require(isinstance(value, str) and bool(value), "unsafe_archive_path")
    require(not any(ord(char) < 32 or ord(char) == 127 for char in value)
            and "\\" not in value and ":" not in value and "%" not in value,
            "unsafe_archive_path")
    parts = value.split("/")
    require(all(part and part not in {".", ".."} for part in parts), "unsafe_archive_path")
    require(len(parts) >= 3 and parts[:2] == ["languages", locale],
            "archive_locale_mismatch")
    return value


@contextmanager
def archive_directory(root: Path) -> Iterator[int]:
    # Walking file descriptors prevents a concurrent directory-symlink swap
    # from redirecting a later media read outside the explicit archive root.
    require(os.name == "posix" and hasattr(os, "O_NOFOLLOW"),
            "secure_archive_open_unsupported")
    descriptor: int | None = None
    try:
        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
        descriptor = os.open("/", flags)
        for part in Path(os.path.abspath(root)).parts[1:]:
            child = os.open(part, flags, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        yield descriptor
    except OSError:
        raise AuditError("archive_root_unavailable_or_symlink") from None
    finally:
        if descriptor is not None:
            os.close(descriptor)


def inspect_artifact(root_fd: int, relative: str, *, json_artifact: bool) -> tuple[dict, tuple[int, int]]:
    descriptor = os.dup(root_fd)
    try:
        parts = relative.split("/")
        for part in parts[:-1]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                            dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        media_fd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                           dir_fd=descriptor)
        with os.fdopen(media_fd, "rb") as handle:
            before = os.fstat(handle.fileno())
            require(stat.S_ISREG(before.st_mode), "artifact_not_regular")
            require(before.st_size > 0, "artifact_empty")
            require(not json_artifact or before.st_size <= JSON_LIMIT, "json_too_large")
            digest = hashlib.sha256()
            payload = bytearray()
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
                if json_artifact:
                    payload.extend(chunk)
                    require(len(payload) <= JSON_LIMIT, "json_too_large")
            after = os.fstat(handle.fileno())
            require((before.st_size, before.st_mtime_ns, before.st_ctime_ns)
                    == (after.st_size, after.st_mtime_ns, after.st_ctime_ns),
                    "artifact_changed_during_read")
            result = {"sha256": digest.hexdigest()}
            if json_artifact:
                result["jsonSha256"] = json_sha256(parse_object(bytes(payload)))
            return result, (after.st_dev, after.st_ino)
    except FileNotFoundError:
        raise AuditError("artifact_missing") from None
    except OSError:
        raise AuditError("artifact_unreadable_or_symlink") from None
    finally:
        os.close(descriptor)


def validate_mapping(rows: object, package: dict, *, manifest: bool) -> list[dict]:
    require(isinstance(rows, list), "mapping_invalid")
    expected = artifact_bindings(package)
    ids: set[str] = set()
    paths: set[str] = set()
    for row in rows:
        require(isinstance(row, dict), "mapping_invalid")
        artifact_id = row.get("artifactId")
        require(isinstance(artifact_id, str) and artifact_id in expected, "mapping_unknown_artifact")
        require(artifact_id not in ids, "mapping_ambiguous_artifact")
        ids.add(artifact_id)
        relative = checked_relative(row.get("archiveRelativePath"), package["targetLocale"])
        require(relative not in paths, "mapping_ambiguous_path")
        paths.add(relative)
        binding = expected[artifact_id]
        hash_keys = {"sha256"} | ({"jsonSha256"} if "jsonSha256" in binding else set())
        allowed = {"artifactId", "archiveRelativePath"} | (hash_keys if manifest else set())
        require(set(row) == allowed, "mapping_fields_mismatch")
        if manifest:
            require(all(row[key] == binding[key] for key in hash_keys), "artifact_identity_mismatch")
    require(ids == set(expected), "mapping_incomplete")
    return rows


def check_media(package: dict, rows: list[dict], archive_root: Path) -> list[dict[str, str]]:
    errors = []
    seen: set[tuple[int, int]] = set()
    bindings = artifact_bindings(package)
    with archive_directory(archive_root) as root_fd:
        for row in rows:
            artifact_id = row["artifactId"]
            binding = bindings[artifact_id]
            try:
                hashes, inode = inspect_artifact(root_fd, row["archiveRelativePath"],
                                                json_artifact="jsonSha256" in binding)
                require(inode not in seen, "mapping_ambiguous_file")
                seen.add(inode)
                require(hashes["sha256"] == binding["sha256"], "artifact_sha256_mismatch")
                if "jsonSha256" in binding:
                    require(hashes["jsonSha256"] == binding["jsonSha256"],
                            "artifact_json_sha256_mismatch")
            except AuditError as exc:
                errors.append({"artifactId": artifact_id, "code": str(exc)})
    return errors


def prepare_manifest(package_path: Path, approval_path: Path, mapping_path: Path,
                     archive_root: Path, *, archive_id: str, expected_source: str,
                     expected_locale: str, expected_candidate: str) -> dict:
    package, _approval, package_hash, approval_hash = load_evidence(
        package_path, approval_path, expected_source=expected_source,
        expected_locale=expected_locale, expected_candidate=expected_candidate)
    require(bool(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,95}", archive_id)),
            "archive_id_invalid")
    mapping, _ = read_object(mapping_path)
    require(set(mapping) == {"artifacts"}, "mapping_invalid")
    rows = validate_mapping(mapping["artifacts"], package, manifest=False)
    require(not check_media(package, rows, archive_root), "archive_media_not_verified")
    bindings = artifact_bindings(package)
    manifest = {
        "schemaVersion": SCHEMA, "scope": SCOPE, "archiveId": archive_id,
        "identity": {key: package[key] for key in IDENTITY_KEYS},
        "originalPackage": package_hash, "approvalReceipt": approval_hash,
        "artifacts": [{**row, **{key: value for key, value in bindings[row["artifactId"]].items()
                                if key in {"sha256", "jsonSha256"}}}
                      for row in sorted(rows, key=lambda row: row["artifactId"])],
    }
    validate_schema(manifest, f"{SCHEMA}.schema.json")
    return manifest


def audit(package_path: Path, approval_path: Path, manifest_path: Path,
          archive_root: Path, *, expected_source: str, expected_locale: str,
          expected_candidate: str) -> dict:
    package, _approval, package_hash, approval_hash = load_evidence(
        package_path, approval_path, expected_source=expected_source,
        expected_locale=expected_locale, expected_candidate=expected_candidate)
    manifest, manifest_hash = read_object(manifest_path)
    validate_schema(manifest, f"{SCHEMA}.schema.json")
    require(manifest["originalPackage"] == package_hash, "original_package_hash_mismatch")
    require(manifest["approvalReceipt"] == approval_hash, "approval_receipt_hash_mismatch")
    require(manifest["identity"] == {key: package[key] for key in IDENTITY_KEYS},
            "manifest_identity_mismatch")
    rows = validate_mapping(manifest["artifacts"], package, manifest=True)
    errors = check_media(package, rows, archive_root)
    return {"schemaVersion": "sermon-private-media-recovery-audit-v1", "scope": SCOPE,
            "status": "blocked" if errors else "verified", "readOnly": True,
            "releaseEligibilityEstablished": False, "artifactCount": len(rows),
            "verifiedArtifactCount": len(rows) - len(errors),
            "manifestSha256": manifest_hash["sha256"], "errors": errors}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for command in ("prepare", "audit"):
        sub = commands.add_parser(command)
        for name in ("package", "approval", "archive-root"):
            sub.add_argument(f"--{name}", type=Path, required=True)
        for name in ("expected-source-sha256", "expected-locale", "expected-candidate-sha256"):
            sub.add_argument(f"--{name}", required=True)
        if command == "prepare":
            sub.add_argument("--mapping", type=Path, required=True)
            sub.add_argument("--archive-id", required=True)
            sub.add_argument("--out", type=Path, required=True,
                             help="New sidecar file only; existing files are never overwritten")
        else:
            sub.add_argument("--manifest", type=Path, required=True)
    args = parser.parse_args(argv)
    expectations = dict(expected_source=args.expected_source_sha256,
                        expected_locale=args.expected_locale,
                        expected_candidate=args.expected_candidate_sha256)
    try:
        if args.command == "prepare":
            manifest = prepare_manifest(args.package, args.approval, args.mapping,
                                        args.archive_root, archive_id=args.archive_id, **expectations)
            try:
                # Exclusive creation also rejects an existing symlink or hard link.
                with args.out.open("x", encoding="utf-8") as handle:
                    handle.write(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
            except OSError:
                raise AuditError("sidecar_output_unavailable_or_exists") from None
            report = {"status": "manifest_created", "scope": SCOPE,
                      "artifactCount": len(manifest["artifacts"]),
                      "releaseEligibilityEstablished": False}
        else:
            report = audit(args.package, args.approval, args.manifest, args.archive_root,
                           **expectations)
    except (AuditError, RecursionError) as exc:
        code = str(exc) if isinstance(exc, AuditError) else "json_nesting_limit"
        report = {"status": "blocked", "scope": SCOPE, "errors": [{"code": code}],
                  "releaseEligibilityEstablished": False}
    print(json.dumps(report, sort_keys=True))
    return 1 if report["status"] == "blocked" else 0


if __name__ == "__main__":
    raise SystemExit(main())
