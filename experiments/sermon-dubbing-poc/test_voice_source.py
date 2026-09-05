import copy
import json
from pathlib import Path
import tempfile
import unittest

from poc import sha256
from prepare_voice_candidates import group_candidates, sentence_spans
from run_qwen_training_smoke import validate_inputs
from voice_source import authorized_source, verify_reference


class AuthorizationTests(unittest.TestCase):
    def test_authorization_cannot_reclassify_protected_evaluation(self):
        for plan in [{"sourceId": "hoeJTwl-EJg"}, {"sourceId": "a-different-upload", "serviceDate": "2026-08-09"}]:
            with self.assertRaisesRegex(ValueError, "Protected evaluation"):
                verify_reference(plan)

    def test_permission_is_bound_to_source_hash_and_purpose(self):
        record = {"schemaVersion": "sermon-voice-authorization-v1", "status": "confirmed_by_user", "statement": "User confirmed training and dubbing", "purposes": ["voice_training", "chinese_dubbing"], "sources": [{"sourceId": "sermon-a", "sha256": "hash-a"}]}
        self.assertTrue(authorized_source(record, "sermon-a", "hash-a", "voice_training"))
        for source, digest, purpose in [("sermon-b", "hash-a", "voice_training"), ("sermon-a", "changed", "voice_training"), ("sermon-a", "hash-a", "other")]:
            self.assertFalse(authorized_source(record, source, digest, purpose))
        record["status"] = "pending"
        self.assertFalse(authorized_source(record, "sermon-a", "hash-a", "voice_training"))

    def test_reference_checks_authorization_and_audio_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            audio = root / "ref.wav"
            audio.write_bytes(b"reference audio")
            authorization = root / "authorization.json"
            authorization.write_text(json.dumps({"schemaVersion": "sermon-voice-authorization-v1", "status": "confirmed_by_user", "statement": "confirmed", "purposes": ["chinese_dubbing"], "sources": [{"sourceId": "a", "sha256": "source-hash"}]}))
            profile = {"sourceId": "a", "sourceSha256": "source-hash", "authorization": str(authorization), "authorizationSha256": sha256(authorization), "referenceAudio": str(audio), "referenceSha256": sha256(audio), "referenceText": "English words.", "referenceLanguage": "English", "role": "production_source_candidate", "protectedEvaluationOverlap": False}
            path = root / "profile.json"
            path.write_text(json.dumps(profile))
            plan = {"sourceId": "a", "sourceAudioSha256": "source-hash", "voice": {"profile": str(path), "profileSha256": sha256(path)}}
            self.assertEqual(verify_reference(plan)["referenceText"], "English words.")
            audio.write_bytes(b"changed reference")
            with self.assertRaisesRegex(ValueError, "audio changed"):
                verify_reference(plan)

    def test_smoke_inputs_do_not_grant_production_admission(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "audio.wav").write_bytes(b"audio")
            (root / "authorization.json").write_text(json.dumps({"status": "confirmed_by_user", "purposes": ["voice_training"], "sources": [{"sourceId": "ZDQwL3K-A44", "sha256": "source"}]}))
            manifest = {"purpose": "engineering_training_smoke", "productionTrainingAdmission": False, "sourceId": "ZDQwL3K-A44", "sourceSha256": "source", "protectedEvaluationOverlap": False, "samples": [{"file": "audio.wav", "sha256": sha256(root / "audio.wav"), "language": "English", "text": "Actual English."}], "reference": {"file": "audio.wav", "sha256": sha256(root / "audio.wav")}}
            path = root / "research-inputs.json"
            path.write_text(json.dumps(manifest))
            self.assertFalse(validate_inputs(root)["productionTrainingAdmission"])
            for key, value in [("productionTrainingAdmission", True), ("sourceId", "protected-source"), ("protectedEvaluationOverlap", True)]:
                changed = copy.deepcopy(manifest)
                changed[key] = value
                path.write_text(json.dumps(changed))
                with self.assertRaises(ValueError):
                    validate_inputs(root)


class CandidateTests(unittest.TestCase):
    def test_cut_trailing_sentence_is_not_a_candidate(self):
        words = [{"text": "Hello", "start": 0.2, "end": 0.5}, {"text": "world", "start": 0.5, "end": 1.0}, {"text": "Cut", "start": 1.2, "end": 1.4}]
        spans = sentence_spans("Hello world. Cut", words)
        self.assertEqual(spans, [{"text": "Hello world.", "start": 0.2, "end": 1.0}])
        with self.assertRaises(ValueError):
            sentence_spans("Hello something.", words)

    def test_disagreement_with_existing_source_is_excluded(self):
        spans = [{"text": "This is the actual sentence.", "start": 0, "end": 7}, {"text": "A hallucinated ending.", "start": 8, "end": 15}]
        candidates, rejected = group_candidates(spans, "This is the actual sentence.")
        self.assertEqual(len(candidates), 1)
        self.assertEqual(rejected[0]["reasons"], ["does_not_match_existing_english_source"])


if __name__ == "__main__":
    unittest.main()
