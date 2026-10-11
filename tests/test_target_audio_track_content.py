"""Delivered compressed audio must preserve screened samples, beyond loudness."""
import hashlib
import json
import math
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from scripts import machine_quality_waiver as waiver
from scripts import target_audio_auto_qc as qc


@unittest.skipUnless(shutil.which("ffmpeg"), "ffmpeg is not installed")
class CompressedTrackContentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.rate = 16000

    def write(self, filename, data):
        path = self.directory / filename
        path.write_bytes(data)
        return {"path": str(path), "sha256": hashlib.sha256(data).hexdigest()}

    def signal(self, frequency):
        # Both frequencies complete whole cycles in every 50 ms QC window.
        return qc.encode_pcm16([
            0.5 * math.sin(2 * math.pi * frequency * index / self.rate)
            if index % 8000 < 6400 else 0.0
            for index in range(3 * self.rate)
        ], self.rate)

    def package(self, replacement=None, bitrate="64k"):
        master = self.signal(220)
        unit = self.write("unit.wav", master)
        self.write("track.wav", master)
        source = self.write("encode-source.wav", replacement or master)
        out = self.directory / "track.mp3"
        subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-y", "-i", source["path"],
                        "-b:a", bitrate, str(out)], check=True)
        track = self.write("track.mp3", out.read_bytes())
        schedule = {"entries": [{"textGroupId": "g1", "plannedStart": 0}]}
        artifact = self.write("schedule.json", json.dumps(schedule).encode())
        artifact["jsonSha256"] = waiver.json_sha256(schedule)
        return {"targetLocale": "ko", "units": [{"textGroupId": "g1", "audio": unit}],
                "schedule": artifact, "track": track}

    def test_valid_lossy_mp3_preserves_waveform(self):
        for bitrate in ("64k", "128k"):
            with self.subTest(bitrate=bitrate):
                result = qc.check_track(self.package(bitrate=bitrate))
                self.assertEqual(result["status"], "pass", result)
                self.assertEqual(result["method"]["compressed"], "decoded_waveform")
                self.assertEqual(result["waveform"]["deviantWindows"], 0)

    @unittest.skipUnless(shutil.which("say"), "macOS speech synthesizer is not installed")
    def test_valid_synthesized_speech_mp3(self):
        speech = self.directory / "speech.aiff"
        subprocess.run(["say", "-o", str(speech),
                        "Jesus saves. God loves all. Grace is not something we earn. "
                        "It is a gift we receive. Turn with me to Revelation chapter three."], check=True)
        for rate in (16000, 24000):
            wav = self.directory / f"speech-{rate}.wav"
            subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-i", str(speech),
                            "-ar", str(rate), "-ac", "1", str(wav)], check=True)
            for bitrate in ("64k", "128k"):
                with self.subTest(rate=rate, bitrate=bitrate):
                    # The helper's master must be the same screened speech.
                    # Update master and unit, leaving the encoded speech intact.
                    package = self.package(wav.read_bytes(), bitrate)
                    package["units"][0]["audio"] = self.write("unit.wav", wav.read_bytes())
                    self.write("track.wav", wav.read_bytes())
                    result = qc.check_track(package)
                    self.assertEqual(result["status"], "pass", result)

    def test_wrong_content_with_matching_loudness_is_rejected(self):
        result = qc.check_track(self.package(self.signal(440)))
        # This substituted audio satisfies the prior envelope-only gate.
        self.assertLessEqual(result["envelope"]["deviantWindows"],
                             qc.TRACK_ENVELOPE["maxDeviantShare"] * result["envelope"]["windows"])
        self.assertIn("compressed_track_differs_from_pcm_master", result["issues"])
        self.assertGreater(result["waveform"]["deviantWindows"], 0)

    def test_short_replaced_phrase_cannot_hide_in_long_track_average(self):
        original, rate = qc.decode_pcm16(self.signal(220))
        wrong, _ = qc.decode_pcm16(self.signal(440))
        original[rate:rate + rate // 10] = wrong[rate:rate + rate // 10]
        result = qc.check_track(self.package(qc.encode_pcm16(original, rate)))
        self.assertIn("compressed_track_differs_from_pcm_master", result["issues"])


if __name__ == "__main__":
    unittest.main()
