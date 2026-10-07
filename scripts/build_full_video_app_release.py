#!/usr/bin/env python3
"""Prepare, verify, and seal the full-text / short-spoken-script App release.

This is a Layer 4 adapter for the 2026-09-27 complete video. It copies approved
bytes and never changes either Layer 2 candidate or the reviewed Layer 3 track.
The existing web page and v1/v2 App catalog remain untouched.

A text or listening gate may also be passed by an exact machine quality waiver.
Such a locale is released as v4 under /releases-v4/ with status machine_checked
and its disclosure; it is never shown as human-reviewed. Seal writes the full
/multilingual-v4.json and its human-only projection /multilingual-v3.json.

A v4 release also says what its dubbed captions display. When the spoken script
was condensed for the dub (``spoken_condensation``), the release binds that
condensation and the captions show the full translation on the dub's timing;
the captions asset itself stays the audio package's spoken-script captions.
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import math
import os
import re
import shutil
import tempfile
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

# Nested v3 validators import the scripts package, including direct CLI runs.
if __package__ in (None, ''):
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

try:
    from scripts import stage_formal_multilingual_dev as stage
    from scripts import build_formal_dev_release_assets as formal_assets
    from scripts.release_asset_io import copy_bound_asset
    from scripts import delivery_contract, study_artifacts
    from scripts import machine_quality_release_basis as machine_basis
except ImportError:
    import stage_formal_multilingual_dev as stage
    import build_formal_dev_release_assets as formal_assets
    from release_asset_io import copy_bound_asset
    import delivery_contract, study_artifacts
    import machine_quality_release_basis as machine_basis


ROOT = Path(__file__).resolve().parents[1]
LOCALES = ("zh-Hans", "ko", "es")
ACCEPT_NOT_RUN = {"status": "not_run", "evidenceSha256": None}
PAGE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,159}$")
RUNTIME_WEB_ROOT = ROOT / 'experiments/sermon-dubbing-poc/web'


def runtime_web_files(root=RUNTIME_WEB_ROOT):
    """Freeze the reader's complete local ES-module import closure."""
    pending = ['app.mjs', 'published-weeks.mjs', 'content-locales.mjs']
    found = set()
    imports = re.compile(r"(?:\bfrom\s*|\bimport\s*(?:\(\s*)?)[\"']([./][^\"']+\.mjs)[\"']")
    root = Path(root).resolve()
    while pending:
        name = pending.pop()
        if name in found:
            continue
        path = (root / name).resolve()
        if not path.is_relative_to(root) or path.suffix != '.mjs' or not path.is_file():
            raise ValueError('Reader module dependency is missing or outside the Web root: ' + name)
        found.add(name)
        for specifier in imports.findall(path.read_text()):
            dependency = (root / specifier.lstrip('/')) if specifier.startswith('/') else path.parent / specifier
            dependency = dependency.resolve()
            if not dependency.is_relative_to(root):
                raise ValueError('Reader dependency escapes Web root')
            pending.append(dependency.relative_to(root).as_posix())
    return tuple(sorted(found))


RUNTIME_WEB_FILES = runtime_web_files()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def digest(path: Path) -> str:
    return stage.file_sha(path)


