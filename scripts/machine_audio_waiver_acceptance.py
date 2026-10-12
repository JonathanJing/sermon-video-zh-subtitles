"""Audio waiver v3: a machine listening waiver whose failed units a person accepted.

``machine_quality_release_basis.build_audio_waiver`` refuses any unit the audio
QC failed. This module issues and validates the v3 receipt that additionally
carries a person's per-unit acceptance (``audio_qc_human_acceptance``): the
accepted units keep their QC evidence and are marked ``human_accepted``; every
other unit must still pass exactly as in v2. The receipt stays a machine
waiver (``humanApproval=false``, disclosure shown).

It deliberately lives outside the waiver implementation file set
(``machine_quality_waiver.IMPLEMENTATION_FILES``): the machine rules and the
waivers already issued under them are unchanged; only this consumer of their
evidence is new.
"""
from __future__ import annotations

from scripts import audio_qc_human_acceptance as acceptance_rules
from scripts import machine_quality_release_basis as basis
from scripts import machine_quality_waiver as waiver
from scripts import machine_repair_ledger as ledger
from scripts.machine_quality_release_basis import (_asr_threshold, _machine_screened, _now, _require, _schema,
                                                   calibration_summary, disclosure, json_sha256,
                                                   screening_queue, screening_score_problems,
                                                   source_span_problems, track_check_problems)

SCHEMA = "sermon-target-language-machine-audio-waiver-v3"


def is_audio_waiver_v3(receipt) -> bool:
    return isinstance(receipt, dict) and receipt.get("schemaVersion") == SCHEMA


def is_audio_waiver(receipt) -> bool:
    """Any machine listening waiver, including v3."""
    return basis.is_audio_waiver(receipt) or is_audio_waiver_v3(receipt)


