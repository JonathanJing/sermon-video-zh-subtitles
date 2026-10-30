# Run digest 20261030-flow2-dryrun

Generated 2026-10-30T20:39:02+00:00. Redacted copies only; source hashes are in manifest.json.

## 20261030-flow2-zh

Source: `~/SynologyDrive/GitHub/Active/sermon-video-zh-subtitles/artifacts/sentence-first-agent/20261030-flow2-zh`

- outcome `outcome.json`: **track_ready_for_review** exit ? (2026-10-30T20:31:35+00:00 → 2026-10-30T20:31:38+00:00)

Timings `timings.tsv`:

| stage | computeSeconds | waitingSeconds | reworkSeconds |
|---|---|---|---|
| l3.finish | 3.0 | 0.0 | 0.0 |
| total | 3.0 | 0.0 | 0.0 |

DeepSeek 状态（`state-check.json`）：**一致**；没有未覆盖句子
- `audit`：finished，窗口 4，句 90，calls 4／hits 0，失败 0
- `translate`：finished，窗口 8，句 90，calls 10／hits 0，失败 0

Error-like log lines (first 5 per log):

- `tts-run.log`: W1030 20:25:09.080000 1 torch/utils/_pytree.py:630] <enum 'KernelPreference'> is an Enum subclass and is now natively supported by torch.compile as an opaque value type. Calling register_constant() on
- `tts-run.log`: W1030 20:25:09.093000 1 torch/utils/_pytree.py:630] <enum 'ScaleCalculationMode'> is an Enum subclass and is now natively supported by torch.compile as an opaque value type. Calling register_constant(
- `tts-run.log`: [0;93m2026-10-30 20:25:09.543394841 [W:onnxruntime:Default, device_discovery.cc:164 DiscoverDevicesForPlatform] GPU device discovery failed: device_discovery.cc:89 ReadFileContents Failed to open fil

Not copied: 1 (none), 1 .html, 25 .json, 9 .jsonl, 1 .md, 1 .mp3, 182 .wav

## 20261030-flow2-ko

Source: `~/SynologyDrive/GitHub/Active/sermon-video-zh-subtitles/artifacts/sentence-first-agent/20261030-flow2-ko`

- outcome `outcome.json`: **track_ready_for_review** exit ? (2026-10-30T20:38:36+00:00 → 2026-10-30T20:38:38+00:00)

Timings `timings.tsv`:

| stage | computeSeconds | waitingSeconds | reworkSeconds |
|---|---|---|---|
| l3.finish | 8.0 | 0.0 | 5.0 |
| l3.lag-loop.ko | 0.0 | 0.0 | 0.0 |
| total | 8.0 | 0.0 | 5.0 |

DeepSeek 状态（`state-check.json`）：**一致**；没有未覆盖句子
- `audit`：finished，窗口 4，句 90，calls 4／hits 0，失败 0
- `translate`：finished，窗口 8，句 90，calls 10／hits 0，失败 0
- `trim`：finished，窗口 7，句 51，calls 7／hits 0，失败 0

Error-like log lines (first 5 per log):

- `tts-run.log`: W1030 20:27:18.203000 1 torch/utils/_pytree.py:630] <enum 'KernelPreference'> is an Enum subclass and is now natively supported by torch.compile as an opaque value type. Calling register_constant() on
- `tts-run.log`: W1030 20:27:18.216000 1 torch/utils/_pytree.py:630] <enum 'ScaleCalculationMode'> is an Enum subclass and is now natively supported by torch.compile as an opaque value type. Calling register_constant(
- `tts-run.log`: [0;93m2026-10-30 20:27:18.682581392 [W:onnxruntime:Default, device_discovery.cc:164 DiscoverDevicesForPlatform] GPU device discovery failed: device_discovery.cc:89 ReadFileContents Failed to open fil
- `tts-run.log`: ... 123 lines omitted; 3 error-like lines, 3 kept below ...
- `tts-run.log`: [line 125] W1030 20:33:55.266000 1 torch/utils/_pytree.py:630] <enum 'KernelPreference'> is an Enum subclass and is now natively supported by torch.compile as an opaque value type. Calling register_co

Not copied: 1 (none), 1 .html, 33 .json, 9 .jsonl, 1 .mp3, 181 .wav

## 20261030-flow2-es

Source: `~/SynologyDrive/GitHub/Active/sermon-video-zh-subtitles/artifacts/sentence-first-agent/20261030-flow2-es`

- outcome `outcome.json`: **track_ready_for_review** exit ? (2026-10-30T20:31:41+00:00 → 2026-10-30T20:31:44+00:00)

Timings `timings.tsv`:

| stage | computeSeconds | waitingSeconds | reworkSeconds |
|---|---|---|---|
| l3.finish | 3.0 | 0.0 | 0.0 |
| total | 3.0 | 0.0 | 0.0 |

DeepSeek 状态（`state-check.json`）：**一致**；没有未覆盖句子
- `audit`：finished，窗口 4，句 90，calls 4／hits 0，失败 0
- `translate`：finished，窗口 8，句 90，calls 10／hits 0，失败 0

Error-like log lines (first 5 per log):

- `tts-run.log`: W1030 20:29:27.971000 1 torch/utils/_pytree.py:630] <enum 'KernelPreference'> is an Enum subclass and is now natively supported by torch.compile as an opaque value type. Calling register_constant() on
- `tts-run.log`: W1030 20:29:27.984000 1 torch/utils/_pytree.py:630] <enum 'ScaleCalculationMode'> is an Enum subclass and is now natively supported by torch.compile as an opaque value type. Calling register_constant(
- `tts-run.log`: [0;93m2026-10-30 20:29:28.442151359 [W:onnxruntime:Default, device_discovery.cc:164 DiscoverDevicesForPlatform] GPU device discovery failed: device_discovery.cc:89 ReadFileContents Failed to open fil

Not copied: 1 (none), 1 .html, 24 .json, 9 .jsonl, 1 .mp3, 181 .wav
