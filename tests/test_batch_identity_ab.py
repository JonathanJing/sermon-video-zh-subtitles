"""DEV-GRP-005 prerequisite: the blind batch-identity A/B harness (decision 1).

The harness renders nothing: it selects groups from a formal speech job, pairs their
formal (batch) WAVs with per-group preview (alone) WAVs under hidden labels, records a
listener's verdicts, and binds the result to the synthesis identity it tested.
"""
import hashlib
import io
import json
import math
from contextlib import redirect_stdout
from pathlib import Path
import random
import struct
import tempfile
import unittest
import wave

from scripts import tongxing_host  # noqa: F401  (binds the package host)
from tongxing_production.audio import batch_identity_ab as ab

INTENT = {"schemaVersion": ab.INTENT_SCHEMA, "adapterId": "qwen3_tts_sft", "adapterFileSha256": "1" * 64,
          "model": "Qwen/Qwen3-TTS-12Hz-1.7B-Base", "modelRevision": "rev", "conditioningRef": "voice://speaker",
          "checkpointSha256": "2" * 64, "speakerId": "speaker", "speakerKey": "speaker", "targetLocale": "ko",
          "languageParameter": "Korean", "operationPoliciesFileSha256": "3" * 64, "rendererSha256": "4" * 64,
          "seed": 43, "temperature": 0.7, "repetitionPenalty": 1.05, "maxNewTokens": 768, "dtype": "bfloat16",
          "attention": "sdpa", "deliveryInstruction": None, "ratePolicy": "natural_no_time_stretch",
          "batchSize": 8, "batchSeedPolicy": "base_plus_fixed_window_start_ordered_full_window_v2",
          "batchImplementationSha256": "5" * 64, "batchCachedUnitPolicy": "replay", "replicaPolicy": "fixed",
          "replicaImplementationSha256": "6" * 64}


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def tone(path: Path, seconds: float, gain: float, pitch: float = 220.0) -> str:
    rate = 8000
    samples = [int(gain * 32767 * math.sin(2 * math.pi * pitch * n / rate)) for n in range(int(seconds * rate))]
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(rate)
        audio.writeframes(struct.pack("<" + "h" * len(samples), *samples))
    return sha(path.read_bytes())


class Job:
    """A formal speech job of ``units`` units and a preview render of some of them."""

    def __init__(self, root: Path, units: int = 14):
        self.root, self.job, self.preview = root, root / "speech-job", root / "preview"
        (self.job / "job.json").parent.mkdir(parents=True, exist_ok=True)
        (self.job / "job.json").write_text(json.dumps({"units": units}))
        self.texts = {}
        for index in range(units):
            group, text_sha = f"g{index:02d}", sha(f"text {index}".encode())
            self.texts[group] = text_sha
            relative = f"languages/ko/audio/unit-{index:04d}.wav"
            audio = tone(self.job / relative, 0.5 + 0.1 * index, 0.3)
            (self.job / "receipts").mkdir(parents=True, exist_ok=True)
            start = index - index % 8
            intent = dict(INTENT, unitIndex=index, groupId=group, sourceUnitIds=[f"u{index}"], textSha256=text_sha,
                          jobJsonSha256="a" * 64, batchWindowStart=start,
                          batchWindowUnitIndices=list(range(start, start + 8)))
            (self.job / "receipts" / f"unit-{index:04d}.intent.json").write_text(json.dumps(intent))
            # The renderer's batch seed is the base seed plus the window start.
            (self.job / "receipts" / f"unit-{index:04d}.render.json").write_text(json.dumps({
                "identity": intent, "audioSha256": audio,
                "generationBatch": {"unitIndices": list(range(start, start + 8)), "seed": 43 + start,
                                    "seedPolicy": INTENT["batchSeedPolicy"], "batchSize": 8}}))
            (self.job / "receipts" / f"unit-{index:04d}.json").write_text(json.dumps({
                "translationGroupId": group, "audioRelativePath": relative, "audioSha256": audio,
                "durationSeconds": 0.5 + 0.1 * index, "fullDecode": "pass"}))

    def render_alone(self, groups, *, gain=0.3, voice=None):
        for group in groups:
            index = int(group[1:])
            audio = tone(self.preview / "units" / f"unit-{index:04d}.wav", 0.5 + 0.1 * index, gain)
            sound = {"groupId": group, "textSha256": self.texts[group], "unitIndex": index,
                     **{field: INTENT[field] for field in ab.PREVIEW_MATCH_FIELDS}, **(voice or {})}
            (self.preview / "receipts").mkdir(parents=True, exist_ok=True)
            (self.preview / "receipts" / f"unit-{index:04d}.json").write_text(json.dumps({
                "schemaVersion": ab.PREVIEW_UNIT_SCHEMA, "status": "preview_only", "fullDecode": "pass",
                "soundIdentity": sound, "audioSha256": audio}))


class BatchIdentityAbTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.job = Job(Path(self.directory.name))

    def packed(self):
        selection = ab.select(self.job.job)
        self.job.render_alone(selection["previewRender"]["groupIds"])
        packet = ab.pack(selection, self.job.preview, self.job.root / "packet", rng=random.Random(7))
        return selection, packet

    def test_select_spreads_over_durations_and_binds_the_tested_identity(self):
        selection = ab.select(self.job.job)
        self.assertEqual(len(selection["groups"]), ab.MINIMUM_GROUPS_PER_LOCALE)
        indices = [group["unitIndex"] for group in selection["groups"]]
        self.assertIn(0, indices)
        self.assertIn(13, indices)  # shortest and longest are both heard
        self.assertEqual(selection["testedIdentitySha256"], ab.json_sha256(ab.tested_identity(dict(INTENT, unitIndex=0))))
        self.assertFalse(selection["humanApproval"])
        with self.assertRaisesRegex(ValueError, "at_least_10_groups_per_locale"):
            ab.select(self.job.job, count=5)
        with self.assertRaisesRegex(ValueError, "speech_job_has_only"):
            ab.select(self.job.job, count=20)

    def test_a_job_mixing_synthesis_stacks_cannot_be_one_ab(self):
        # A unit genuinely rendered by another stack: its intent and commit agree with each other.
        intent_path = self.job.job / "receipts" / "unit-0003.intent.json"
        commit_path = self.job.job / "receipts" / "unit-0003.render.json"
        intent = dict(json.loads(intent_path.read_text()), batchSize=4)
        intent_path.write_text(json.dumps(intent))
        commit = json.loads(commit_path.read_text())
        commit_path.write_text(json.dumps(dict(commit, identity=intent,
                                               generationBatch=dict(commit["generationBatch"], batchSize=4))))
        with self.assertRaisesRegex(ValueError, "mixes_synthesis_identities"):
            ab.select(self.job.job)

    def test_the_packet_hides_which_arm_is_which(self):
        selection, packet = self.packed()
        self.assertEqual(len(packet["pairs"]), 10)
        heard = json.dumps([packet["pairs"], packet["verdictTemplate"]])  # what the listener works from
        self.assertNotIn("batch", heard)
        self.assertNotIn("alone", heard)
        key = json.loads((self.job.root / "packet" / "key.json").read_text())
        self.assertEqual(packet["keySha256"], sha((self.job.root / "packet" / "key.json").read_bytes()))
        self.assertEqual({tuple(sorted(row["arms"].values())) for row in key["pairs"]}, {("alone", "batch")})
        self.assertGreater(len({row["arms"]["X"] for row in key["pairs"]}), 1)  # labels really vary
        self.assertIn("durationSeconds", packet["pairs"][0]["metrics"]["X"])

    def test_a_preview_with_another_voice_or_text_is_refused(self):
        selection = ab.select(self.job.job)
        self.job.render_alone(selection["previewRender"]["groupIds"], voice={"speakerId": "someone-else"})
        with self.assertRaisesRegex(ValueError, "preview_differs_beyond_batching"):
            ab.pack(selection, self.job.preview, self.job.root / "packet")
        with self.assertRaisesRegex(ValueError, "preview_missing_groups"):
            ab.pack(selection, self.job.root / "no-preview", self.job.root / "packet2")

    def test_the_batch_arm_must_be_the_committed_batch_render(self):
        # Silence compaction rewrote unit 3's bytes after the batch render committed them.
        wav = self.job.job / "languages/ko/audio/unit-0003.wav"
        compacted = tone(wav, 0.6, 0.2)
        receipt_path = self.job.job / "receipts/unit-0003.json"
        receipt = json.loads(receipt_path.read_text())
        receipt_path.write_text(json.dumps(dict(receipt, audioSha256=compacted)))
        # Unit 5 claims a scalar render.
        commit_path = self.job.job / "receipts/unit-0005.render.json"
        commit = json.loads(commit_path.read_text())
        commit_path.write_text(json.dumps(dict(commit, generationBatch=None)))
        (self.job.job / "receipts/unit-0007.render.json").unlink()
        selection = ab.select(self.job.job)
        chosen = {group["unitIndex"] for group in selection["groups"]}
        self.assertFalse(chosen & {3, 5, 7})
        self.assertEqual(len(chosen), 10)

    def test_a_preview_with_another_seed_or_decoding_is_refused(self):
        selection = ab.select(self.job.job)
        self.assertEqual(selection["previewRender"]["settings"]["seed"], 43)
        for change in ({"seed": 42}, {"dtype": "float32"}, {"attention": "eager"}):
            with self.subTest(change=change):
                self.job.render_alone(selection["previewRender"]["groupIds"], voice=change)
                with self.assertRaisesRegex(ValueError, "preview_differs_beyond_batching"):
                    ab.pack(selection, self.job.preview, self.job.root / f"packet-{list(change)[0]}")

    def test_duplicate_verdicts_and_bad_times_are_refused(self):
        selection, packet = self.packed()
        quiet = [{"pair": pair["pair"], "verdict": "no_audible_difference"} for pair in packet["pairs"]]
        twice = [{"pair": 1, "verdict": "audible_difference"}] + quiet
        with self.assertRaisesRegex(ValueError, "duplicate_pair_verdicts"):
            ab.record(self.job.root / "packet", twice, "Jony", "2026-10-19T20:00:00Z")
        for when in ("yesterday", "2026-10-19T20:00:00"):
            with self.subTest(when=when), self.assertRaisesRegex(ValueError, "iso_time_with_timezone"):
                ab.record(self.job.root / "packet", quiet, "Jony", when)
        result = ab.record(self.job.root / "packet", quiet, "Jony", "2026-10-19T20:00:00Z")
        self.assertEqual(result["humanListening"]["listenedAt"], "2026-10-19T20:00:00+00:00")

    def test_one_audible_difference_fails_and_every_pair_needs_a_verdict(self):
        selection, packet = self.packed()
        quiet = [{"pair": pair["pair"], "verdict": "no_audible_difference"} for pair in packet["pairs"]]
        result = ab.record(self.job.root / "packet", quiet, "Jony", "2026-10-19T20:00:00Z")
        self.assertEqual((result["result"], result["releaseEligible"]), ("pass", False))
        self.assertEqual(result["humanListening"]["listener"], "Jony")
        heard = [dict(row, verdict="audible_difference") if row["pair"] == 4 else row for row in quiet]
        failed = ab.record(self.job.root / "packet", heard, "Jony", "2026-10-19T20:00:00Z")
        self.assertEqual((failed["result"], failed["audibleDifferencePairs"]), ("fail", [4]))
        with self.assertRaisesRegex(ValueError, "every_pair_needs_one_verdict"):
            ab.record(self.job.root / "packet", quiet[:-1], "Jony", "2026-10-19T20:00:00Z")

    def test_a_changed_packet_file_is_refused(self):
        selection, packet = self.packed()
        (self.job.root / "packet" / packet["pairs"][0]["files"]["X"]).write_bytes(b"other")
        quiet = [{"pair": pair["pair"], "verdict": "no_audible_difference"} for pair in packet["pairs"]]
        with self.assertRaisesRegex(ValueError, "packet_audio_changed"):
            ab.record(self.job.root / "packet", quiet, "Jony", "2026-10-19T20:00:00Z")

    def test_the_result_applies_only_to_the_identity_it_tested(self):
        selection, packet = self.packed()
        quiet = [{"pair": pair["pair"], "verdict": "no_audible_difference"} for pair in packet["pairs"]]
        result = ab.record(self.job.root / "packet", quiet, "Jony", "2026-10-19T20:00:00Z")
        self.assertTrue(ab.applies(result, INTENT))
        for field, value in (("checkpointSha256", "9" * 64), ("batchSize", 4), ("rendererSha256", "8" * 64),
                             ("temperature", 0.8)):
            with self.subTest(field=field):
                self.assertFalse(ab.applies(result, dict(INTENT, **{field: value})))
        self.assertFalse(ab.applies(dict(result, result="fail"), INTENT))

    def test_cli_writes_new_files_only(self):
        selection_path = self.job.root / "selection.json"
        with redirect_stdout(io.StringIO()) as out:
            self.assertEqual(ab.main(["select", "--speech-job", str(self.job.job), "--out", str(selection_path)]), 0)
        self.assertIn("preview --group-id", out.getvalue())
        with self.assertRaisesRegex(ValueError, "output_exists"):
            ab.main(["select", "--speech-job", str(self.job.job), "--out", str(selection_path)])


if __name__ == "__main__":
    unittest.main()