def build_audio_waiver(package: dict, screening: dict, audio_qc: dict, text_waiver: dict,
                       calibration: dict, *, human_acceptance: dict, anchor: dict, candidate: dict,
                       repair_ledger: list[dict], speech_job: dict, track_check: dict | None = None,
                       secondary_asr_model: str | None = None,
                       implementation: str | None = None, created_at: str | None = None) -> dict:
    """Issue a v3 audio waiver: every unit passed audio QC or was accepted by a person for this exact audio."""
    implementation = implementation or waiver.implementation_sha256()
    locale = package.get("targetLocale")
    _require(locale in basis.LOCALES, "Machine waivers cover zh-Hans, ko and es only")
    _require(_machine_screened(package),
             "Audio waiver requires a complete machine-screened package with no human decision")
    _schema(text_waiver, text_waiver.get("schemaVersion") if text_waiver.get("schemaVersion") in basis.TEXT_WAIVER_SCHEMAS
            else basis.TEXT_WAIVER_SCHEMA)
    _require(text_waiver["targetLocale"] == locale
             and text_waiver["candidateJsonSha256"] == package["targetLanguageCandidateJsonSha256"]
             and text_waiver["englishSourcePackageJsonSha256"] == package["englishSourcePackageJsonSha256"]
             and text_waiver["reviewedGroupIds"] == [row["textGroupId"] for row in package["units"]],
             "Audio waiver requires the text waiver of the package's spoken script")
    flagged = set(screening_queue(package, screening))
    by_group = {row["textGroupId"]: row for row in screening["results"]}
    results = audio_qc.get("results") or []
    _require(audio_qc.get("schemaVersion") == "sermon-target-audio-auto-qc-v1"
             and audio_qc.get("locale") == locale and audio_qc.get("humanApproval") is False
             and [row.get("groupId") for row in results] == [row["textGroupId"] for row in package["units"]],
             "Audio QC must cover every package unit in order")
    accepted = acceptance_rules.check(human_acceptance, package=package, audio_qc=audio_qc)
    _require(not audio_qc.get("subtitleOnlyGroupIds")
             and all((row.get("status") == "pass" and row.get("nextAction") == "keep")
                     or row.get("groupId") in accepted for row in results),
             "Every unit must pass audio QC or be accepted by a person; subtitle-only units are not wired yet")
    # Only units that failed this QC and were accepted are marked human_accepted.
    accepted = {row["groupId"] for row in results if row["groupId"] in accepted and row.get("status") != "pass"}
    _require(bool(accepted), "No failed unit is accepted; issue the ordinary v2 waiver instead")
    from scripts.target_audio_auto_qc import THRESHOLDS, screening_asr_settings, transcript_agrees, transcript_similarity
    _require(audio_qc.get("thresholds") == THRESHOLDS,
             "Audio QC thresholds differ from the calibrated release thresholds")
    spans = source_span_problems(anchor, candidate, text_waiver, package, results)
    _require(not spans, "Audio QC source spans are not the frozen ones: " + "; ".join(spans))
    rescored = screening_score_problems(screening, candidate)
    _require(not rescored, "ASR screening does not rescore: " + "; ".join(rescored))
    _require([row.get("sourceUnitIds") for row in results] == [group["sourceUnitIds"] for group in candidate["groups"]],
             "Audio QC counted repairs for other source units")
    repairs = ledger.head_problems(ledger.lineage("audio", locale, package["englishSourcePackageJsonSha256"],
                                                  json_sha256(anchor)), repair_ledger, audio_qc)
    _require(not repairs, "Audio QC is not bound to its repair ledger: " + "; ".join(repairs))
    summary = calibration_summary(calibration, locale, implementation, require_audio=True)
    runtime = waiver.runtime_identity_problems(calibration, audio_qc=audio_qc)
    _require(not runtime, "Audio QC runtime differs from calibration: " + "; ".join(runtime))
    voice = waiver.render_binding_problems(calibration, package, speech_job)
    _require(not voice, "Calibration TTS differs from the package: " + "; ".join(voice))
    inputs = waiver.input_problems(calibration, audio_qc=audio_qc, candidate=candidate,
                                   condensed=bool(text_waiver["condensedGroupIds"]))
    _require(not inputs, "Calibration does not cover this audio: " + "; ".join(inputs))
    track = track_check_problems(package, track_check, implementation)
    _require(not track, "Assembled track is not verified: " + "; ".join(track))
    threshold = _asr_threshold()
    primary_settings = json_sha256(screening_asr_settings(screening))
    texts = {group["translationGroupId"]: group["targetText"] for group in candidate["groups"]}
    secondary_identity = None
    rows = []
    for row, unit in zip(results, package["units"]):
        group_id = unit["textGroupId"]
        primary = by_group[group_id]["similarity"]
        secondary = row.get("asrSecondary")
        _require(row.get("audioSha256") == unit["audio"]["sha256"], f"Audio QC screened different audio: {group_id}")
        _require(row.get("textSha256") == unit["targetTextSha256"],
                 f"Audio QC checked the audio against different text: {group_id}")
        _require(row.get("asrPrimary") == primary and row.get("asrPrimaryModel") == {
                     "model": screening["model"], "modelRevision": screening.get("modelRevision")}
                 and row.get("asrPrimaryRecognized") == by_group[group_id]["recognized"],
                 f"Audio QC primary ASR differs from the bound screening: {group_id}")
        _require(row.get("asrPrimarySettingsSha256") == primary_settings,
                 f"Audio QC primary ASR runtime differs from the bound screening: {group_id}")
        identity = row.get("asrSecondaryModel")
        if group_id in flagged or group_id in accepted:
            if isinstance(identity, dict):
                _require(set(identity) == {"model", "modelRevision"} and isinstance(identity["model"], str)
                         and bool(identity["model"]) and (identity["modelRevision"] is None or
                                                          isinstance(identity["modelRevision"], str) and bool(identity["modelRevision"])),
                         f"Flagged unit needs its secondary ASR identity: {group_id}")
                _require(secondary_asr_model is None or secondary_asr_model == identity["model"],
                         "Secondary ASR CLI label differs from the QC runtime")
                _require(secondary_identity is None or secondary_identity == identity,
                         "Flagged units used different secondary ASR runtimes")
                secondary_identity = dict(identity)
        if group_id in accepted:
            # The person accepted this exact audio; both ASR opinions stay recorded, unjudged.
            rows.append({"textGroupId": group_id, "audioSha256": unit["audio"]["sha256"], "status": "human_accepted",
                         "asr": "human_accepted", "primarySimilarity": primary,
                         "secondarySimilarity": secondary if isinstance(secondary, (int, float)) else None,
                         "secondaryAsrModel": dict(identity) if isinstance(identity, dict) else None,
                         "failedAttempts": int(row.get("failedAttempts", 0))})
            continue
        if group_id in flagged:
            _require(isinstance(identity, dict), f"Flagged unit needs its secondary ASR identity: {group_id}")
            _require(isinstance(secondary, (int, float)) and secondary >= threshold,
                     f"Flagged unit needs a passing secondary ASR: {group_id}")
            heard = row.get("asrSecondaryRecognized")
            _require(isinstance(heard, str) and transcript_similarity(texts[group_id], heard, locale) == secondary,
                     f"Secondary ASR score is not the score of its transcript: {group_id}")
            _require(transcript_agrees(texts[group_id], heard, locale, threshold),
                     f"Secondary ASR does not agree with the text (short unit, negation or number): {group_id}")
        rows.append({"textGroupId": group_id, "audioSha256": unit["audio"]["sha256"], "status": "pass",
                     "asr": "secondary_pass" if group_id in flagged else "primary_pass",
                     "primarySimilarity": primary,
                     "secondarySimilarity": secondary if group_id in flagged else None,
                     "secondaryAsrModel": dict(secondary_identity) if group_id in flagged else None,
                     "failedAttempts": int(row.get("failedAttempts", 0))})
    receipt = {
        "schemaVersion": SCHEMA, "reviewKind": basis.REVIEW_KIND, "humanApproval": False,
        "decision": "machine_quality_waived", "targetLocale": locale,
        "englishSourcePackageJsonSha256": package["englishSourcePackageJsonSha256"],
        "targetLanguageCandidateJsonSha256": package["targetLanguageCandidateJsonSha256"],
        "targetLanguageAudioPackageJsonSha256": json_sha256(package),
        "trackSha256": package["track"]["sha256"],
        "textWaiverJsonSha256": json_sha256(text_waiver),
        "machineScreeningStatus": package["machineScreening"]["status"],
        "machineScreeningReceiptJsonSha256": json_sha256(screening),
        "secondaryAsrModel": secondary_identity,
        "reviewedUnitIds": [row["textGroupId"] for row in package["units"]],
        "unitResults": rows, "audioQcJsonSha256": json_sha256(audio_qc),
        "trackCheckJsonSha256": json_sha256(track_check),
        "calibration": summary,
        "implementationSha256": implementation, "rules": basis.RULES,
        "disclosure": disclosure(locale), "createdAt": created_at or _now(),
        "postPublicationSpotCheck": "owner_spot_check_after_release",
        "humanAcceptance": {
            "schemaVersion": human_acceptance["schemaVersion"], "jsonSha256": json_sha256(human_acceptance),
            "decidedBy": human_acceptance["decidedBy"], "decidedAt": human_acceptance["decidedAt"],
            "userStatement": human_acceptance["userStatement"],
            "audioQcJsonSha256": human_acceptance["audioQcJsonSha256"],
            "groupIds": [row["groupId"] for row in results if row["groupId"] in accepted],
            "groupDecisions": [{"groupId": u["groupId"], "decidedBy": u.get("decidedBy", human_acceptance["decidedBy"]),
                                "decidedByRole": u.get("decidedByRole", "human_operator")}
                               for u in human_acceptance["units"] if u["groupId"] in accepted]},
    }
    _schema(receipt, SCHEMA)
    return receipt


