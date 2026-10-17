#!/usr/bin/env python3
"""Audit one Production v3 page against private, reviewed Layer 3 evidence.

This is a read-only local gate. Reviewed Layer 3 packages contain private
filesystem paths and must never be copied into the Hosting public directory.
The JSON result intentionally contains only public URLs and hashes.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path, PurePosixPath


SHA256 = re.compile(r"^[a-f0-9]{64}$")
LOCALE = re.compile(r"^[a-z]{2,3}(?:-[A-Za-z0-9]{2,8})*$")
APPROVAL_CHECKS = (
    "pronunciation", "naturalness", "completeness", "scripture",
    "voiceIdentity", "synchronization",
)


class BindingAuditError(ValueError):
    """A failed binding; messages never contain private input paths."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise BindingAuditError(message)


def read_object(path: Path, label: str) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as error:
        raise BindingAuditError(f"{label}: missing or invalid JSON") from error
    require(isinstance(value, dict), f"{label}: expected JSON object")
    return value


def file_hash(path: Path, label: str) -> str:
    try:
        digest = hashlib.sha256()
        with path.open("rb") as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()
    except OSError as error:
        raise BindingAuditError(f"{label}: missing or unreadable file") from error


def canonical_hash(value: object) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True,
                         separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def valid_hash(value: object) -> bool:
    return isinstance(value, str) and SHA256.fullmatch(value) is not None


def object_field(value: dict, key: str) -> dict:
    child = value.get(key)
    return child if isinstance(child, dict) else {}


def assignments(values: list[str], label: str) -> dict[str, Path]:
    result: dict[str, Path] = {}
    for assignment in values:
        locale, separator, path = assignment.partition("=")
        require(bool(separator and LOCALE.fullmatch(locale) and path),
                f"{label}: expected LOCALE=PATH")
        require(locale not in result, f"{label}: duplicate locale {locale}")
        result[locale] = Path(path)
    return result


def public_file(public: Path, url: object, expected_url: str, label: str) -> Path:
    require(url == expected_url, f"{label}: unexpected public URL")
    relative = PurePosixPath(expected_url.removeprefix("/"))
    require(expected_url.startswith("/") and ".." not in relative.parts,
            f"{label}: unsafe public URL")
    path = public.joinpath(*relative.parts)
    require(path.resolve().is_relative_to(public.resolve()) and path.is_file(),
            f"{label}: missing or unsafe public file")
    return path


def private_artifact(package: dict, role: str) -> str:
    artifact = package.get(role)
    require(isinstance(artifact, dict) and valid_hash(artifact.get("sha256"))
            and isinstance(artifact.get("path"), str) and artifact["path"],
            f"Layer 3 {role}: invalid artifact receipt")
    require(file_hash(Path(artifact["path"]), f"Layer 3 {role}") == artifact["sha256"],
            f"Layer 3 {role}: local file hash differs")
    return artifact["sha256"]


