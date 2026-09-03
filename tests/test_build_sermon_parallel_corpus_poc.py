import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "build_sermon_parallel_corpus_poc.py"
SPEC = importlib.util.spec_from_file_location("build_sermon_parallel_corpus_poc", SCRIPT_PATH)
mod = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = mod
SPEC.loader.exec_module(mod)


class ParallelCorpusPocTest(unittest.TestCase):
    def cues(self):
        return [
            {"cueId": "cue_00001", "startMs": 0, "endMs": 1000, "text": "Welcome everyone."},
            {"cueId": "cue_00002", "startMs": 1000, "endMs": 2000, "text": "Today we read John 5:31."},
            {"cueId": "cue_00003", "startMs": 2000, "endMs": 3000, "text": "Jesus speaks to us."},
            {"cueId": "cue_00004", "startMs": 3000, "endMs": 4000, "text": "Let us pray."},
        ]

    def test_aggregate_cues_preserves_ids_and_timeline(self):
        chunks = mod.aggregate_cues(self.cues(), window_ms=2000)
        self.assertEqual(len(chunks), 2)
        self.assertEqual(chunks[0]["cueIds"], ["cue_00001", "cue_00002"])
        self.assertEqual(chunks[1]["startMs"], 2000)

    def test_boundary_validation_rejects_unknown_and_reversed(self):
        chunks = mod.aggregate_cues(self.cues(), window_ms=1000)
        self.assertEqual(
            mod.validate_coarse_boundary({"startChunkId": 1, "endChunkId": 3}, chunks),
            (1, 3),
        )
        with self.assertRaises(RuntimeError):
            mod.validate_coarse_boundary({"startChunkId": 3, "endChunkId": 1}, chunks)
        by_id = {item["cueId"]: item for item in self.cues()}
        start = [by_id["cue_00002"]]
        end = [by_id["cue_00004"]]
        self.assertEqual(
            mod.validate_exact_boundary(
                {"startCueId": "cue_00002", "endCueId": "cue_00004"},
                self.cues(),
                start,
                end,
            ),
            (1, 3),
        )

    def test_hash_bound_human_boundary_is_accepted(self):
        receipt = {
            "sourceCues": {"sha256": "a" * 64},
            "sourceManifest": {"sha256": "b" * 64},
        }
        approval = {
            "schemaVersion": 1,
            "status": "approved_human_boundary",
            "contentScope": "sermon_only",
            "videoId": "video",
            "startCueId": "cue_00002",
            "endCueId": "cue_00004",
            "approvedByHuman": True,
            "requiresHumanReview": False,
            "sourceBindings": {
                "sourceCuesSha256": "a" * 64,
                "sourceManifestSha256": "b" * 64,
            },
            "approval": {
                "approver": "Human",
                "audioReviewCompleted": True,
                "decisionSha256": "c" * 64,
            },
        }
        start, end, boundary = mod.validate_approved_boundary(
            approval, self.cues(), receipt
        )
        self.assertEqual((start, end), (1, 3))
        self.assertTrue(boundary["approvedByHuman"])
        self.assertEqual(boundary["promptVersion"], "human-operator-boundary-v1")

    def test_human_boundary_rejects_source_hash_drift(self):
        receipt = {
            "sourceCues": {"sha256": "a" * 64},
            "sourceManifest": {"sha256": "b" * 64},
        }
        approval = {
            "status": "approved_human_boundary",
            "contentScope": "sermon_only",
            "videoId": "video",
            "startCueId": "cue_00002",
            "endCueId": "cue_00004",
            "approvedByHuman": True,
            "requiresHumanReview": False,
            "sourceBindings": {
                "sourceCuesSha256": "wrong",
                "sourceManifestSha256": "b" * 64,
            },
            "approval": {
                "approver": "Human",
                "audioReviewCompleted": True,
                "decisionSha256": "c" * 64,
            },
        }
        with self.assertRaises(RuntimeError):
            mod.validate_approved_boundary(approval, self.cues(), receipt)

    def test_approval_preflight_stops_before_any_output_when_set_is_missing(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            with self.assertRaises(SystemExit):
                mod.preflight_approved_boundaries(
                    video_ids=["video"],
                    corpus_root=root / "raw",
                    approved_boundary_root=root / "approvals",
                )
            self.assertFalse((root / "output").exists())

    def test_semantic_segments_keep_source_cues_and_poc_split(self):
        segments = mod.build_semantic_segments(
            video_id="video",
            cues=self.cues(),
            start_index=1,
            end_index=3,
            preferred_chars=1,
            preferred_ms=1,
        )
        self.assertEqual(len(segments), 3)
        self.assertEqual(segments[0]["cueIds"], ["cue_00002"])
        self.assertEqual(segments[0]["split"], "poc")
        self.assertEqual(segments[0]["previousSegmentId"], None)
        self.assertEqual(segments[-1]["nextSegmentId"], None)

    def test_semantic_segments_inherit_expansion_split(self):
        segments = mod.build_semantic_segments(
            video_id="video",
            cues=self.cues(),
            start_index=1,
            end_index=3,
            split="dev",
            preferred_chars=1,
            preferred_ms=1,
        )
        self.assertTrue(segments)
        self.assertEqual({item["split"] for item in segments}, {"dev"})

    def test_exact_ids_requires_same_order_and_coverage(self):
        expected = [{"id": "a"}, {"id": "b"}]
        mod.exact_ids(expected, [{"id": "a"}, {"id": "b"}], "test")
        with self.assertRaises(RuntimeError):
            mod.exact_ids(expected, [{"id": "b"}, {"id": "a"}], "test")

    def test_scripture_resolver_attaches_exact_public_domain_verses(self):
        bible = {
            "translation": {"id": "cmn-cu89s", "license": "Public Domain"},
            "books": [{"code": "JOH", "nameEn": "John", "nameZh": "约翰福音"}],
            "chapters": {
                "JOH": {
                    "5": [
                        {"verse": 31, "text": "我若为自己作见证，我的见证就不真。"},
                        {"verse": 32, "text": "另有一位给我作见证。"},
                    ]
                }
            },
        }
        resolved, unresolved = mod.resolve_scripture_refs(["John 5:31-32"], bible)
        self.assertFalse(unresolved)
        self.assertEqual(resolved[0]["bookCode"], "JOH")
        self.assertEqual(len(resolved[0]["canonicalZh"]), 2)

    def test_training_provenance_is_always_blocked(self):
        segment = {
            "sermonId": "s",
            "id": "s1",
            "startMs": 0,
            "endMs": 1000,
            "en": "Jesus said 12 words.",
            "zh": "耶稣说了十二句话。",
            "needsHumanReview": False,
        }
        queue = mod.build_review_queue([segment])
        self.assertEqual(queue[0]["trainingEligibility"], "blocked")
        self.assertEqual(queue[0]["reviewStatus"], "pending_human")

    def test_cached_request_does_not_make_network_call(self):
        system = "system"
        user_payload = {"x": 1}
        schema = mod.object_schema({"ok": {"type": "boolean"}}, ["ok"])
        public_request = {
            "model": "gpt-5.6-sol",
            "reasoning": {"effort": "high"},
            "input": [
                {"role": "system", "content": [{"type": "input_text", "text": system}]},
                {"role": "user", "content": [{"type": "input_text", "text": json.dumps(user_payload)}]},
            ],
            "text": {"format": mod.json_schema_format("test_schema", schema)},
        }
        input_hash = mod.request_input_sha256(
            prompt_version="v1", stage="test", request=public_request
        )
        with tempfile.TemporaryDirectory() as tempdir:
            cache = Path(tempdir) / "cache.json"
            mod.write_json(cache, {"inputSha256": input_hash, "result": {"ok": True}})
            result, _ = mod.request_json_cached(
                api_key="unused",
                cache_path=cache,
                stage="test",
                prompt_version="v1",
                model="gpt-5.6-sol",
                reasoning_effort="high",
                system_prompt=system,
                user_payload=user_payload,
                schema_name="test_schema",
                schema=schema,
            )
        self.assertEqual(result, {"ok": True})

    def test_cache_identity_ignores_json_object_key_order(self):
        schema = mod.object_schema({"ok": {"type": "boolean"}}, ["ok"])
        first = {
            "model": "gpt-5.6-sol",
            "input": [
                {
                    "role": "user",
                    "content": [{"type": "input_text", "text": '{"a":1,"b":2}'}],
                }
            ],
            "text": {"format": mod.json_schema_format("test", schema)},
        }
        second = {
            "model": "gpt-5.6-sol",
            "input": [
                {
                    "role": "user",
                    "content": [{"type": "input_text", "text": '{"b":2,"a":1}'}],
                }
            ],
            "text": {"format": mod.json_schema_format("test", schema)},
        }
        self.assertEqual(
            mod.request_input_sha256(stage="test", prompt_version="v1", request=first),
            mod.request_input_sha256(stage="test", prompt_version="v1", request=second),
        )


if __name__ == "__main__":
    unittest.main()
