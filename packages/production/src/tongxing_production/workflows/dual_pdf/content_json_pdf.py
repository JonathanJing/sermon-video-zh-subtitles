"""Render a reading PDF from a published `/content/<pageId>/zh-Hans.json` full text.

The PDF is a convenience export of text that is already published; it does not
create a new release identity. It stays local unless ``--gcs-uri`` names a
private Cloud Storage object, in which case the PDF and its ``.qa.json`` go to
that bucket and both are verified by MD5 before the command reports success.

    .venv/bin/python tools/ops/run.py workflows.dual_pdf.content_json_pdf --page-id <pageId>
    .venv/bin/python tools/ops/run.py workflows.dual_pdf.content_json_pdf --page-id <pageId> \
        --out <pdf> --gcs-uri gs://<bucket>/sundays/<date>/reading-pdf/<pdf>
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import math
import re
import urllib.request
from pathlib import Path

from ...contracts import schemas
from . import mobile_pdf as renderer


DEFAULT_BASE_URL = "https://ai-for-god-sermon-audio.web.app"
LOCALE = "zh-Hans"
REFERENCE_SCHEMA = "sermon-published-english-reference-v1"
# Published full-text schemas; v2 is human_reviewed only, v3 adds machine_checked with a disclosure.
CONTENT_SCHEMAS = {"sermon-full-video-text-content-v2", "sermon-full-video-text-content-v3"}
DURATION_TOLERANCE_SECONDS = 1.0
SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")
# A destination object, not a store prefix: the QA report is written beside it.
GCS_PDF_URI = re.compile(r"gs://([a-z0-9][a-z0-9._-]{1,220})/([^\s]+\.pdf)")
GCS_UPLOAD_SCHEMA = "sermon-reading-pdf-gcs-upload-v1"


def main() -> int:
    args = parse_args()
    base = args.base_url.rstrip("/")
    if args.content:
        raw, origin = args.content.read_bytes(), str(args.content)
    else:
        origin = f"{base}/content/{args.page_id}/{LOCALE}.json"
        raw = fetch(origin)
    content = json.loads(raw)
    check_content(content, args.page_id)
    content_sha = hashlib.sha256(raw).hexdigest()
    reference = reference_raw = reference_origin = None
    if args.english_reference:
        reference_raw, reference_origin = args.english_reference.read_bytes(), str(args.english_reference)
    elif not args.no_english and args.page_id and not has_inline_english(content):
        reference_origin = f"{base}/english-reference/{args.page_id}.json"
        reference_raw = fetch(reference_origin)
    if reference_raw is not None:
        reference = json.loads(reference_raw)
    out = args.out or Path(f"{content['pageId']}-{LOCALE}.pdf")
    out.parent.mkdir(parents=True, exist_ok=True)
    qa = render_content_pdf(
        content,
        out=out,
        include_english=not args.no_english,
        english_reference=reference,
        content_sha256=content_sha,
        include_timecodes=not args.hide_timecodes,
        font_path=args.font_path,
    )
    qa["contentSource"] = origin
    qa["contentSha256"] = content_sha
    qa["pdfSha256"] = hashlib.sha256(out.read_bytes()).hexdigest()
    if reference_raw is not None:
        qa["englishReferenceSource"] = reference_origin
        qa["englishReferenceSha256"] = hashlib.sha256(reference_raw).hexdigest()
    qa_path = out.with_suffix(".qa.json")
    write_qa(qa_path, qa)
    upload = None
    if args.gcs_uri:
        upload = publish_reading_pdf(out, qa, qa_path, uri=args.gcs_uri)
    summary = {"status": "ok", "out": str(out), "qa": str(qa_path), "qaStatus": qa["status"],
               "cueCount": len(content.get("cues", []))}
    if upload:
        summary["gcs"] = upload
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


def render_content_pdf(
    content: dict,
    *,
    out: Path,
    include_english: bool = True,
    english_reference: dict | None = None,
    content_sha256: str | None = None,
    include_timecodes: bool = True,
    font_path: Path | None = None,
) -> dict:
    english = reference_english(english_reference, content, content_sha256) if english_reference else {}
    primary, secondary = content_cues(content, english)
    if not primary:
        raise SystemExit("Content JSON has no cues with text.")
    if include_english and len(secondary) != len(primary):
        raise SystemExit(f"English is missing for {len(primary) - len(secondary)} of {len(primary)} cues; "
                         "pass a matching --english-reference or use --no-english.")
    disclaimer = footer_disclaimer(content)
    footer_font = renderer.register_cjk_font(font_path)
    footer_width = renderer.MOBILE_PAGE_SIZE[0] - renderer.MARGIN_X * 2
    if len(renderer.wrap_text(disclaimer, footer_font, renderer.FOOTER_FONT_SIZE, footer_width)) > renderer.FOOTER_MAX_LINES:
        raise SystemExit("Footer disclosure does not fit; it must be shown in full.")
    series, title = content.get("series"), content.get("title")
    heading = " · ".join(part for part in (series, title) if part) or content.get("pageId") or "Sermon"
    qa = renderer.render_reading_pdf(
        primary,
        secondary_cues=secondary if include_english else None,
        paired_secondary=[cue.text for cue in secondary] if include_english else None,
        out=out,
        title=heading,
        subtitle=content.get("scripture"),
        sermon_date=content.get("date"),
        speaker=content.get("speaker"),
        font_path=font_path,
        include_timecodes=include_timecodes,
        disclaimer=disclaimer,
        subject="Mobile Chinese-English sermon reading edition" if include_english else "Mobile Chinese sermon reading edition",
    )
    qa["contentStatus"] = content.get("status")
    qa["includeEnglish"] = include_english
    qa["includeTimecodes"] = include_timecodes
    qa["font"] = font_identity()
    return qa


def check_content(content: dict, page_id: str | None = None) -> None:
    schema = content.get("schemaVersion")
    if schema not in CONTENT_SCHEMAS:
        raise SystemExit(f"Unsupported content schema {schema!r}; expected one of {sorted(CONTENT_SCHEMAS)}.")
    errors = sorted(schemas.validator(schema).iter_errors(content), key=lambda error: list(error.path))
    if errors:
        raise SystemExit(f"Content does not match {schema}: {errors[0].message}")
    if content["reviewMode"] != "formal":
        raise SystemExit("Simulated-review content cannot be exported as a reading edition.")
    if content.get("targetLocale") != LOCALE:
        raise SystemExit(f"Only {LOCALE} content is supported (the renderer's fonts and metadata are Chinese); "
                         f"got {content.get('targetLocale')!r}.")
    if not SAFE_ID.fullmatch(str(content.get("pageId") or "")) or (page_id and content["pageId"] != page_id):
        raise SystemExit("Content pageId is missing, unsafe or differs from the requested page.")


def font_identity() -> dict:
    selected = dict(renderer.SELECTED_FONT)
    if "path" in selected:
        selected["sha256"] = hashlib.sha256(Path(selected["path"]).read_bytes()).hexdigest()
    return selected


def parse_gcs_pdf_uri(uri: str) -> tuple[str, str]:
    """Split a ``gs://bucket/path/<name>.pdf`` destination into bucket and object name."""
    match = GCS_PDF_URI.fullmatch(uri.strip())
    if not match:
        raise ValueError(f"--gcs-uri must name one gs://bucket/path/<name>.pdf object, got {uri!r}")
    bucket, name = match.group(1), match.group(2)
    if any(segment in ("", ".", "..") for segment in name.split("/")) or len(name.encode()) > 1024:
        raise ValueError(f"--gcs-uri object path is unsafe: {uri!r}")
    return bucket, name


