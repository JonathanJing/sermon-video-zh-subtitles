"""Wrapper contract tests with a fake CLI; these do not validate Apple artwork."""
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

SPEC = importlib.util.spec_from_file_location("tongxing_frames", Path(__file__).resolve().parents[1] / "frames.py")
frames = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(frames)

STUB = r'''
import json, os, pathlib, sys
args = sys.argv[1:]
mode = os.environ.get("FRAMES_STUB_MODE", "success")
if mode == "exit":
    print("render failed", file=sys.stderr)
    sys.exit(7)
if mode == "json-error":
    print(json.dumps({"error": "assets missing", "setup_required": True}))
    sys.exit(0)
if mode == "nested-error":
    print(json.dumps([{"error": "bad input"}]))
    sys.exit(0)
if mode == "bad-json":
    print("not JSON")
    sys.exit(0)
output = pathlib.Path(args[args.index("-o") + 1])
inputs = [pathlib.Path(arg) for arg in args if pathlib.Path(arg).is_file()]
if mode != "no-output":
    suffix = ".mp4" if "video" in args else ".png"
    names = ["merged_framed"] if "-m" in args else [p.stem + "_framed" for p in inputs]
    for name in names:
        (output / (name + suffix)).write_bytes(b"" if mode == "empty" else b"fake-render")
if mode == "mutate":
    inputs[0].write_bytes(b"changed")
print(json.dumps({"outputs": [str(p) for p in output.iterdir()]}))
'''


class FramesTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.raw = self.root / "raw inputs"
        self.raw.mkdir()
        self.one = self.raw / "home screen.png"
        self.two = self.raw / "player.png"
        self.one.write_bytes(b"original-home")
        self.two.write_bytes(b"original-player")
        self.binary = self.root / "fake frames"
        self.binary.write_text("#!" + sys.executable + "\n" + STUB, encoding="utf-8")
        self.binary.chmod(0o755)
        patch = mock.patch.object(frames, "ROOT", self.root)
        patch.start()
        self.addCleanup(patch.stop)
        env = mock.patch.dict(os.environ, {"TONGXING_FRAMES_BIN": str(self.binary), "FRAMES_STUB_MODE": "success"})
        env.start()
        self.addCleanup(env.stop)

    def invoke(self, *args, mode="success"):
        stdout, stderr = io.StringIO(), io.StringIO()
        with mock.patch.dict(os.environ, {"FRAMES_STUB_MODE": mode}), contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = frames.main([str(arg) for arg in args])
        return code, stdout.getvalue().strip(), stderr.getvalue()

    def receipt(self, output):
        return json.loads((Path(output) / "receipt.json").read_text())

    def assert_usage_error(self, *args):
        with self.assertRaises(SystemExit) as exc:
            self.invoke(*args)
        self.assertEqual(exc.exception.code, 2)
        self.assertFalse((self.root / "artifacts").exists())

    def test_help_needs_no_tool(self):
        with self.assertRaises(SystemExit) as exc:
            self.invoke("--help")
        self.assertEqual(exc.exception.code, 0)

    def test_dry_run_never_invokes_cli_or_writes(self):
        with mock.patch("subprocess.run", side_effect=AssertionError("must not execute")):
            code, output, _ = self.invoke("--dry-run", self.one)
        self.assertEqual(code, 0)
        self.assertIn("<unique-run>", output)
        self.assertIn("home screen.png", output)
        self.assertFalse((self.root / "artifacts").exists())

    def test_image_batch_preserves_originals_and_records_hashes(self):
        code, output, _ = self.invoke(self.one, self.two, "--device", "iPhone 17 Pro Portrait", "--color", "Silver")
        self.assertEqual(code, 0)
        receipt = self.receipt(output)
        self.assertEqual(receipt["status"], "completed")
        self.assertEqual(receipt["scope"], "presentation_only")
        self.assertEqual(len(receipt["outputs"]), 2)
        self.assertEqual(self.one.read_bytes(), b"original-home")
        self.assertEqual(self.two.read_bytes(), b"original-player")
        self.assertEqual(receipt["sources"][0]["sha256"], frames.sha256(self.one))
        self.assertNotIn("--preset", receipt["command"])

    def test_runs_do_not_overwrite_previous_outputs(self):
        first = self.invoke(self.one)[1]
        second = self.invoke(self.one)[1]
        self.assertNotEqual(first, second)
        self.assertTrue((Path(first) / "home screen_framed.png").is_file())

    def test_merge_outputs_one_image(self):
        code, output, _ = self.invoke("--merge", self.one, self.two)
        self.assertEqual(code, 0)
        self.assertEqual(len(self.receipt(output)["outputs"]), 1)

    def test_video_sequential_merge_and_preset(self):
        one, two = self.raw / "one.mp4", self.raw / "two.mov"
        one.write_bytes(b"video-one")
        two.write_bytes(b"video-two")
        code, output, _ = self.invoke("--video", "--merge", "--playback-offset", "--preset", "compact", one, two)
        self.assertEqual(code, 0)
        self.assertIn("--playback-offset", self.receipt(output)["command"])
        self.assertIn("compact", self.receipt(output)["command"])
        self.assertTrue((Path(output) / "merged_framed.mp4").exists())

    def test_video_defaults_to_balanced(self):
        video = self.raw / "one.MOV"
        video.write_bytes(b"video")
        code, output, _ = self.invoke("--video", video)
        self.assertEqual(code, 0)
        self.assertIn("balanced", self.receipt(output)["command"])

    def test_invalid_option_combinations_and_inputs(self):
        cases = [("--preset", "best", self.one), ("--playback-offset", self.one), ("--merge", self.one), (self.raw / "missing.png",), ("--video", self.one), ("--assets", self.raw / "missing", self.one)]
        for case in cases:
            with self.subTest(args=case):
                self.assert_usage_error(*case)

    def test_duplicate_basenames_rejected_case_insensitively(self):
        other = self.root / "other"
        other.mkdir()
        duplicate = other / "HOME SCREEN.png"
        duplicate.write_bytes(b"duplicate")
        self.assert_usage_error(self.one, duplicate)

    def test_missing_cli_fails_without_installing(self):
        with mock.patch.dict(os.environ, {"TONGXING_FRAMES_BIN": str(self.root / "not-installed")}):
            code, _, stderr = self.invoke(self.one)
        self.assertEqual(code, 127)
        self.assertIn("FRAMES.zh.md", stderr)
        self.assertFalse((self.root / "artifacts").exists())

    def test_dry_run_works_without_cli(self):
        with mock.patch.dict(os.environ, {"TONGXING_FRAMES_BIN": str(self.root / "not-installed")}):
            self.assertEqual(self.invoke("--dry-run", self.one)[0], 0)

    def test_nonzero_upstream_status_is_preserved(self):
        code, output, _ = self.invoke(self.one, mode="exit")
        self.assertEqual(code, 7)
        self.assertEqual(self.receipt(output)["status"], "failed")
        self.assertIn("render failed", (Path(output) / "run.log").read_text())

    def test_json_errors_or_missing_outputs_are_not_success(self):
        for mode in ("json-error", "nested-error", "bad-json", "no-output", "empty"):
            with self.subTest(mode=mode):
                code, output, _ = self.invoke(self.one, mode=mode)
                self.assertNotEqual(code, 0)
                self.assertEqual(self.receipt(output)["status"], "failed")

    def test_input_change_is_detected(self):
        code, output, _ = self.invoke(self.one, mode="mutate")
        self.assertNotEqual(code, 0)
        self.assertIn("Source changed", self.receipt(output)["error"])

    def test_assets_path_and_arguments_with_spaces(self):
        assets = self.root / "Apple Frames assets"
        assets.mkdir()
        code, output, _ = self.invoke("--assets", assets, self.one)
        self.assertEqual(code, 0)
        command = self.receipt(output)["command"]
        self.assertEqual(command[command.index("--assets") + 1], str(assets.resolve()))


if __name__ == "__main__":
    unittest.main()