def audit(public: Path, audio_packages: dict[str, Path],
          audio_receipts: dict[str, Path], spoken_candidates: dict[str, Path],
          spoken_receipts: dict[str, Path], *, page_id: str | None = None) -> dict:
    catalog_path = public / "multilingual-v3.json"
    catalog = read_object(catalog_path, "Production catalog")
    require(catalog.get("schemaVersion") == "sermon-multilingual-catalog-v3",
            "Production catalog: expected v3")
    pages = catalog.get("pages")
    require(isinstance(pages, list) and pages, "Production catalog: missing pages")
    selected_id = page_id or catalog.get("defaultPageId")
    require(isinstance(selected_id, str) and selected_id,
            "Production catalog: missing selected page")
    selected = [page for page in pages if isinstance(page, dict)
                and page.get("id") == selected_id]
    require(len(selected) == 1, "Production catalog: selected page is missing or duplicated")
    page = selected[0]
    source_hash = page.get("sourceIdentitySha256")
    require(page.get("sourceLocale") == "en" and valid_hash(source_hash),
            "Production catalog: invalid English source identity")
    targets = page.get("targets")
    default_locale = page.get("defaultTargetLocale")
    require(isinstance(targets, dict) and targets and
            all(isinstance(locale, str) and LOCALE.fullmatch(locale) for locale in targets),
            "Production catalog: invalid target locales")
    require(default_locale in targets, "Production catalog: invalid default target locale")
    require(set(audio_packages) == set(targets) == set(audio_receipts)
            == set(spoken_candidates) == set(spoken_receipts),
            "Private reviewed inputs must cover every published locale exactly")

    rows = []
    for locale in sorted(targets):
        target = targets[locale]
        require(isinstance(target, dict) and target.get("contentStatus") == "human_reviewed"
                and target.get("audioStatus") == "human_reviewed"
                and isinstance(target.get("capabilities"), list)
                and "audio" in target["capabilities"],
                f"{locale}: catalog does not advertise reviewed audio")
        release_url = f"/releases-v2/{selected_id}/{locale}.json"
        release_path = public_file(public, target.get("releasePackageUrl"),
                                   release_url, f"{locale} release")
        release_hash = file_hash(release_path, f"{locale} release")
        require(valid_hash(target.get("releasePackageJsonSha256"))
                and release_hash == target["releasePackageJsonSha256"],
                f"{locale}: catalog release hash differs")
        release = read_object(release_path, f"{locale} release")
        spoken_hash = release.get("spokenTargetLanguageCandidateJsonSha256")
        full_hash = release.get("targetLanguageCandidateJsonSha256")
        audio_hash = release.get("targetLanguageAudioPackageJsonSha256")
        require(release.get("schemaVersion") == "sermon-target-language-release-package-v2"
                and release.get("pageId") == selected_id
                and release.get("sourceLocale") == "en"
                and release.get("targetLocale") == locale
                and release.get("interfaceLocale") == locale
                and release.get("contentLocale") == locale
                and release.get("audioLocale") == locale
                and release.get("status") == "published_http_verified"
                and object_field(release, "httpVerification").get("status") == "pass"
                and release.get("contentStatus") == "human_reviewed"
                and release.get("audioStatus") == "human_reviewed"
                and release.get("issues") == []
                and valid_hash(spoken_hash) and valid_hash(full_hash)
                and valid_hash(audio_hash),
                f"{locale}: invalid Production release identity or state")

        spoken = read_object(spoken_candidates[locale], f"{locale} private spoken candidate")
        spoken_receipt = read_object(spoken_receipts[locale],
                                     f"{locale} private spoken review receipt")
        groups = spoken.get("groups")
        group_ids = ([group.get("translationGroupId") for group in groups]
                     if isinstance(groups, list) and all(isinstance(group, dict) for group in groups)
                     else [])
        require(spoken.get("schemaVersion") == "sermon-target-language-candidate-v2"
                and canonical_hash(spoken) == spoken_hash
                and spoken.get("sourceLocale") == "en"
                and spoken.get("targetLocale") == locale
                and spoken.get("englishSourcePackageJsonSha256") == source_hash
                and spoken.get("status") == "human_translation_approved"
                and object_field(spoken, "humanReview").get("translation") == "approved"
                and group_ids and len(group_ids) == len(set(group_ids)),
                f"{locale}: approved spoken candidate differs from release")
        require(spoken_receipt.get("schemaVersion") ==
                    "sermon-target-language-human-review-receipt-v1"
                and spoken_receipt.get("decision") == "approved"
                and spoken_receipt.get("targetLocale") == locale
                and spoken_receipt.get("englishSourcePackageJsonSha256") == source_hash
                and spoken_receipt.get("candidateJsonSha256") == spoken_hash
                and spoken_receipt.get("reviewedGroupIds") == group_ids
                and isinstance(spoken_receipt.get("reviewer"), str)
                and bool(spoken_receipt["reviewer"].strip()),
                f"{locale}: spoken human review receipt differs")

        package = read_object(audio_packages[locale], f"{locale} private Layer 3 package")
        receipt = read_object(audio_receipts[locale], f"{locale} private audio receipt")
        require(package.get("schemaVersion") == "sermon-target-language-audio-package-v1"
                and canonical_hash(package) == audio_hash
                and package.get("targetLocale") == locale
                and package.get("englishSourcePackageJsonSha256") == source_hash
                and package.get("targetLanguageCandidateJsonSha256") == spoken_hash
                and package.get("status") == "human_reviewed"
                and object_field(package, "humanReview").get("status") == "approved"
                and object_field(package, "humanReview").get("humanApproval") is True
                and object_field(package, "humanReview").get("fullPlayback") == "approved"
                and package.get("issues") == [],
                f"{locale}: reviewed Layer 3 package differs from release")
        units = package.get("units")
        unit_ids = ([unit.get("textGroupId") for unit in units]
                    if isinstance(units, list) and all(isinstance(unit, dict) for unit in units)
                    else [])
        require(unit_ids and all(isinstance(unit_id, str) and unit_id for unit_id in unit_ids)
                and len(unit_ids) == len(set(unit_ids)),
                f"{locale}: invalid reviewed Layer 3 unit coverage")
        track_hash = private_artifact(package, "track")
        captions_hash = private_artifact(package, "captions")
        require(receipt.get("schemaVersion") == "sermon-target-language-audio-human-review-receipt-v2"
                and receipt.get("targetLocale") == locale
                and receipt.get("englishSourcePackageJsonSha256") == source_hash
                and receipt.get("targetLanguageCandidateJsonSha256") == spoken_hash
                and receipt.get("targetLanguageAudioPackageJsonSha256") == audio_hash
                and receipt.get("trackSha256") == track_hash
                and receipt.get("machineScreeningStatus") ==
                    object_field(package, "machineScreening").get("status")
                and receipt.get("decision") == "approved"
                and receipt.get("fullPlayback") == "approved"
                and receipt.get("videoSync1x") == "approved"
                and isinstance(receipt.get("reviewedBy"), str)
                and bool(receipt["reviewedBy"].strip())
                and isinstance(receipt.get("reviewedAt"), str)
                and bool(receipt["reviewedAt"].strip())
                and receipt.get("reviewedUnitIds") == unit_ids
                and receipt.get("checks") == {check: "approved" for check in APPROVAL_CHECKS}
                and receipt.get("issues") == [],
                f"{locale}: human audio review receipt differs")
        adjudications = receipt.get("asrAdjudications")
        require(isinstance(adjudications, list) and
                all(isinstance(item, dict) and item.get("textGroupId") in unit_ids
                    and item.get("decision") == "approved"
                    and isinstance(item.get("evidence"), str) and item["evidence"].strip()
                    for item in adjudications) and
                len({item["textGroupId"] for item in adjudications}) == len(adjudications),
                f"{locale}: unresolved or duplicate ASR adjudication")

        assets = release.get("assets")
        require(isinstance(assets, list) and len(assets) == 4
                and {asset.get("role") for asset in assets if isinstance(asset, dict)}
                == {"page", "content", "audio", "captions"},
                f"{locale}: release asset set differs")
        by_role = {asset["role"]: asset for asset in assets}
        expected = {
            "page": f"/pages/{selected_id}/{locale}/index.html",
            "content": f"/content/{selected_id}/{locale}.json",
            "audio": f"/media/{selected_id}/{locale}.mp3",
            "captions": f"/captions/{selected_id}/{locale}.json",
        }
        for role, expected_url in expected.items():
            asset = by_role[role]
            path = public_file(public, asset.get("path"), expected_url,
                               f"{locale} {role}")
            require(valid_hash(asset.get("sha256"))
                    and file_hash(path, f"{locale} {role}") == asset["sha256"],
                    f"{locale}: published {role} hash differs")
        require(by_role["audio"]["sha256"] == track_hash
                and by_role["captions"]["sha256"] == captions_hash,
                f"{locale}: public audio or captions differ from reviewed Layer 3")
        content = read_object(public / expected["content"].removeprefix("/"),
                              f"{locale} public content")
        require(content.get("englishSourcePackageJsonSha256") == source_hash
                and content.get("targetLanguageCandidateJsonSha256") == full_hash,
                f"{locale}: public full text identity differs")
        if locale == default_locale:
            series, title = content.get("series"), content.get("title")
            require(isinstance(series, str) and bool(series.strip())
                    and isinstance(title, str) and bool(title.strip())
                    and page.get("title") == f"{series} · {title}",
                    f"{locale}: catalog page name must include the approved series and sermon title")
        rows.append({
            "locale": locale, "status": "pass", "releaseUrl": release_url,
            "releaseFileSha256": release_hash,
            "fullCandidateJsonSha256": full_hash,
            "spokenCandidateJsonSha256": spoken_hash,
            "spokenHumanReviewReceiptJsonSha256": canonical_hash(spoken_receipt),
            "reviewedAudioPackageJsonSha256": audio_hash,
            "humanAudioReviewReceiptJsonSha256": canonical_hash(receipt),
            "audioUrl": expected["audio"], "audioSha256": track_hash,
            "captionsUrl": expected["captions"], "captionsSha256": captions_hash,
            "reviewedUnits": len(unit_ids),
        })
    return {"schemaVersion": "sermon-production-release-binding-audit-v1",
            "status": "pass", "pageId": selected_id,
            "catalogFileSha256": file_hash(catalog_path, "Production catalog"),
            "locales": rows}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--public", type=Path, required=True,
                        help="Local Hosting public directory; never uploads files")
    parser.add_argument("--page-id", help="Defaults to catalog.defaultPageId")
    parser.add_argument("--audio-package", action="append", default=[], metavar="LOCALE=PATH")
    parser.add_argument("--audio-review-receipt", action="append", default=[], metavar="LOCALE=PATH")
    parser.add_argument("--spoken-candidate", action="append", default=[], metavar="LOCALE=PATH")
    parser.add_argument("--spoken-review-receipt", action="append", default=[], metavar="LOCALE=PATH")
    args = parser.parse_args()
    try:
        result = audit(args.public,
                       assignments(args.audio_package, "audio package"),
                       assignments(args.audio_review_receipt, "audio review receipt"),
                       assignments(args.spoken_candidate, "spoken candidate"),
                       assignments(args.spoken_review_receipt, "spoken review receipt"),
                       page_id=args.page_id)
    except BindingAuditError as error:
        parser.exit(1, f"binding audit failed: {error}\n")
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