def gcs_pdf_uri_arg(value: str) -> str:
    try:
        parse_gcs_pdf_uri(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc
    return value.strip()


def qa_object_name(object_name: str) -> str:
    """The QA report lands beside the PDF, sharing its stem."""
    return object_name[: -len(".pdf")] + ".qa.json"


def write_qa(path: Path, qa: dict) -> None:
    path.write_text(json.dumps(qa, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def gcs_client(client=None):
    """google-cloud-storage client from Application Default Credentials, imported only when uploading."""
    if client is not None:
        return client
    try:
        from google.cloud import storage
    except ImportError as exc:  # pragma: no cover - depends on the host's packages
        raise SystemExit("--gcs-uri needs google-cloud-storage and Application Default Credentials; "
                         "the PDF and QA report were written locally.") from exc
    return storage.Client()


def require_private_bucket(bucket_name: str, *, client) -> None:
    """Refuse a bucket that could serve sermon text publicly; the weekly evidence store uses this rule."""
    bucket = client.bucket(bucket_name)
    bucket.reload()
    config = bucket.iam_configuration
    problems = []
    if not config.uniform_bucket_level_access_enabled:
        problems.append("uniform bucket-level access is off (per-object ACLs could publish the file)")
    if config.public_access_prevention != "enforced":
        problems.append(f"public access prevention is {config.public_access_prevention!r}, not 'enforced'")
    if problems:
        raise SystemExit(f"refusing to upload to gs://{bucket_name}: " + "; ".join(problems))


def upload_verified(path: Path, *, bucket_name: str, object_name: str, content_type: str, client) -> dict:
    """Upload one file and prove the stored bytes equal the local ones."""
    data = path.read_bytes()
    blob = client.bucket(bucket_name).blob(object_name)
    try:
        blob.upload_from_string(data, content_type=content_type)
        blob.reload()
    except Exception as exc:
        raise SystemExit(f"uploading {path.name} to gs://{bucket_name}/{object_name} failed: {exc}") from exc
    local_md5 = hashlib.md5(data).hexdigest()
    remote_md5 = base64.b64decode(blob.md5_hash or "").hex()
    if remote_md5 != local_md5:
        raise SystemExit(f"gs://{bucket_name}/{object_name} holds different bytes than {path} "
                         f"(remote md5 {remote_md5}, local md5 {local_md5}); treat the upload as failed.")
    return {"uri": f"gs://{bucket_name}/{object_name}", "generation": str(blob.generation),
            "sizeBytes": len(data), "md5Hex": remote_md5,
            "sha256": hashlib.sha256(data).hexdigest(),
            "contentType": blob.content_type or content_type, "verified": True}


def publish_reading_pdf(pdf: Path, qa: dict, qa_path: Path, *, uri: str, client=None) -> dict:
    """Upload the PDF, record that upload in the QA report, then upload the report beside it.

    The PDF goes first so the QA report stored next to it already carries the
    object identity and verified hash of the bytes it describes.
    """
    bucket_name, object_name = parse_gcs_pdf_uri(uri)
    client = gcs_client(client)
    require_private_bucket(bucket_name, client=client)
    pdf_object = upload_verified(pdf, bucket_name=bucket_name, object_name=object_name,
                                 content_type="application/pdf", client=client)
    qa["gcs"] = {"schemaVersion": GCS_UPLOAD_SCHEMA, "pdf": pdf_object}
    write_qa(qa_path, qa)
    qa_object = upload_verified(qa_path, bucket_name=bucket_name, object_name=qa_object_name(object_name),
                                content_type="application/json", client=client)
    return {"schemaVersion": GCS_UPLOAD_SCHEMA, "pdf": pdf_object, "qa": qa_object}


def fetch(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=60) as response:
        return response.read()


def has_inline_english(content: dict) -> bool:
    """True only when every cue with text carries its own English."""
    cues = [cue for cue in content.get("cues", []) if str(cue.get("text") or "").strip()]
    return bool(cues) and all(str(cue.get("source") or "").strip() for cue in cues)


def reference_english(reference: dict, content: dict, content_sha256: str | None) -> dict[str, str]:
    """Map textGroupId to English from a published english-reference bound to this content."""
    if (reference.get("schemaVersion"), reference.get("reviewState")) != (REFERENCE_SCHEMA, "human_approved"):
        raise SystemExit("English reference is not a human-approved published reference.")
    if content.get("englishSourcePackageJsonSha256") and (
            reference.get("sourceIdentitySha256") != content["englishSourcePackageJsonSha256"]):
        raise SystemExit("English reference source identity differs from the content's.")
    target = (reference.get("targets") or {}).get(LOCALE)
    if reference.get("pageId") != content.get("pageId") or not target:
        raise SystemExit("English reference does not cover this page and locale.")
    if content_sha256 and target.get("contentSha256") != content_sha256:
        raise SystemExit("English reference is bound to different content bytes.")
    return {block["textGroupId"]: block["english"] for block in target.get("blocks", [])}


def content_cues(content: dict, english: dict[str, str] | None = None) -> tuple[list, list]:
    """Pair each cue with its English: from the approved reference when one is given, else the cue's own source."""
    primary, secondary = [], []
    limit = content.get("durationSeconds")
    previous_start = 0.0
    for index, cue in enumerate(content.get("cues", [])):
        text = renderer.clean_caption_text(str(cue.get("text") or ""))
        if not text:
            continue
        start_s, end_s = cue.get("start"), cue.get("end")
        if not (is_number(start_s) and is_number(end_s) and 0 <= start_s < end_s
                and (not is_number(limit) or end_s <= limit + DURATION_TOLERANCE_SECONDS)):
            raise SystemExit(f"Cue {index} has missing or invalid timing: start={start_s!r} end={end_s!r}.")
        if start_s < previous_start:
            raise SystemExit(f"Cue {index} starts before the previous cue; cues must be in time order.")
        previous_start = start_s
        start, end = srt_time(start_s), srt_time(end_s)
        primary.append(renderer.Cue(start=start, end=end, text=text))
        raw = english.get(cue.get("textGroupId"), "") if english else cue.get("source")
        source = renderer.clean_caption_text(str(raw or ""))
        if source:  # a cue without English is counted, never borrowed from a neighbour
            secondary.append(renderer.Cue(start=start, end=end, text=source))
    return primary, secondary


def is_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def footer_disclaimer(content: dict) -> str:
    # Machine-checked content carries its own disclosure, which must stay visible.
    disclosure = (content.get("disclosure") or {}).get("text")
    if content.get("status") == "machine_checked" and not (isinstance(disclosure, str) and disclosure.strip()):
        raise SystemExit("Machine-checked content has no disclosure text; refusing to render it unlabeled.")
    base = renderer.COMPACT_DISCLAIMER
    return f"{disclosure} {base}" if disclosure else base


def srt_time(seconds: float) -> str:
    millis = max(0, round(float(seconds) * 1000))
    hours, rest = divmod(millis, 3_600_000)
    minutes, rest = divmod(rest, 60_000)
    secs, millis = divmod(rest, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def page_id_arg(value: str) -> str:
    if not SAFE_ID.fullmatch(value):
        raise argparse.ArgumentTypeError(f"unsafe pageId {value!r}")
    return value


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--content", type=Path, help="Local content JSON file.")
    source.add_argument("--page-id", type=page_id_arg, help="Published pageId to download from --base-url.")
    parser.add_argument("--english-reference", type=Path,
                        help="Local english-reference JSON; with --page-id it is downloaded when cues lack English.")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--out", type=Path, help="Output PDF path (default <pageId>-zh-Hans.pdf).")
    parser.add_argument("--no-english", action="store_true", help="Omit the English source under each paragraph.")
    parser.add_argument("--hide-timecodes", action="store_true")
    parser.add_argument("--font-path", type=Path, help="Optional CJK TTF/TTC/OTF font to embed.")
    parser.add_argument("--gcs-uri", type=gcs_pdf_uri_arg, metavar="gs://BUCKET/PATH/NAME.pdf",
                        help="Also upload the PDF, and its .qa.json beside it, to this private object and "
                             "verify both by MD5. The bucket must keep uniform bucket-level access with "
                             "public access prevention enforced; the command refuses otherwise.")
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(main())
