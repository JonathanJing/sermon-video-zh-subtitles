# Run digest 20261013-post-merge-start-tools

Generated 2026-10-13T22:45:01+00:00. Redacted copies only; source hashes are in manifest.json.

## clip-test-20261013-merged

Source: `~/SynologyDrive/GitHub/Active/sermon-video-zh-subtitles/artifacts/clip-test-20261013-merged`

- outcome `textqc-es/state/asr-calls/primary/326763a3984e94d52538203e5ea0472d1e013c30f783dadf9dc82c73126f491a/outcome.json`: **completed** exit ? (? → ?)
- outcome `textqc-es/state/asr-calls/primary/39ecd75897c84a78bca8597da50bb180461e99872b15edd383d1f299ad74029c/outcome.json`: **completed** exit ? (? → ?)
- outcome `textqc-es/state/asr-calls/primary/5cd26f994bff54df88b0f0a09d62e56d67819ff7a1694985aa8b103abfd304f1/outcome.json`: **completed** exit ? (? → ?)
- outcome `textqc-es/state/asr-calls/primary/9d4ae260153806a13edc101468f9635538741680c851748f852a6fd1004e8590/outcome.json`: **completed** exit ? (? → ?)
- outcome `textqc-zh-Hans/state/asr-calls/primary/18c52d57881d7deb6a2a5b41366438fafc897e1b0d765ce43548dca98b7c690c/outcome.json`: **completed** exit ? (? → ?)
- outcome `textqc-zh-Hans/state/asr-calls/primary/337f9a0712fedb279acbc260da356087d9019e7ef9e6bd67fb8101dc1191b9ab/outcome.json`: **completed** exit ? (? → ?)
- outcome `textqc-zh-Hans/state/asr-calls/primary/420965a7fb96ec75533c81a25b25a1c479af06d5510b2d4d07a294743b6e1458/outcome.json`: **completed** exit ? (? → ?)
- outcome `textqc-zh-Hans/state/asr-calls/primary/5a24e5a26784edb908c31e3b32cd49e15e3b5429f81f00b8b40ba18f6339b2dc/outcome.json`: **completed** exit ? (? → ?)
- outcome `textqc-zh-Hans/state/asr-calls/primary/6b1aadc59d7b50d79585a6e21288eda1c5520e8d0caec162ea6f5eec5b81599d/outcome.json`: **completed** exit ? (? → ?)
- outcome `textqc-zh-Hans/state/asr-calls/primary/7ca60f2ef521ef97dc4f61596395e6d762608983663f06797e0d89d3fd85148a/outcome.json`: **completed** exit ? (? → ?)
- outcome `textqc-zh-Hans/state/asr-calls/primary/890998ce56ff051c6d66a84afedec96dde5b4ba2ae09bcf76a21f178dcc02d14/outcome.json`: **completed** exit ? (? → ?)
- outcome `textqc-zh-Hans/state/asr-calls/primary/a24c24e6f63beb3b7dd83b4c4a68719610540135f4d590e9900eef84acbb117e/outcome.json`: **completed** exit ? (? → ?)
- outcome `textqc-zh-Hans/state/asr-calls/primary/d8a82f2ef2e9ff50bfe9d04e4386f536ecff1c3056a4010e95187c865895c97c/outcome.json`: **completed** exit ? (? → ?)
- summary `aqc/es/summary.json` es: **audio_waiver_issued**
- summary `aqc/ko/summary.json` ko: **requires_repair** (audio QC failed; re-render the failed units as the repair ladder says)
- summary `aqc/zh-Hans/summary.json` zh-Hans: **audio_waiver_issued**
- summary `textqc-es/out/summary.json` es: **text_waiver_issued**
- summary `textqc-ko/out/summary.json` ko: **text_waiver_issued**
- summary `textqc-zh-Hans/out/summary.json` zh-Hans: **requires_repair** (text QC failed; repair the failed groups in a new candidate revision)
- summary `textqc-zh-Hans-r2/out/summary.json` zh-Hans: **text_waiver_issued**