def read(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    require(isinstance(value, dict), f"Expected JSON object: {path}")
    return value


def write(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
                    encoding="utf-8")


def validate(value: dict, schema: str) -> None:
    definition = read(ROOT / "schemas" / schema)
    problems = list(Draft202012Validator(definition, format_checker=FormatChecker()).iter_errors(value))
    require(not problems, f"{schema}: {problems[0].message if problems else ''}")


def reviewed_candidate(path: Path, source_sha: str, locale: str) -> tuple[dict, str]:
    candidate = stage.read_package(path, "sermon-target-language-candidate-v2.schema.json")
    require(stage.reviewed_candidate(candidate)
            and candidate["targetLocale"] == locale
            and candidate["englishSourcePackageJsonSha256"] == source_sha,
            f"{locale}: candidate is not approved for this source")
    return candidate, stage.canonical_sha(candidate)


def admitted_text(candidate_path: Path, receipt_path: Path, source_sha: str, locale: str, *,
                  spoken: bool = False) -> tuple[dict, str, dict]:
    """A candidate admitted by an exact human review or an exact machine quality waiver.

    Returns the candidate, its hash and its review basis. A waiver keeps the
    candidate human-review pending; it is never recorded as a human approval.
    A waiver for a script condensed for dubbing admits only the ``spoken`` role.
    """
    receipt = read(receipt_path)
    if not machine_basis.is_text_waiver(receipt):
        candidate, candidate_sha = reviewed_candidate(candidate_path, source_sha, locale)
        checked_review(receipt_path, candidate, candidate_sha, locale)
        return candidate, candidate_sha, {"kind": "human_review", "receiptSha256": stage.canonical_sha(receipt)}
    candidate = stage.read_package(candidate_path, "sermon-target-language-candidate-v2.schema.json")
    require(candidate["targetLocale"] == locale and candidate["englishSourcePackageJsonSha256"] == source_sha,
            f"{locale}: candidate is not for this source")
    machine_basis.validate_text_waiver(receipt, candidate=candidate, source_sha=source_sha)
    require(spoken or not receipt["condensedGroupIds"],
            f"{locale}: a script condensed for dubbing cannot be the full text")
    return (candidate, stage.canonical_sha(candidate),
            {"kind": "machine_quality_waiver", "receiptSha256": stage.canonical_sha(receipt)})


def caption_text(full: dict, full_sha: str, spoken: dict, spoken_sha: str, spoken_receipt: dict,
                 binding_path: Path | None, locale: str) -> tuple[str, dict | None]:
    """What the dubbed captions display, and the condensation that lets them show the full text.

    Captions keep the dub's timing. They show the full translation when the
    spoken script equals it, or when it differs only in the groups a passing
    condensation binding condensed from this exact full candidate. A spoken
    script shortened any other way keeps showing its own text.
    """
    differing = [spoken_group["translationGroupId"]
                 for full_group, spoken_group in zip(full["groups"], spoken["groups"])
                 if full_group["targetText"] != spoken_group["targetText"]]
    condensed = (list(spoken_receipt.get("condensedGroupIds") or [])
                 if machine_basis.is_text_waiver(spoken_receipt) else [])
    if not condensed:
        require(binding_path is None, f"{locale}: condensation binding given for a spoken script without condensed groups")
        return ("full_text" if not differing else "spoken_text"), None
    require(binding_path is not None, f"{locale}: condensed spoken script needs its condensation binding")
    binding = read(binding_path)
    binding_sha = stage.canonical_sha(binding)
    require(binding_sha == spoken_receipt.get("condensationBindingJsonSha256")
            and binding.get("schemaVersion") == machine_basis.CONDENSATION_BINDING_SCHEMA
            and binding.get("status") == "pass" and not binding.get("issues")
            and binding.get("humanApproval") is False and binding.get("targetLocale") == locale
            and binding.get("fullCandidateJsonSha256") == full_sha
            and binding.get("spokenCandidateJsonSha256") == spoken_sha
            and [row.get("translationGroupId") for row in binding.get("groups", [])] == condensed
            and differing == condensed,
            f"{locale}: condensation binding does not bind this full and spoken script")
    return "full_text", {"condensationRecordJsonSha256": binding.get("condensationRecordJsonSha256"),
                         "condensationBindingJsonSha256": binding_sha, "condensedGroupIds": condensed}


def release_statuses(bases: dict) -> tuple[str, str]:
    """Content follows the full text; audio is human only when its script and track both are."""
    waived = {name for name, basis in bases.items() if basis["kind"] == "machine_quality_waiver"}
    content = "machine_checked" if "fullText" in waived else "human_reviewed"
    audio = "machine_checked" if waived & {"spokenText", "audio"} else "human_reviewed"
    return content, audio


def checked_review(path: Path, candidate: dict, candidate_sha: str, locale: str) -> None:
    receipt = stage.read_package(path, "sermon-target-language-human-review-receipt-v1.schema.json")
    require(receipt["decision"] == "approved"
            and receipt["targetLocale"] == locale
            and receipt["englishSourcePackageJsonSha256"] == candidate["englishSourcePackageJsonSha256"]
            and receipt["candidateJsonSha256"] == candidate_sha
            and receipt["reviewedGroupIds"] == [g["translationGroupId"] for g in candidate["groups"]]
            and [row["translationGroupId"] for row in receipt["groupReviews"]]
                == [g["translationGroupId"] for g in candidate["groups"]]
            and all(row["decision"] == "approved" for row in receipt["groupReviews"]),
            f"{locale}: independent candidate review receipt differs")


MACHINE_FOOTERS = {
    ("human_reviewed", "machine_checked"): '根据讲道视频制作的已审核译文；配音使用的短口播稿与音轨经机器质检后自动发布，未经人工审核。',
    ("machine_checked", "human_reviewed"): '根据讲道视频制作的机器质检译文，未经人工审核；配音另使用已审核短口播稿。',
    ("machine_checked", "machine_checked"): '根据讲道视频制作的机器质检译文；译文与配音均经机器质检后自动发布，未经人工审核。',
}
# A condensed dub is always machine checked; its captions show the full translation.
CONDENSED_FOOTERS = {
    "human_reviewed": '根据讲道视频制作的已审核译文；配音为同传式精简口播，经机器质检后自动发布，未经人工审核；配音字幕显示完整译文。',
    "machine_checked": '根据讲道视频制作的机器质检译文；配音为同传式精简口播，译文与配音均经机器质检后自动发布，未经人工审核；配音字幕显示完整译文。',
}


def static_page(content: dict, locale: str, page_id: str, studies=None, *,
                audio_status: str = "human_reviewed", disclosure: dict | None = None,
                condensed: bool = False) -> str:
    esc = html.escape
    simulated = content.get('reviewMode') == 'simulation'
    machine_text = content.get('status') == 'machine_checked'
    statuses = ('machine_checked' if machine_text else 'human_reviewed', audio_status)
    require((disclosure is not None) == ('machine_checked' in statuses) and not (simulated and disclosure),
            'Machine-checked page needs exactly its disclosure')
    reading_label = ('模拟审核测试文稿；非正式内容批准' if simulated
                     else '机器质检完整文稿；未经人工审核' if machine_text else '已批准完整文稿')
    reading_notice = ('模拟审核测试文稿；不代表正式内容批准。' if simulated
                      else '此处为机器质检后自动发布的完整阅读稿，未经人工审核。' if machine_text
                      else '此处为已批准完整阅读稿。')
    require(not condensed or audio_status == 'machine_checked', 'A condensed dub is machine checked')
    footer_notice = ('模拟审核收据仅用于测试；译文、音轨、大纲与默想未获正式批准。' if simulated
                     else CONDENSED_FOOTERS[statuses[0]] if condensed
                     else MACHINE_FOOTERS.get(statuses, '根据讲道视频制作的已审核译文；配音另使用已审核短口播稿。'))
    disclosure_html = (f'<p role="note" lang="{esc(disclosure["locale"])}"><strong>机器质检</strong> · '
                       f'{esc(disclosure["text"])}</p>' if disclosure else '')
    total_seconds = int(content["durationSeconds"])
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    duration = (f"{hours}:{minutes:02d}:{seconds:02d}" if hours
                else f"{minutes}:{seconds:02d}")
    outlines = "".join(
        f"<li>{esc(item if isinstance(item, str) else item['title'] + ': ' + item['body'])}</li>"
        for item in content["outline"])
    paragraphs = "".join(
        f"<p id=\"cue-{index}\" data-start=\"{cue['start']}\">{esc(cue['text'])}</p>"
        for index, cue in enumerate(content["cues"], 1))
    study_html = ""
    if studies:
        labels = {'zh-Hans': ('大纲', '默想'), 'ko': ('설교 개요', '묵상'), 'es': ('Bosquejo', 'Meditación')}[locale]
        study_html = ''.join(
            f'<section id="study-{kind}" aria-label="{esc(label)}"><h2>{esc(label)}</h2>'
            + ''.join(f'<article><h3>{esc(section["title"])}</h3><p style="white-space:pre-wrap">{esc(section["body"])}</p></article>'
                      for section in studies[kind]['sections']) + '</section>'
            for kind, label in zip(('outline', 'meditation'), labels))
        # Independently reviewed outline replaces metadata's legacy outline.
        outlines = ''
    return ("<!doctype html>\n"
            f"<html lang=\"{esc(locale)}\"><head><meta charset=\"utf-8\">"
            "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
            f"<title>{esc(content['title'])}</title>"
            "<style>body{font:1.12rem/1.75 -apple-system,BlinkMacSystemFont,Arial,sans-serif;"
            "max-width:48rem;margin:auto;padding:1.25rem;color:#1b2430;background:#fff}"
            "h1{line-height:1.25}a{color:#145f9e}main p{margin:0 0 1.1em}"
            "header,aside{border-bottom:1px solid #ccd2d8;padding-bottom:1rem;margin-bottom:1.5rem}"
            "small{color:#52606d}</style></head><body>"
            f"<header><small>{esc(content['series'])} · {esc(content['speaker'])}</small>"
            f"<h1>{esc(content['title'])}</h1><p>{esc(content['scripture'])}</p>"
            f"<p>对应完整 {duration} 讲道视频；{reading_notice}</p>{disclosure_html}</header>"
            f"<aside><p>{esc(content['summary'])}</p><ol>{outlines}</ol></aside>"
            f"<main aria-label=\"{reading_label}\">{paragraphs}</main>"
            + study_html +
            f"<footer><small>{footer_notice}"
            "来源：Mariners Church 视频；本项目与该教会无隶属关系。</small></footer>"
            "</body></html>\n")


def asset(public: Path, role: str, path: str) -> dict:
    local = public / path.lstrip("/")
    require(local.is_file() and not local.is_symlink(), f"Missing release asset: {path}")
    return {"role": role, "path": path, "sha256": digest(local)}


def assignment_map(values, locales):
    result = {}
    for value in values:
        locale, separator, path = value.partition("=")
        require(separator and locale in locales and locale not in result and path, "Invalid locale assignment")
        result[locale] = Path(path)
    require(set(result) == set(locales), "Input locale assignments differ from release scope")
    return result


def partial_assignment_map(values, locales):
    """Optional per-locale inputs: any subset of the release scope."""
    scope = [value.partition("=")[0] for value in values]
    require(set(scope) <= set(locales), "Input locale assignments differ from release scope")
    return assignment_map(values, scope)


def prepare(args: argparse.Namespace) -> dict:
    require(PAGE_ID.fullmatch(args.page_id) is not None, "Unsafe page ID")
    require(not args.out.exists(), "Output already exists")
    source = stage.read_package(args.source, "sermon-english-source-package-v1.schema.json")
    require(source["status"] == "ready_for_translation", "English source is not approved")
    source_sha = stage.canonical_sha(source)
    locales = tuple(getattr(args, "locales", None) or LOCALES)
    require(bool(locales) and len(locales) == len(set(locales))
            and set(locales) <= set(LOCALES), "Release locales must be a nonempty unique supported subset")
    if getattr(args, "source_date_label", False):
        require(locales == ("zh-Hans",), "Date-only metadata is Chinese-only")
        metadata = {"schemaVersion": "sermon-source-date-label-v1", "date": args.date,
                    "pageId": args.page_id, "locales": {"zh-Hans": {
                        "series": "每周证道", "title": args.date + " 证道", "speaker": "讲员信息待补充",
                        "scripture": "经文见全文", "summary": "中文文稿及配音已审核；视频同步未单独验收。", "outline": []}}}
    else:
        require(args.metadata_approval and args.metadata_proposal, "Approved metadata is required")
        metadata = formal_assets.checked_metadata(args.metadata_approval, args.metadata_proposal,
                                                  args.page_id, args.date, locales,
                                                  release_intent=read(args.release_intent) if getattr(args, "release_intent", None) else None)
    if getattr(args, "release_intent", None):
        delivery_contract.validate_intent(read(args.release_intent), read(args.routes))
        for fields in metadata["locales"].values():
            delivery_contract.validate_metadata(fields)
    study_maps = {name: assignment_map(getattr(args, name, []), locales) if getattr(args, name, []) else {}
                  for name in ("outline", "outline_review", "meditation", "meditation_review")}
    require_study = getattr(args, "require_study", False)
    maps = {name: assignment_map(getattr(args, name), locales)
            for name in ("full_candidate", "full_review_receipt", "spoken_candidate",
                         "spoken_review_receipt", "audio_package", "audio_review_receipt",
                         "audio_screening_receipt", "full_content")}
    condensation_maps = partial_assignment_map(getattr(args, "condensation_binding", None) or [], locales)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    scratch = Path(tempfile.mkdtemp(prefix=f".{args.out.name}-", dir=args.out.parent))
    try:
        public = scratch / "public"
        releases = {}
        for locale in locales:
            full, full_sha, full_basis = admitted_text(maps["full_candidate"][locale],
                                                       maps["full_review_receipt"][locale], source_sha, locale)
            spoken, spoken_sha, spoken_basis = admitted_text(maps["spoken_candidate"][locale],
                                                             maps["spoken_review_receipt"][locale], source_sha, locale,
                                                             spoken=True)
            require([g["sourceUnitIds"] for g in full["groups"]]
                    == [g["sourceUnitIds"] for g in spoken["groups"]],
                    f"{locale}: full and spoken scripts cover different source units")
            audio_path = maps["audio_package"][locale]
            audio = stage.read_package(audio_path, "sermon-target-language-audio-package-v1.schema.json")
            audio_sha = stage.canonical_sha(audio)
            audio_receipt_path = maps["audio_review_receipt"][locale]
            receipt_schema = read(audio_receipt_path)["schemaVersion"] + ".schema.json"
            audio_receipt = stage.read_package(audio_receipt_path, receipt_schema)
            audio_waived = machine_basis.is_audio_waiver(audio_receipt)
            require(audio["targetLocale"] == locale
                    and audio["englishSourcePackageJsonSha256"] == source_sha
                    and audio["targetLanguageCandidateJsonSha256"] == spoken_sha
                    and not audio["issues"] and audio["track"] and audio["captions"]
                    and (audio_waived or (audio["status"] == "human_reviewed"
                                          and audio["humanReview"]["humanApproval"] is True
                                          and audio["humanReview"]["fullPlayback"] == "approved")),
                    f"{locale}: reviewed track does not bind approved spoken script")
            # The audio waiver is issued against the spoken script's own text waiver.
            require(not audio_waived or (spoken_basis["kind"] == "machine_quality_waiver"
                                         and audio_receipt["textWaiverJsonSha256"] == spoken_basis["receiptSha256"]),
                    f"{locale}: audio waiver does not bind the spoken script's text waiver")
            screening = stage.read_package(maps["audio_screening_receipt"][locale],
                                           "sermon-target-language-audio-screening-v1.schema.json")
            stage.validate_audio_screening_review(audio, audio_receipt, screening)
            bases = {"fullText": full_basis, "spokenText": spoken_basis,
                     "audio": {"kind": "machine_quality_waiver" if audio_waived else "human_review",
                               "receiptSha256": stage.canonical_sha(audio_receipt)}}
            content_status, audio_status = release_statuses(bases)
            machine = "machine_checked" in (content_status, audio_status)
            captions_show, condensation = caption_text(full, full_sha, spoken, spoken_sha,
                                                       read(maps["spoken_review_receipt"][locale]),
                                                       condensation_maps.get(locale), locale)
            disclosure = machine_basis.disclosure(locale) if machine else None
            require(not machine or require_study, f"{locale}: machine-checked delivery requires the four-product release")
            require(audio_receipt["targetLanguageAudioPackageJsonSha256"] == audio_sha
                    and audio_receipt["targetLanguageCandidateJsonSha256"] == spoken_sha
                    and audio_receipt["trackSha256"] == audio["track"]["sha256"]
                    and len(audio["units"]) == len(spoken["groups"])
                    and all(unit["textGroupId"] == group["translationGroupId"]
                            and unit["targetTextSha256"] == hashlib.sha256(
                                group["targetText"].encode("utf-8")).hexdigest()
                            for unit, group in zip(audio["units"], spoken["groups"])),
                    f"{locale}: full-listen approval does not bind track")
            track = stage.local_artifact(audio_path, audio["track"], f"{locale} track")
            captions = stage.local_artifact(audio_path, audio["captions"], f"{locale} captions")
            caption_data = read(captions)
            require(len(caption_data.get("cues", [])) == len(spoken["groups"])
                    and all(cue["textGroupId"] == group["translationGroupId"]
                            and cue["text"] == group["targetText"]
                            for cue, group in zip(caption_data["cues"], spoken["groups"])),
                    f"{locale}: captions differ from approved spoken text")
            require(track.suffix == ".mp3", f"{locale}: App track must be MP3")
            content_source = maps["full_content"][locale]
            content_bytes = content_source.read_bytes()
            content_sha = hashlib.sha256(content_bytes).hexdigest()
            content = json.loads(content_bytes)
            audio_duration = None
            clocked = content.get('schemaVersion') in ('sermon-full-video-text-content-v2', 'sermon-full-video-text-content-v3')
            if clocked:
                validate(content, content['schemaVersion'] + '.schema.json')
            if content_status == 'machine_checked':
                require(content.get('schemaVersion') == 'sermon-full-video-text-content-v3'
                        and content.get('disclosure') == disclosure,
                        f'{locale}: machine-checked reading content needs content v3 with its disclosure')
            if clocked or 'audioDurationSeconds' in content:
                declared = content.get('audioDurationSeconds')
                require(isinstance(declared, (int, float)) and not isinstance(declared, bool)
                        and math.isfinite(declared) and 0 < declared <= 86400, 'Invalid declared audio duration')
                audio_duration = stage.decode_audio(track, f'{locale} measured audio clock')
                require(abs(content['audioDurationSeconds'] - audio_duration) <= .05,
                        f'{locale}: declared audio duration differs from measured track')
            if metadata.get('schemaVersion') == 'sermon-dev-simulated-metadata-v1':
                require(content.get('schemaVersion') == 'sermon-full-video-text-content-v2'
                        and content.get('reviewMode') == 'simulation', 'Simulated metadata requires simulated v2 content review mode')
            else:
                require(content.get('reviewMode', 'formal') == 'formal', 'Formal metadata cannot bind simulated content')
            if getattr(args, "release_intent", None):
                # The page and reading cues use source-video time. A natural
                # dubbed track has its own independently decoded duration.
                if audio_duration is None:
                    stage.decode_audio(track, f"{locale} audio integrity")
                window = source["source"]["approvedWindow"]
                delivery_contract.validate_metadata(content, measured_duration=
                    window["endSeconds"] - window["startSeconds"])
            require(content.get("schemaVersion") in ("sermon-full-video-text-content-v1", "sermon-full-video-text-content-v2",
                                                     "sermon-full-video-text-content-v3")
                    and content.get("status") == content_status
                    and content.get("pageId") == args.page_id
                    and content.get("targetLocale") == locale
                    and content.get("englishSourcePackageJsonSha256") == source_sha
                    and content.get("targetLanguageCandidateJsonSha256") == full_sha
                    and len(content.get("cues", [])) == len(full["groups"])
                    and all(cue["textGroupId"] == group["translationGroupId"]
                            and cue["sourceUnitIds"] == group["sourceUnitIds"]
                            and cue["text"] == group["targetText"]
                            for cue, group in zip(content["cues"], full["groups"])),
                    f"{locale}: full reading content differs from approved full text")
            if "sourceWindow" in content:
                original = content["sourceWindow"]
                require(original.get("schemaVersion") == "sermon-original-recording-window-v1"
                        and original.get("mediaSha256") == source["source"]["media"]["sha256"]
                        and original.get("startSeconds") == source["source"]["approvedWindow"]["startSeconds"]
                        and original.get("endSeconds") == source["source"]["approvedWindow"]["endSeconds"],
                        f"{locale}: original recording window differs from approved source")
            require(all(content.get(field) == metadata["locales"][locale][field]
                        for field in ("series", "title", "speaker", "scripture", "summary", "outline")),
                    f"{locale}: display fields differ from approved page metadata")
            page_path = f"/pages/{args.page_id}/{locale}/index.html"
            content_path = f"/content/{args.page_id}/{locale}.json"
            audio_url = f"/media/{args.page_id}/{locale}.mp3"
            captions_url = f"/captions/{args.page_id}/{locale}.json"
            for source_path, public_path, expected_sha in (
                    (content_source, content_path, content_sha),
                    (track, audio_url, audio["track"]["sha256"]),
                    (captions, captions_url, audio["captions"]["sha256"])):
                copy_bound_asset(source_path, public, public_path, expected_sha)
            page_file = public / page_path.lstrip("/")
            page_file.parent.mkdir(parents=True, exist_ok=True)
            page_file.write_text(static_page(content, locale, args.page_id, audio_status=audio_status,
                                             disclosure=disclosure, condensed=condensation is not None),
                                 encoding="utf-8")
            release = {
                "schemaVersion": "sermon-target-language-release-package-v2",
                "packageId": f"{args.page_id}-{locale}-dual-script",
                "pageId": args.page_id, "sourceLocale": "en", "targetLocale": locale,
                "targetLanguageCandidateJsonSha256": full_sha,
                "spokenTargetLanguageCandidateJsonSha256": spoken_sha,
                "targetLanguageAudioPackageJsonSha256": audio_sha,
                "status": "candidate", "contentStatus": content_status,
                "audioStatus": audio_status, "interfaceLocale": locale,
                "contentLocale": locale, "audioLocale": locale,
                "assets": [asset(public, role, path) for role, path in (
                    ("page", page_path), ("content", content_path),
                    ("audio", audio_url), ("captions", captions_url))],
                "httpVerification": ACCEPT_NOT_RUN.copy(),
                "deviceAcceptance": ACCEPT_NOT_RUN.copy(),
                "venueAcceptance": ACCEPT_NOT_RUN.copy(), "issues": [],
            }
            release_path = public / f"releases-v2/{args.page_id}/{locale}.json"
            if require_study:
                required_study = ("outline", "outline_review", "meditation", "meditation_review")
                require(all(locale in study_maps[name] for name in required_study),
                        f"{locale}: independent outline and meditation approvals required")
                study = {name: read(study_maps[name][locale]) for name in required_study}
                for kind in ("outline", "meditation"):
                    require(study[kind]["pageId"] == args.page_id and study[kind]["locale"] == locale,
                            "Study page/locale differs")
                    known_units = {unit for group in full["groups"] for unit in group["sourceUnitIds"]}
                    require(all(set(section["sourceUnitIds"]) <= known_units for section in study[kind]["sections"]),
                            "Study references unknown source units")
                joined = study_artifacts.join_artifacts(source_sha=source_sha, text_sha=full_sha,
                                                         audio_sha=audio_sha, **study)
                require(joined["status"] == "complete", "Four-product join incomplete")
                write(scratch / "study" / locale / "join.json", joined)
                for name, value in study.items():
                    write(scratch / "study" / locale / (name + ".json"), value)
                products = {'sourcePackageSha256': source_sha, 'textCandidateSha256': full_sha,
                            'audioPackageSha256': audio_sha,
                            **{kind + 'ArtifactSha256': joined['products'][kind]['artifactSha256'] for kind in ('outline', 'meditation')},
                            **{kind + 'ReviewSha256': joined['products'][kind]['reviewSha256'] for kind in ('outline', 'meditation')},
                            'metadataApprovalSha256': stage.canonical_sha(metadata), 'contentSha256': content_sha,
                            'candidateSha256': delivery_contract.sha({'products': joined['candidateSha256'], 'metadataApproval': stage.canonical_sha(metadata), 'contentSha256': content_sha})}
                release.update(schemaVersion='sermon-target-language-release-package-v3',
                               englishSourcePackageJsonSha256=source_sha, sourceIdentity=delivery_contract.source_identity(source),
                               fourProducts=products)
                if machine:
                    release.update(schemaVersion=delivery_contract.RELEASE_V4, reviewBasis=bases, disclosure=disclosure,
                                   captionText=captions_show, spokenCondensation=condensation)
                    release_path = public / delivery_contract.release_path(release).lstrip("/")
                public_products = {'schemaVersion': 'sermon-public-app-products-v1', 'pageId': args.page_id,
                                   'locale': locale, 'sourceIdentity': release['sourceIdentity'], 'fourProducts': products}
                validate(public_products, 'sermon-public-app-products-v1.schema.json')
                for role, filename, document in [('outline', 'outline', study['outline']), ('meditation', 'meditation', study['meditation']),
                                                 ('product_manifest', 'products', public_products)]:
                    url = f'/study/{args.page_id}/{locale}/{filename}.json'
                    write(public / url.lstrip('/'), document)
                    release['assets'].append(asset(public, role, url))
                page_file.write_text(static_page(content, locale, args.page_id, study, audio_status=audio_status,
                                                 disclosure=disclosure, condensed=condensation is not None),
                                     encoding='utf-8')
                release['assets'][0] = asset(public, 'page', page_path)
                delivery_contract.validate_public_study(release, reader=lambda url: (public / url.lstrip('/')).read_bytes())
            delivery_contract.validate_release_schema(release)
            write(release_path, release)
            releases[locale] = {"releasePath": "/" + str(release_path.relative_to(public)),
                                "releaseSha256": digest(release_path),
                                "fullCandidateSha256": full_sha,
                                "spokenCandidateSha256": spoken_sha,
                                "audioPackageSha256": audio_sha}
            if require_study:
                releases[locale]["studyJoinSha256"] = digest(scratch / "study" / locale / "join.json")
                releases[locale]["appCandidateSha256"] = delivery_contract.sha({"products": joined["candidateSha256"], "metadataApproval": stage.canonical_sha(metadata), "contentSha256": content_sha})
        display_locale = "zh-Hans" if "zh-Hans" in locales else locales[0]
        runtime_assets = []
        if require_study:
            # An overlay must upgrade the existing reader as well as publish v3
            # data. These modules keep legacy v2 pages readable in the baseline.
            for name in RUNTIME_WEB_FILES:
                path = RUNTIME_WEB_ROOT / name
                copy_bound_asset(path, public, '/' + name, digest(path))
                runtime_assets.append(asset(public, 'other', '/' + name))
        manifest = {"schemaVersion": "sermon-dual-script-app-preparation-v1",
                    "status": "candidate_not_deployed", "pageId": args.page_id,
                    "date": args.date, "englishSourcePackageJsonSha256": source_sha,
                    "metadataApprovalJsonSha256": stage.canonical_sha(metadata),
                    "title": read(maps["full_content"][display_locale])["title"],
                    "releases": releases,
                    **({'runtimeAssets': runtime_assets} if require_study else {}),
                    "assets": sorted([asset for locale in locales
                                      for asset in read(public / releases[locale]["releasePath"].lstrip("/"))["assets"]],
                                     key=lambda row: row["path"])}
        write(scratch / "preparation-manifest.json", manifest)
        os.rename(scratch, args.out)
        return manifest
    except Exception:
        shutil.rmtree(scratch)
        raise


def verified_assets(prepared: Path) -> tuple[dict, list[dict]]:
    manifest = read(prepared / "preparation-manifest.json")
    require(manifest.get("schemaVersion") == "sermon-dual-script-app-preparation-v1"
            and manifest.get("status") == "candidate_not_deployed"
            and bool(manifest["releases"])
            and set(manifest["releases"]) <= set(LOCALES), "Invalid preparation manifest")
    public = prepared / "public"
    assets = manifest["assets"]
    expected_count = sum(7 if 'studyJoinSha256' in item else 4 for item in manifest['releases'].values())
    require(len(assets) == expected_count and len({a["path"] for a in assets}) == len(assets),
            "Expected distinct required public assets per locale")
    if any('studyJoinSha256' in item for item in manifest['releases'].values()):
        runtime = manifest.get('runtimeAssets', [])
        require(len(runtime) == len(RUNTIME_WEB_FILES)
                and {row['path'] for row in runtime} == {'/' + name for name in RUNTIME_WEB_FILES},
                'Four-product reader runtime assets required')
        assets = assets + runtime
    for row in assets:
        path = public / row["path"].lstrip("/")
        require(path.is_file() and digest(path) == row["sha256"],
                f"Prepared asset changed: {row['path']}")
    for locale, item in manifest["releases"].items():
        if "studyJoinSha256" in item:
            study_root = prepared / "study" / locale
            require(digest(study_root / "join.json") == item["studyJoinSha256"], "Study join changed")
            study = {name: read(study_root / (name + ".json")) for name in ("outline", "outline_review", "meditation", "meditation_review")}
            joined = study_artifacts.join_artifacts(source_sha=manifest["englishSourcePackageJsonSha256"],
                                                    text_sha=item["fullCandidateSha256"], audio_sha=item["audioPackageSha256"], **study)
            content_asset = next(row for row in assets if row["role"] == "content" and row["path"].endswith("/" + locale + ".json"))
            app_identity = delivery_contract.sha({"products": joined["candidateSha256"], "metadataApproval": manifest["metadataApprovalJsonSha256"], "contentSha256": content_asset["sha256"]})
            require(joined == read(study_root / "join.json") and app_identity == item["appCandidateSha256"], "Study approval changed")
        path = public / item["releasePath"].lstrip("/")
        require(digest(path) == item["releaseSha256"], f"Candidate release changed: {locale}")
        release = read(path)
        delivery_contract.validate_release_schema(release)
        if 'studyJoinSha256' in item:
            public_studies = delivery_contract.validate_public_study(release, reader=lambda url: (public / url.lstrip('/')).read_bytes())
            require(all(public_studies[kind] == study[kind] for kind in ('outline', 'meditation'))
                    and release['fourProducts']['candidateSha256'] == item['appCandidateSha256'], 'Private and public study differ')
            content = read(public / content_asset['path'].lstrip('/'))
            require(content.get('status') == release['contentStatus']
                    and item['releasePath'] == delivery_contract.release_path(release),
                    'Release status or path differs from its content')
            page_asset = next(row for row in release['assets'] if row['role'] == 'page')
            require((public / page_asset['path'].lstrip('/')).read_text()
                    == static_page(content, locale, manifest['pageId'], public_studies,
                                   audio_status=release['audioStatus'], disclosure=release.get('disclosure'),
                                   condensed=bool(release.get('spokenCondensation'))),
                    'Public page does not display approved study')
        require(release["status"] == "candidate"
                and release["httpVerification"] == ACCEPT_NOT_RUN
                and len(release["assets"]) == (7 if 'studyJoinSha256' in item else 4)
                and {(row["role"], row["path"], row["sha256"]) for row in release["assets"]}
                    == {(row["role"], row["path"], row["sha256"]) for row in assets
                        if row in release["assets"]},
                f"Candidate release gate or assets changed: {locale}")
    return manifest, assets


def verify(args: argparse.Namespace) -> dict:
    _, assets = verified_assets(args.prepared)
    require(args.origin.startswith("https://") and args.origin.rstrip("/") == args.origin
            and "/" not in args.origin.removeprefix("https://"), "Origin must be an HTTPS host")
    require(not args.out.exists(), "Verification receipt already exists")
    observed = []
    for row in assets:
        request = urllib.request.Request(args.origin + row["path"],
                                         headers={"User-Agent": "SermonLayer4Verifier/1"})
        with urllib.request.urlopen(request, timeout=120) as response:
            require(response.status == 200, f"HTTP status differs: {row['path']}")
            result = hashlib.sha256()
            total = 0
            while chunk := response.read(1024 * 1024):
                result.update(chunk)
                total += len(chunk)
            require(result.hexdigest() == row["sha256"], f"HTTP SHA-256 differs: {row['path']}")
            observed.append({"path": row["path"], "sha256": result.hexdigest(),
                             "bytes": total, "status": "pass"})
    receipt = {"schemaVersion": "sermon-app-assets-http-verification-v1",
               "status": "pass", "origin": args.origin,
               "verifiedAt": datetime.now(timezone.utc).isoformat(), "assets": observed}
    write(args.out, receipt)
    return receipt


def seal(args: argparse.Namespace) -> dict:
    manifest, assets = verified_assets(args.prepared)
    locales = tuple(manifest["releases"])
    receipt = read(args.http_verification)
    require(receipt.get("schemaVersion") == "sermon-app-assets-http-verification-v1"
            and receipt.get("status") == "pass"
            and isinstance(receipt.get("origin"), str)
            and receipt["origin"].startswith("https://")
            and {(row["path"], row["sha256"]) for row in receipt.get("assets", [])
                 if row.get("status") == "pass"}
                == {(row["path"], row["sha256"]) for row in assets}
            and len(receipt["assets"]) == len(assets),
            "HTTP receipt does not verify exactly the prepared published assets")
    require(not args.out.exists(), "Sealed output already exists")
    scratch = Path(tempfile.mkdtemp(prefix=f".{args.out.name}-", dir=args.out.parent))
    try:
        public = scratch / "public"
        shutil.copytree(args.prepared / "public", public)
        if (args.prepared / "study").exists():
            shutil.copytree(args.prepared / "study", scratch / "study")
        receipt_sha = digest(args.http_verification)
        targets = {}
        source_media_hashes = set()
        for locale in locales:
            url = manifest["releases"][locale]["releasePath"]
            path = public / url.lstrip("/")
            release = read(path)
            release["status"] = "published_http_verified"
            release["httpVerification"] = {"status": "pass", "evidenceSha256": receipt_sha}
            delivery_contract.validate_release_schema(release)
            if release["schemaVersion"] in delivery_contract.FOUR_PRODUCT_RELEASES:
                source_media_hashes.add(release["sourceIdentity"]["mediaSha256"])
            write(path, release)
            targets[locale] = {"releasePackageUrl": url,
                               "releasePackageJsonSha256": digest(path),
                               "contentStatus": release["contentStatus"],
                               "audioStatus": release["audioStatus"],
                               "capabilities": ["text", "captions", "audio"]}
        # v4 carries every target; v3 stays the human-only projection for older clients.
        catalog = {"schemaVersion": delivery_contract.CATALOG_V4,
                   "generatedAt": datetime.now(timezone.utc).isoformat(),
                   "defaultPageId": manifest["pageId"],
                   "pages": [{"id": manifest["pageId"], "date": manifest["date"],
                              "title": manifest["title"],
                              "sourceLocale": "en",
                              "sourceIdentitySha256": manifest["englishSourcePackageJsonSha256"],
                              "defaultTargetLocale": "zh-Hans" if "zh-Hans" in targets else next(locale for locale in LOCALES if locale in targets),
                              "targets": targets}]}
        if source_media_hashes:
            require(len(source_media_hashes) == 1, "Locale source media identities differ")
            catalog["pages"][0]["sourceMediaSha256"] = next(iter(source_media_hashes))
        if getattr(args, "baseline", None):
            require(getattr(args, "release_plan", None), "Incremental release requires a bound plan")
            baseline = delivery_contract.validate_catalog_snapshot(args.baseline)
            plan = read(args.release_plan)
            catalog = delivery_contract.merge_catalog(delivery_contract.snapshot_catalog_v4(args.baseline), catalog, plan,
                                                      anchor=baseline)
            protected_paths = set()
            for old_page in delivery_contract.snapshot_catalog_v4(args.baseline)["pages"]:
                for old_locale, old_target in old_page["targets"].items():
                    if old_page["id"] == plan["pageId"] and old_locale in plan["locales"]:
                        continue
                    old_release_path = old_target["releasePackageUrl"].lstrip("/")
                    protected_paths.add(old_release_path)
                    old_release = read(args.baseline / "public" / old_release_path)
                    protected_paths.update(item["path"].lstrip("/") for item in old_release["assets"])
            replacement_paths = {item["path"].lstrip("/") for item in assets}
            replacement_paths.update(item["releasePath"].lstrip("/") for item in manifest["releases"].values())
            # Preserve the entire verified live snapshot, including older pages and locale assets.
            baseline_report = read(args.baseline / "seal-report.json")
            require(baseline_report["catalogSha256"] == digest(args.baseline / "public/multilingual-v3.json")
                    and (baseline_report.get("catalogV4Sha256") is None
                         or baseline_report["catalogV4Sha256"] == digest(args.baseline / "public/multilingual-v4.json")),
                    "Baseline catalog hash differs")
            for row in baseline_report["files"]:
                relative = Path(row["path"].lstrip("/"))
                require(not relative.is_absolute() and ".." not in relative.parts, "Unsafe baseline path")
                old = args.baseline / "public" / relative
                require(not old.is_symlink() and old.resolve().is_relative_to((args.baseline / "public").resolve()), "Unsafe baseline asset")
                require(digest(old) == row["sha256"] and old.stat().st_size == row["bytes"], "Baseline asset changed")
                target = public / relative
                if not target.exists():
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(old, target)
                elif relative.as_posix() not in delivery_contract.CATALOG_FILES.values():
                    require(digest(target) == row["sha256"] or
                            (relative.as_posix() in replacement_paths and relative.as_posix() not in protected_paths),
                            "Asset collision would damage sibling locale")
        delivery_contract.validate_catalog_schema(catalog)
        human = delivery_contract.validate_catalog_schema(delivery_contract.project_human_catalog(catalog))
        write(public / "multilingual-v4.json", catalog)
        write(public / "multilingual-v3.json", human)
        report = {"schemaVersion": "sermon-dual-script-app-seal-v1",
                  "status": "ready_for_catalog_deployment",
                  "pageId": manifest["pageId"], "origin": receipt["origin"],
                  "httpAssetReceiptSha256": receipt_sha,
                  "catalogSha256": digest(public / "multilingual-v3.json"),
                  "catalogV4Sha256": digest(public / "multilingual-v4.json"),
                  "appCandidateSha256s": {locale: manifest["releases"][locale].get("appCandidateSha256") for locale in locales},
                  "releaseSha256s": {locale: targets[locale]["releasePackageJsonSha256"]
                                    for locale in locales},
                  "files": [{"path": "/" + str(path.relative_to(public)), "sha256": digest(path),
                             "bytes": path.stat().st_size}
                            for path in sorted(public.rglob("*")) if path.is_file()]}
        write(scratch / "seal-report.json", report)
        os.rename(scratch, args.out)
        return report
    except Exception:
        shutil.rmtree(scratch)
        raise


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    prepare_parser = commands.add_parser("prepare")
    prepare_parser.add_argument("--release-intent", type=Path)
    prepare_parser.add_argument("--routes", type=Path)
    prepare_parser.add_argument("--require-study", action="store_true")
    for name in ("outline", "outline-review", "meditation", "meditation-review"):
        prepare_parser.add_argument("--" + name, action="append", default=[], metavar="LOCALE=PATH")
    prepare_parser.add_argument("--source", type=Path, required=True)
    prepare_parser.add_argument("--metadata-approval", type=Path)
    prepare_parser.add_argument("--metadata-proposal", type=Path)
    prepare_parser.add_argument("--locales", nargs="+", choices=LOCALES)
    prepare_parser.add_argument("--source-date-label", action="store_true", help="Use only source date as neutral Chinese display metadata")
    for option in ("full-candidate", "full-review-receipt", "spoken-candidate",
                   "spoken-review-receipt", "audio-package", "audio-review-receipt",
                   "audio-screening-receipt", "full-content"):
        prepare_parser.add_argument("--" + option, action="append", default=[], metavar="LOCALE=PATH")
    prepare_parser.add_argument("--condensation-binding", action="append", default=[], metavar="LOCALE=PATH",
                                help="Passing spoken_condensation binding for a locale whose spoken script was condensed")
    prepare_parser.add_argument("--page-id", required=True)
    prepare_parser.add_argument("--date", required=True)
    prepare_parser.add_argument("--out", type=Path, required=True)
    verify_parser = commands.add_parser("verify")
    verify_parser.add_argument("--prepared", type=Path, required=True)
    verify_parser.add_argument("--origin", required=True)
    verify_parser.add_argument("--out", type=Path, required=True)
    seal_parser = commands.add_parser("seal")
    seal_parser.add_argument("--baseline", type=Path, help="Complete sealed live snapshot")
    seal_parser.add_argument("--release-plan", type=Path)
    seal_parser.add_argument("--prepared", type=Path, required=True)
    seal_parser.add_argument("--http-verification", type=Path, required=True)
    seal_parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    result = {"prepare": prepare, "verify": verify, "seal": seal}[args.command](args)
    print(json.dumps({"status": result["status"], "pageId": result.get("pageId")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
