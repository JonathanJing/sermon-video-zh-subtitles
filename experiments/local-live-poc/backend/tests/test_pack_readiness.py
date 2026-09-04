from __future__ import annotations

from datetime import datetime
import unittest
from zoneinfo import ZoneInfo

from backend.content_pack import build_weekly_pack
from backend.pack_readiness import derive_pack_capabilities, evaluate_pack, select_context_policy


NOW = datetime(2026, 9, 6, 12, 0, tzinfo=ZoneInfo("America/Los_Angeles"))
MESSAGE_APPROVAL = {
    "schemaVersion": "saturday-message-identity-approval-v1",
    "status": "approved",
    "humanApproval": True,
    "matchStatus": "human_confirmed",
    "messageKey": "series-week-title",
    "targetSunday": "2026-09-06",
    "sourceServiceDate": "2026-09-05",
    "approvedBy": "operator",
    "approvedAt": "2026-09-05T20:00:00-07:00",
}


def manifest_for(pack, *, match_status="human_confirmed", phrase_count=0):
    capabilities, counts = derive_pack_capabilities(
        pack,
        asr_phrase_candidate_count=phrase_count,
    )
    return {
        "schemaVersion": "weekly-context-pack-v2",
        "packId": pack["packVersion"],
        "createdAt": "2026-09-05T20:00:00Z",
        "targetSunday": "2026-09-06",
        "messageIdentity": {
            "messageKey": "series-week-title",
            "matchStatus": match_status,
            "sourceServiceDate": "2026-09-05",
            "approval": {
                "sha256": "f" * 64,
                "approvedBy": "operator" if match_status == "human_confirmed" else None,
                "approvedAt": (
                    "2026-09-05T20:00:00-07:00"
                    if match_status == "human_confirmed"
                    else None
                ),
            },
        },
        "provenance": {
            "sourceId": pack["provenance"]["sourceId"],
            "sourceUrlHash": "source-url-hash",
            "sourceAudioSha256": "b" * 64,
            "sermonClipSha256": pack["provenance"]["audioSha256"],
            "segmentSourceSha256": "c" * 64,
            "pipelineInputFingerprint": None,
        },
        "capabilities": capabilities,
        "timing": {
            "quality": "synthetic_sequence_only",
            "source": "gpt-transcribe-reading-layout",
        },
        "validity": {
            "notBefore": "2026-09-05T00:00:00-07:00",
            "validUntil": "2026-09-06T23:59:59-07:00",
            "timezone": "America/Los_Angeles",
        },
        "review": {
            "machineChineseInjectable": False,
            "asrPhraseCandidateCount": phrase_count,
            "reviewedTermCount": counts["reviewedTermCount"],
            "verifiedScriptureCount": counts["verifiedScriptureCount"],
            "reviewedExampleCount": counts["reviewedExampleCount"],
        },
        "policy": {
            "currentLiveEnglishIsSourceOfTruth": True,
            "machineTranslationInjectable": False,
        },
        "artifacts": {
            "sourceAudio": {"path": "download/source_audio.m4a", "sha256": "b" * 64},
            "sermonClip": {"path": "pipeline/source_clip.m4a", "sha256": "a" * 64},
            "saturdaySegments": {"path": "saturday-segments.jsonl", "sha256": "c" * 64},
            "weeklyPack": {"path": "weekly-pack.json", "sha256": "d" * 64},
            "asrPhraseCandidates": {"path": "asr-phrases.candidate.txt", "sha256": "e" * 64},
            "messageIdentityApproval": {
                "path": "message-identity-approval.json",
                "sha256": "f" * 64,
            },
        },
    }


def evaluate(manifest, pack, **kwargs):
    return evaluate_pack(
        manifest,
        pack,
        message_approval=MESSAGE_APPROVAL,
        actual_message_approval_sha256="f" * 64,
        **kwargs,
    )


def pack_for(segment):
    return build_weekly_pack(
        [segment],
        service_date="2026-09-05",
        source_id="saturday-service",
        audio_sha256="a" * 64,
        valid_until="2026-09-06",
        valid_until_timezone="America/Los_Angeles",
    )