Timings `aqc/es/timings.tsv`:

| stage | status | seconds |
|---|---|---|
| discover | pass | 0.0 |
| es.track-check | pass | 0.4 |
| es.secondary-asr | pass | 0.5 |
| es.audio-qc | pass | 0.2 |
| es.calibration.prefetch | pass | 3.3 |
| es.calibration | pass | 116.4 |
| es.audio-waiver | pass | 0.0 |

Timings `aqc/ko/timings.tsv`:

| stage | status | seconds |
|---|---|---|
| discover | pass | 0.0 |
| ko.track-check | pass | 0.3 |
| ko.secondary-asr | pass | 1.5 |
| ko.audio-qc | pass | 0.3 |

Timings `aqc/zh-Hans/timings.tsv`:

| stage | status | seconds |
|---|---|---|
| discover | pass | 0.0 |
| zh-Hans.track-check | pass | 0.3 |
| zh-Hans.audio-qc | pass | 0.2 |
| zh-Hans.calibration.prefetch | pass | 3.2 |
| zh-Hans.calibration | pass | 139.5 |
| zh-Hans.audio-waiver | pass | 0.0 |

Timings `textqc-es/out/timings.tsv`:

| stage | status | seconds |
|---|---|---|
| discover | pass | 0.0 |
| es.text-qc.prefetch | pass | 12.5 |
| es.text-qc | pass | 0.5 |
| es.calibration.prefetch | pass | 78.6 |
| es.calibration | pass | 3.8 |
| es.text-waiver | pass | 0.0 |

Timings `textqc-ko/out/timings.tsv`:

| stage | status | seconds |
|---|---|---|
| discover | pass | 0.0 |
| ko.text-qc.prefetch | pass | 12.4 |
| ko.text-qc | pass | 0.5 |
| ko.calibration.prefetch | pass | 81.1 |
| ko.calibration | pass | 3.5 |
| ko.text-waiver | pass | 0.0 |

Timings `textqc-zh-Hans/out/timings.tsv`:

| stage | status | seconds |
|---|---|---|
| discover | pass | 0.0 |
| zh-Hans.text-qc.prefetch | pass | 18.1 |
| zh-Hans.text-qc | pass | 0.5 |

Timings `textqc-zh-Hans-r2/out/timings.tsv`:

| stage | status | seconds |
|---|---|---|
| discover | pass | 0.0 |
| zh-Hans.text-qc.prefetch | pass | 14.0 |
| zh-Hans.text-qc | pass | 0.5 |
| zh-Hans.calibration.prefetch | pass | 97.1 |
| zh-Hans.calibration | pass | 3.5 |
| zh-Hans.text-waiver | pass | 0.0 |

Timings `timings.tsv`:

| zh-Hans.text-qc | fail(1) | 1 | 19 |
|---|---|---|---|
| zh-Hans.text-qc | pass | 1 | 115 |
| ko.text-qc | pass | 1 | 98 |
| ko.job | pass | 105 | 1 |
| ko.render | fail(1) | 106 | 86 |
| ko.compact | pass | 192 | 17 |
| ko.screen | pass | 209 | 40 |
| ko.package | pass | 249 | 3 |
| ko.audio-qc | fail(1) | 253 | 23 |
| zh-Hans.job | pass | 2 | 1 |
| zh-Hans.render | fail(1) | 3 | 84 |
| zh-Hans.compact | pass | 87 | 16 |
| zh-Hans.screen | pass | 103 | 35 |
| zh-Hans.package | pass | 138 | 3 |
| zh-Hans.audio-qc | pass | 142 | 154 |
| es.text-qc | pass | 0 | 96 |
| es.job | pass | 99 | 0 |
| es.render | fail(1) | 99 | 87 |
| es.compact | pass | 186 | 17 |
| es.screen | pass | 203 | 39 |
| es.package | pass | 242 | 3 |
| es.audio-qc | pass | 246 | 131 |

