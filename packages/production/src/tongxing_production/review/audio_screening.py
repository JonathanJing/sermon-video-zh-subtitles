"""The Layer 3 audio screening review gate.

A reviewed audio package is accepted for release only with one of: a machine
listening waiver (never a human approval of the track), a human review receipt
v1 (ASR passed) or v2 (exact human adjudication of every unit ASR flagged), or
one of the two human publication exceptions (v3: an exact-track Chinese
exception; v4: a locale-bound exception). The waiver rules stay in
machine_audio_waiver_acceptance, outside the waiver implementation closure, and
are reached through the backend; the receipt schemas through ``Schemas``.
"""
from __future__ import annotations

import hashlib
import json

from jsonschema import Draft202012Validator, FormatChecker

from . import backend

# The three locales a locale-bound publication exception (v4) may name.
LOCALES = ("zh-Hans", "ko", "es")


class AudioScreeningError(ValueError):
    """The receipt does not accept this audio package; the message is the rejection reason."""


def _canonical_sha(value: object) -> str:
    data = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(data).hexdigest()


def _schema_errors(receipt: dict, schema_name: str) -> list:
    schema = json.loads(backend.current().schemas.path(schema_name).read_text())
    return list(Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(receipt))


def validate_audio_screening_review(audio: dict, receipt: dict,
                                    screening: dict | None) -> None:
    waivers = backend.current().waivers
    if waivers.is_audio_waiver(receipt):
        # A machine listening waiver (v3: with a person's per-unit acceptance), never a human approval of the track.
        try:
            waivers.validate_audio_waiver(audio, receipt, screening)
        except ValueError as error:
            raise AudioScreeningError(str(error)) from error
        return
    if receipt.get("schemaVersion") == "sermon-target-language-audio-human-review-receipt-v3":
        if (_schema_errors(receipt, "sermon-target-language-audio-human-review-receipt-v3.schema.json")
                or audio["targetLocale"] != "zh-Hans"
                or receipt["publicationException"]["trackSha256"] != audio["track"]["sha256"]):
            raise AudioScreeningError("Invalid exact-track Chinese publication exception")
    elif receipt.get("schemaVersion") == "sermon-target-language-audio-human-review-receipt-v4":
        exception = receipt.get("publicationException", {})
        identities = {"targetLocale": audio["targetLocale"],
                      "englishSourcePackageJsonSha256": audio["englishSourcePackageJsonSha256"],
                      "targetLanguageCandidateJsonSha256": audio["targetLanguageCandidateJsonSha256"],
                      "targetLanguageAudioPackageJsonSha256": _canonical_sha(audio),
                      "trackSha256": audio["track"]["sha256"]}
        if (_schema_errors(receipt, "sermon-target-language-audio-human-review-receipt-v4.schema.json")
                or receipt["targetLocale"] != audio["targetLocale"]
                or audio["targetLocale"] not in LOCALES
                or any(receipt.get(key) != value for key, value in identities.items())
                or any(exception.get(key) != value for key, value in identities.items())):
            raise AudioScreeningError("Invalid locale-bound publication exception v2")
    elif receipt.get("schemaVersion") not in {"sermon-target-language-audio-human-review-receipt-v1", "sermon-target-language-audio-human-review-receipt-v2"}:
        raise AudioScreeningError("Unsupported audio human review receipt")
    status = audio["machineScreening"]["status"]
    if receipt["schemaVersion"] == "sermon-target-language-audio-human-review-receipt-v1":
        if status != "pass":
            raise AudioScreeningError("Unresolved ASR review requires a v2 human adjudication receipt")
        return
    if screening is None:
        raise AudioScreeningError("v2 audio review requires the bound full ASR screening receipt")
    group_ids = [row["textGroupId"] for row in audio["units"]]
    if (status not in {"pass", "requires_review"}
            or receipt["machineScreeningStatus"] != status
            or receipt["machineScreeningReceiptJsonSha256"] != _canonical_sha(screening)
            or screening["status"] != status
            or screening["model"] != audio["machineScreening"]["model"]
            or screening["targetLocale"] != audio["targetLocale"]
            or screening["trackSha256"] != audio["track"]["sha256"]
            or screening["targetLanguageSpeechJobJsonSha256"] != audio["targetLanguageSpeechJobJsonSha256"]
            or screening["coverage"] != 1.0
            or screening["reviewedGroupIds"] != group_ids
            or screening["unitAudioSha256s"] != [row["audio"]["sha256"] for row in audio["units"]]
            or len(screening["results"]) != len(group_ids)):
        raise AudioScreeningError("Audio ASR receipt is not bound to the reviewed package")
    queue = []
    for result, unit in zip(screening["results"], audio["units"]):
        if (result["textGroupId"] != unit["textGroupId"]
                or result["targetTextSha256"] != unit["targetTextSha256"]
                or result["audioSha256"] != unit["audio"]["sha256"]):
            raise AudioScreeningError("ASR result differs from reviewed audio unit")
        if result["status"] == "requires_review":
            queue.append(result["textGroupId"])
    if ((status == "pass") != (not queue)
            or [row["textGroupId"] for row in receipt["asrAdjudications"]] != queue
            or any(row["decision"] != "approved" or not row["evidence"].strip()
                   for row in receipt["asrAdjudications"])):
        raise AudioScreeningError("ASR review queue lacks exact human adjudications")