class PackReadinessTest(unittest.TestCase):
    def test_machine_only_pack_is_english_map_degraded_mode(self):
        pack = pack_for({
            "segmentId": "seg_001",
            "sourceTextEn": "Grace leads us through the truth.",
            "targetTextZh": "恩典带领我们经过真理。",
            "translationStatus": "machine_generated",
        })
        report = evaluate(manifest_for(pack, phrase_count=2), pack, now=NOW)

        self.assertEqual("degraded", report["status"])
        self.assertEqual("english_map_only", report["runtimeMode"])
        self.assertEqual("english_alignment_v1", report["contextPolicy"])
        self.assertTrue(report["alignmentEnabled"])
        self.assertEqual([], report["blockers"])

    def test_reviewed_translation_selects_full_alignment(self):
        pack = pack_for({
            "segmentId": "seg_001",
            "sourceTextEn": "Grace leads us through the truth.",
            "targetTextZh": "恩典带领我们经过真理。",
            "translationStatus": "reviewed",
        })
        report = evaluate(manifest_for(pack), pack, now=NOW)

        self.assertEqual("ready", report["status"])
        self.assertEqual("full_alignment", report["runtimeMode"])
        self.assertEqual("saturday_alignment_v1", report["contextPolicy"])

    def test_approved_term_without_reviewed_sentence_selects_terms_only(self):
        pack = pack_for({
            "segmentId": "seg_001",
            "sourceTextEn": "We are approaching the promised land.",
            "terms": [{"source": "promised land", "preferredZh": "应许之地", "status": "approved"}],
        })
        report = evaluate(manifest_for(pack), pack, now=NOW)

        self.assertEqual("ready", report["status"])
        self.assertEqual("terms_only", report["runtimeMode"])
        self.assertEqual("weekly_terms_v1", report["contextPolicy"])
        self.assertFalse(report["alignmentEnabled"])

    def test_unconfirmed_message_fails_closed(self):
        pack = pack_for({"segmentId": "seg_001", "sourceTextEn": "Grace is enough."})
        report = evaluate(manifest_for(pack, match_status="inferred"), pack, now=NOW)

        self.assertEqual("invalid", report["status"])
        self.assertEqual("none", report["runtimeMode"])
        self.assertIn("message_match_not_confirmed:inferred", report["blockers"])

    def test_declared_capability_mismatch_fails_closed(self):
        pack = pack_for({"segmentId": "seg_001", "sourceTextEn": "Grace is enough."})
        manifest = manifest_for(pack)
        manifest["capabilities"]["reviewedExamplesReady"] = True
        report = evaluate(manifest, pack, now=NOW)

        self.assertEqual("invalid", report["status"])
        self.assertIn("capability_mismatch:reviewedExamplesReady", report["blockers"])

    def test_local_end_of_day_keeps_pack_active_sunday_evening(self):
        pack = pack_for({"segmentId": "seg_001", "sourceTextEn": "Grace is enough."})
        report = evaluate(
            manifest_for(pack),
            pack,
            now=datetime(2026, 9, 6, 23, 30, tzinfo=ZoneInfo("America/Los_Angeles")),
        )

        self.assertEqual("degraded", report["status"])
        self.assertNotIn("legacy_pack_expired", report["blockers"])

    def test_pack_identity_and_malformed_counts_fail_closed(self):
        pack = pack_for({"segmentId": "seg_001", "sourceTextEn": "Grace is enough."})
        manifest = manifest_for(pack)
        manifest["packId"] = "different-pack"
        pack["provenance"]["segmentCount"] = "not-a-count"

        report = evaluate(manifest, pack, now=NOW)

        self.assertEqual("invalid", report["status"])
        self.assertIn("pack_id_mismatch", report["blockers"])
        self.assertIn(
            "invalid_nonnegative_integer:pack.provenance.segmentCount",
            report["blockers"],
        )

    def test_requested_policy_can_only_reduce_verified_capability(self):
        full = {"contextPolicy": "saturday_alignment_v1"}
        english_only = {"contextPolicy": "english_alignment_v1"}

        self.assertEqual("weekly_terms_v1", select_context_policy(full, "weekly_terms_v1"))
        self.assertEqual("english_alignment_v1", select_context_policy(
            english_only,
            "saturday_alignment_v1",
        ))
        self.assertEqual("none", select_context_policy(english_only, "none"))


if __name__ == "__main__":
    unittest.main()