def validate_audio_waiver(package: dict, receipt: dict, screening: dict | None) -> None:
    """Gate-time check of a v2 or v3 waiver against exactly this machine-screened package."""
    if not is_audio_waiver_v3(receipt):
        basis.validate_audio_waiver(package, receipt, screening)
        return
    _schema(receipt, SCHEMA)
    _require(screening is not None, "Audio waiver requires the bound full ASR screening receipt")
    _require(_machine_screened(package),
             "Audio waiver applies only to a machine-screened package with no human decision")
    expected = {"targetLocale": package["targetLocale"],
                "englishSourcePackageJsonSha256": package["englishSourcePackageJsonSha256"],
                "targetLanguageCandidateJsonSha256": package["targetLanguageCandidateJsonSha256"],
                "targetLanguageAudioPackageJsonSha256": json_sha256(package),
                "trackSha256": package["track"]["sha256"],
                "machineScreeningStatus": package["machineScreening"]["status"],
                "machineScreeningReceiptJsonSha256": json_sha256(screening)}
    _require(all(receipt[key] == value for key, value in expected.items()),
             "Audio waiver does not bind this package, track and screening")
    named = receipt["humanAcceptance"]["groupIds"]
    _require(named == [row["textGroupId"] for row in receipt["unitResults"] if row["status"] == "human_accepted"]
             and named, "Audio waiver v3 human acceptance differs from its unit results")
    accepted = set(named)
    flagged = set(screening_queue(package, screening))
    by_group = {row["textGroupId"]: row for row in screening["results"]}
    units = package["units"]
    threshold = _asr_threshold()
    _require(receipt["reviewedUnitIds"] == [unit["textGroupId"] for unit in units]
             and [row["textGroupId"] for row in receipt["unitResults"]] == receipt["reviewedUnitIds"],
             "Audio waiver coverage differs from the package")
    for row, unit in zip(receipt["unitResults"], units):
        group_id = unit["textGroupId"]
        _require(row["audioSha256"] == unit["audio"]["sha256"]
                 and row["primarySimilarity"] == by_group[group_id]["similarity"],
                 f"Audio waiver unit differs from the package: {group_id}")
        if group_id in accepted:
            _require(row["asr"] == "human_accepted", f"Accepted unit must be marked human_accepted: {group_id}")
        elif group_id in flagged:
            _require(row.get("secondaryAsrModel") == receipt["secondaryAsrModel"],
                     f"Secondary ASR identity differs from its QC-bound unit: {group_id}")
            _require(row["asr"] == "secondary_pass" and receipt["secondaryAsrModel"]
                     and row["secondarySimilarity"] is not None and row["secondarySimilarity"] >= threshold,
                     f"Flagged unit lacks a passing secondary ASR: {group_id}")
        else:
            _require(row.get("secondaryAsrModel") is None, "Unflagged unit claims a secondary ASR identity")
            _require(row["asr"] == "primary_pass", f"Unflagged unit claims a secondary ASR: {group_id}")
    basis._validate_summary(receipt)