Failed stages: `ko.render`, `ko.audio-qc`, `zh-Hans.render`, `es.render`
- source budget `plans/qc-es/qc-es/.api-budget/source-budget.json`: 240 of 240 requests returned; reserved US$2.31; estimated US$0.30 over 220 priced; cost unknown: missing_or_invalid_token_counts ×20; invoice not verified
- source budget `plans/qc-ko/qc-ko/.api-budget/source-budget.json`: 215 of 215 requests returned; reserved US$2.31; estimated US$0.36 over 214 priced; cost unknown: missing_or_invalid_token_counts ×1; invoice not verified
- source budget `plans/qc-zh-Hans/qc-zh-Hans/.api-budget/source-budget.json`: 260 of 260 requests returned; reserved US$2.65; estimated US$0.41 over 235 priced; cost unknown: missing_or_invalid_token_counts ×25; invoice not verified

Error-like log lines (first 5 per log):

- `aqc/es/spark-driver.log`: W1013 22:32:29.366000 49 torch/utils/_pytree.py:630] <enum 'KernelPreference'> is an Enum subclass and is now natively supported by torch.compile as an opaque value type. Calling register_constant() o
- `aqc/es/spark-driver.log`: W1013 22:32:29.383000 49 torch/utils/_pytree.py:630] <enum 'ScaleCalculationMode'> is an Enum subclass and is now natively supported by torch.compile as an opaque value type. Calling register_constant
- `aqc/es/spark-driver.log`: [0;93m2026-10-13 22:32:29.789061109 [W:onnxruntime:Default, device_discovery.cc:164 DiscoverDevicesForPlatform] GPU device discovery failed: device_discovery.cc:89 ReadFileContents Failed to open fil
- `aqc/ko/spark-driver.log`: "reason": "audio QC failed; re-render the failed units as the repair ladder says",
- `aqc/zh-Hans/spark-driver.log`: W1013 22:25:50.219000 48 torch/utils/_pytree.py:630] <enum 'KernelPreference'> is an Enum subclass and is now natively supported by torch.compile as an opaque value type. Calling register_constant() o
- `aqc/zh-Hans/spark-driver.log`: W1013 22:25:50.234000 48 torch/utils/_pytree.py:630] <enum 'ScaleCalculationMode'> is an Enum subclass and is now natively supported by torch.compile as an opaque value type. Calling register_constant
- `aqc/zh-Hans/spark-driver.log`: [0;93m2026-10-13 22:25:50.684019492 [W:onnxruntime:Default, device_discovery.cc:164 DiscoverDevicesForPlatform] GPU device discovery failed: device_discovery.cc:89 ReadFileContents Failed to open fil
- `chain-merged-es.log`: zh-Hans.text-qc	fail(1)	1	19
- `chain-merged-es.log`: ko.render	fail(1)	106	86
- `chain-merged-es.log`: ko.audio-qc	fail(1)	253	23
- `chain-merged-es.log`: zh-Hans.render	fail(1)	3	84
- `chain-merged-es.log`: es.render	fail(1)	99	87
- `chain-merged-koes.log`: ko audio requires_repair ['translation-chunk-0005-u007'] None audio QC failed; re-render the failed units as the repair ladder says
- `chain-merged-koes.log`: zh-Hans.text-qc	fail(1)	1	19
- `chain-merged-koes.log`: ko.render	fail(1)	106	86
- `chain-merged-koes.log`: ko.audio-qc	fail(1)	253	23
- `chain-merged-zh.log`: session begin failed
- `chain-merged-zh.log`: zh-Hans.text-qc	fail(1)	1	19
- `chain-merged.log`: zh-Hans text requires_repair ['translation-chunk-0005-u003'] None text QC failed; repair the failed groups in a new candidate revision
- `chain-merged.log`: zh-Hans.text-qc	fail(1)	1	19
- `chain-resume-zh.log`: zh-Hans.text-qc	fail(1)	1	19
- `chain-resume-zh.log`: ko.render	fail(1)	106	86
- `chain-resume-zh.log`: ko.audio-qc	fail(1)	253	23
- `chain-resume-zh.log`: zh-Hans.render	fail(1)	3	84
- `l2/text/es/accounting/operations.log`: ... 154 lines omitted; 0 error-like lines, 0 kept below ...
- `l2/text/ko/accounting/operations.log`: ... 154 lines omitted; 0 error-like lines, 0 kept below ...
- `l2/text/zh-Hans/accounting/operations.log`: ... 154 lines omitted; 0 error-like lines, 0 kept below ...
- `l2-zh-r2/text/zh-Hans/accounting/operations.log`: ... 154 lines omitted; 0 error-like lines, 0 kept below ...
- `l3/es/spark-es-c-m/spark-output/screen-v1.log`: W1013 22:30:58.528000 1 torch/utils/_pytree.py:630] <enum 'KernelPreference'> is an Enum subclass and is now natively supported by torch.compile as an opaque value type. Calling register_constant() on
- `l3/es/spark-es-c-m/spark-output/screen-v1.log`: W1013 22:30:58.542000 1 torch/utils/_pytree.py:630] <enum 'ScaleCalculationMode'> is an Enum subclass and is now natively supported by torch.compile as an opaque value type. Calling register_constant(
- `l3/es/spark-output/render.log`: [0;93m2026-10-13 22:29:24.432655510 [W:onnxruntime:Default, device_discovery.cc:164 DiscoverDevicesForPlatform] GPU device discovery failed: device_discovery.cc:89 ReadFileContents Failed to open fil
- `l3/es/spark-output/render.log`: [0;93m2026-10-13 22:29:24.670714509 [W:onnxruntime:Default, device_discovery.cc:164 DiscoverDevicesForPlatform] GPU device discovery failed: device_discovery.cc:89 ReadFileContents Failed to open fil
- `l3/es/spark-output/render.log`: [0;93m2026-10-13 22:29:24.987280967 [W:onnxruntime:Default, device_discovery.cc:164 DiscoverDevicesForPlatform] GPU device discovery failed: device_discovery.cc:89 ReadFileContents Failed to open fil
- `l3/es/spark-output/render.log`: [0;93m2026-10-13 22:29:24.997275550 [W:onnxruntime:Default, device_discovery.cc:164 DiscoverDevicesForPlatform] GPU device discovery failed: device_discovery.cc:89 ReadFileContents Failed to open fil
- `l3/es/spark-output/render.log`: [0;93m2026-10-13 22:29:25.157370037 [W:onnxruntime:Default, device_discovery.cc:164 DiscoverDevicesForPlatform] GPU device discovery failed: device_discovery.cc:89 ReadFileContents Failed to open fil
- `l3/es/spark-output/speech-job/accounting/operations.log`: ... 97 lines omitted; 0 error-like lines, 0 kept below ...
- `l3/es/spark-output/speech-job/accounting/operations.log`: 2026-10-13T22:30:31.838865+00:00 ERROR run=960f98b5d0e9434090a5b9ae61f4b2f1 stage_finished workflowId=d88722c6cae6429f905a86d986b1c859 stage=layer3.track_assembly spanId=b3e64cec988b4c96bf1675b0ca9c39
- `l3/es/spark-output/speech-job/accounting/operations.log`: 2026-10-13T22:30:31.843050+00:00 ERROR run=960f98b5d0e9434090a5b9ae61f4b2f1 stage_finished workflowId=d88722c6cae6429f905a86d986b1c859 stage=layer3.assemble spanId=360bdbe9e547419db2f85fff85c65330 att
- `l3/es/spark-output/speech-job/accounting/operations.log`: 2026-10-13T22:30:31.846499+00:00 ERROR run=960f98b5d0e9434090a5b9ae61f4b2f1 stage_finished workflowId=d88722c6cae6429f905a86d986b1c859 stage=layer3_formal_render spanId=e714db6d7f834723a47dbbc1c103a50
- `l3/es/spark-output/speech-job/accounting/operations.log`: 2026-10-13T22:30:31.854279+00:00 ERROR run=960f98b5d0e9434090a5b9ae61f4b2f1 workflow_finished workflowId=d88722c6cae6429f905a86d986b1c859 status=failed
- `l3/ko/spark-ko-c-m/spark-output/screen-v1.log`: W1013 22:18:40.770000 1 torch/utils/_pytree.py:630] <enum 'KernelPreference'> is an Enum subclass and is now natively supported by torch.compile as an opaque value type. Calling register_constant() on
- `l3/ko/spark-ko-c-m/spark-output/screen-v1.log`: W1013 22:18:40.783000 1 torch/utils/_pytree.py:630] <enum 'ScaleCalculationMode'> is an Enum subclass and is now natively supported by torch.compile as an opaque value type. Calling register_constant(
- `l3/ko/spark-output/render.log`: [0;93m2026-10-13 22:17:07.772732049 [W:onnxruntime:Default, device_discovery.cc:164 DiscoverDevicesForPlatform] GPU device discovery failed: device_discovery.cc:89 ReadFileContents Failed to open fil
- `l3/ko/spark-output/render.log`: [0;93m2026-10-13 22:17:07.908663624 [W:onnxruntime:Default, device_discovery.cc:164 DiscoverDevicesForPlatform] GPU device discovery failed: device_discovery.cc:89 ReadFileContents Failed to open fil
- `l3/ko/spark-output/render.log`: [0;93m2026-10-13 22:17:08.315775882 [W:onnxruntime:Default, device_discovery.cc:164 DiscoverDevicesForPlatform] GPU device discovery failed: device_discovery.cc:89 ReadFileContents Failed to open fil
- `l3/ko/spark-output/render.log`: [0;93m2026-10-13 22:17:08.383102043 [W:onnxruntime:Default, device_discovery.cc:164 DiscoverDevicesForPlatform] GPU device discovery failed: device_discovery.cc:89 ReadFileContents Failed to open fil
- `l3/ko/spark-output/render.log`: [0;93m2026-10-13 22:17:08.625735621 [W:onnxruntime:Default, device_discovery.cc:164 DiscoverDevicesForPlatform] GPU device discovery failed: device_discovery.cc:89 ReadFileContents Failed to open fil
- `l3/ko/spark-output/speech-job/accounting/operations.log`: ... 97 lines omitted; 0 error-like lines, 0 kept below ...
- `l3/ko/spark-output/speech-job/accounting/operations.log`: 2026-10-13T22:18:13.971210+00:00 ERROR run=0c766be76f8d4b70aa2ce8a99024306f stage_finished workflowId=835ba6ce16bd41a397416a8fab386aba stage=layer3.track_assembly spanId=e228e4c1bb80475598dc9e41d44b46
- `l3/ko/spark-output/speech-job/accounting/operations.log`: 2026-10-13T22:18:13.975601+00:00 ERROR run=0c766be76f8d4b70aa2ce8a99024306f stage_finished workflowId=835ba6ce16bd41a397416a8fab386aba stage=layer3.assemble spanId=0f721a766f5c482983746fa3a5a0ac47 att
- `l3/ko/spark-output/speech-job/accounting/operations.log`: 2026-10-13T22:18:13.979168+00:00 ERROR run=0c766be76f8d4b70aa2ce8a99024306f stage_finished workflowId=835ba6ce16bd41a397416a8fab386aba stage=layer3_formal_render spanId=5fd549fd6d9c4881b243b90f74af8b1
- `l3/ko/spark-output/speech-job/accounting/operations.log`: 2026-10-13T22:18:13.987047+00:00 ERROR run=0c766be76f8d4b70aa2ce8a99024306f workflow_finished workflowId=835ba6ce16bd41a397416a8fab386aba status=failed
- `l3/zh-Hans/spark-output/render.log`: [0;93m2026-10-13 22:22:51.535700873 [W:onnxruntime:Default, device_discovery.cc:164 DiscoverDevicesForPlatform] GPU device discovery failed: device_discovery.cc:89 ReadFileContents Failed to open fil
- `l3/zh-Hans/spark-output/render.log`: [0;93m2026-10-13 22:22:51.571774460 [W:onnxruntime:Default, device_discovery.cc:164 DiscoverDevicesForPlatform] GPU device discovery failed: device_discovery.cc:89 ReadFileContents Failed to open fil
- `l3/zh-Hans/spark-output/render.log`: [0;93m2026-10-13 22:22:51.955061242 [W:onnxruntime:Default, device_discovery.cc:164 DiscoverDevicesForPlatform] GPU device discovery failed: device_discovery.cc:89 ReadFileContents Failed to open fil
- `l3/zh-Hans/spark-output/render.log`: [0;93m2026-10-13 22:22:52.211297036 [W:onnxruntime:Default, device_discovery.cc:164 DiscoverDevicesForPlatform] GPU device discovery failed: device_discovery.cc:89 ReadFileContents Failed to open fil
- `l3/zh-Hans/spark-output/render.log`: [0;93m2026-10-13 22:22:52.364926944 [W:onnxruntime:Default, device_discovery.cc:164 DiscoverDevicesForPlatform] GPU device discovery failed: device_discovery.cc:89 ReadFileContents Failed to open fil
- `l3/zh-Hans/spark-output/speech-job/accounting/operations.log`: ... 97 lines omitted; 0 error-like lines, 0 kept below ...
- `l3/zh-Hans/spark-output/speech-job/accounting/operations.log`: 2026-10-13T22:23:55.622003+00:00 ERROR run=311d0d6e952e47329ec09409bb04196c stage_finished workflowId=7e440bde7fe8447faa169b8b3fb663f4 stage=layer3.track_assembly spanId=fe44b833814f411e890381dc1bffe7
- `l3/zh-Hans/spark-output/speech-job/accounting/operations.log`: 2026-10-13T22:23:55.625875+00:00 ERROR run=311d0d6e952e47329ec09409bb04196c stage_finished workflowId=7e440bde7fe8447faa169b8b3fb663f4 stage=layer3.assemble spanId=ff51ae9848bd4a75ab72f5d9ca12c758 att
- `l3/zh-Hans/spark-output/speech-job/accounting/operations.log`: 2026-10-13T22:23:55.629345+00:00 ERROR run=311d0d6e952e47329ec09409bb04196c stage_finished workflowId=7e440bde7fe8447faa169b8b3fb663f4 stage=layer3_formal_render spanId=256c0d12d66b4ae7ad1e1d7bfbb56a4
- `l3/zh-Hans/spark-output/speech-job/accounting/operations.log`: 2026-10-13T22:23:55.636837+00:00 ERROR run=311d0d6e952e47329ec09409bb04196c workflow_finished workflowId=7e440bde7fe8447faa169b8b3fb663f4 status=failed
- `l3/zh-Hans/spark-zh-Hans-c-m/spark-output/screen-v1.log`: W1013 22:24:21.835000 1 torch/utils/_pytree.py:630] <enum 'KernelPreference'> is an Enum subclass and is now natively supported by torch.compile as an opaque value type. Calling register_constant() on
- `l3/zh-Hans/spark-zh-Hans-c-m/spark-output/screen-v1.log`: W1013 22:24:21.847000 1 torch/utils/_pytree.py:630] <enum 'ScaleCalculationMode'> is an Enum subclass and is now natively supported by torch.compile as an opaque value type. Calling register_constant(
- `l4-publish.log`: Traceback (most recent call last):
- `l4-publish.log`: raise ValueError(message)
- `l4-publish.log`: ValueError: Three locales required
- `textqc-zh-Hans/textqc.log`: "reason": "text QC failed; repair the failed groups in a new candidate revision",

Not copied: 1 (none), 6 .css, 21 .csv, 1 .err, 71 .html, 1 .jpg, 11 .js, 2912 .json, 7 .jsonl, 787 .lock, 75 .mjs, 167 .mp3, 19 .mp4, 4 .pdf, 21 .png, 5 .py, 2 .sh, 112 .sha256, 2 .srt, 6 .svg, 2 .txt, 215 .wav
