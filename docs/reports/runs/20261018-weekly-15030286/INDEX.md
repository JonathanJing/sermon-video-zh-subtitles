# Run digest 20261018-weekly-15030286

Generated 2026-10-18T16:49:02+00:00. Redacted copies only; source hashes are in manifest.json.

## layer1-15030286-20261017

Source: `~/SynologyDrive/GitHub/Active/sermon-video-zh-subtitles/artifacts/weekend-live/layer1-15030286-20261017`

- outcome `outcome.json`: **blocked** exit ? (? → ?)
- outcome `output-rebuild-v3/outcome.json`: **succeeded** exit ? (2026-10-18T02:47:53.672654+00:00 → ?)
- summary `output-rebuild-v3/summary.json`: **english_source_candidate**
- summary `output-v2/summary.json`: **english_source_candidate**
- source budget `.jobs-v2.source-budget/source-budget.json`: 76 of 76 requests returned; reserved US$22.63; estimated US$5.50 over 65 priced; cost unknown: missing_or_invalid_token_counts ×11; invoice not verified
- source budget `.jobs.source-budget/source-budget.json`: 11 of 11 requests returned; reserved US$0.14; cost unknown: missing_or_invalid_token_counts ×11; invoice not verified
- source budget `.output-rebuild-v3.judge-budget/source-budget.json`: 65 of 65 requests returned; reserved US$22.52; estimated US$5.46 over 65 priced; invoice not verified

Error-like log lines (first 5 per log):

- `execute-stderr.log`: Traceback (most recent call last):
- `execute-stderr.log`: raise ValueError('Ambiguous numeric reference: configure its exact token in spoken forms before MFA')
- `execute-stderr.log`: ValueError: Ambiguous numeric reference: configure its exact token in spoken forms before MFA
- `execute-v2-stderr.log`: Traceback (most recent call last):
- `execute-v2-stderr.log`: if not session_id or not owner: raise SessionError('spark_exclusive_session_required')
- `execute-v2-stderr.log`: tongxing_production.compute.spark_exclusive_session.SessionError: spark_exclusive_session_required
- `output/accounting/operations.log`: 2026-10-18T02:10:06.230518+00:00 ERROR run=1e6f9d72d26141c2a438ff3245a049b3 stage_finished workflowId=39e45884207845d38e2c0e7676256584 stage=unified_source_preparation spanId=285ea443af3044d1b35515bc1
- `output/accounting/operations.log`: 2026-10-18T02:10:06.232256+00:00 ERROR run=1e6f9d72d26141c2a438ff3245a049b3 workflow_finished workflowId=39e45884207845d38e2c0e7676256584 status=failed
- `output/accounting/operations.log`: 2026-10-18T02:10:06.232424+00:00 ERROR run=1e6f9d72d26141c2a438ff3245a049b3 run_finished workflowId=39e45884207845d38e2c0e7676256584 status=failed
- `output-v2/accounting/operations.log`: 2026-10-18T02:11:42.762248+00:00 ERROR run=75ac391da24e4d2fa6cd1d9e381158b8 stage_finished workflowId=5f34ac2c7f414198b5517b55ed96072c stage=unified_source_preparation spanId=4bbfd720b84c479db63b1b96c
- `output-v2/accounting/operations.log`: 2026-10-18T02:11:42.763852+00:00 ERROR run=75ac391da24e4d2fa6cd1d9e381158b8 workflow_finished workflowId=5f34ac2c7f414198b5517b55ed96072c status=failed
- `output-v2/accounting/operations.log`: 2026-10-18T02:11:42.764011+00:00 ERROR run=75ac391da24e4d2fa6cd1d9e381158b8 run_finished workflowId=5f34ac2c7f414198b5517b55ed96072c status=failed

Not copied: 6 .csv, 514 .json, 2 .jsonl, 291 .lock, 1 .md, 24 .wav

## text-qc-15030286-20261018

Source: `~/SynologyDrive/GitHub/Active/sermon-video-zh-subtitles/artifacts/weekend-live/text-qc-15030286-20261018`

- outcome `state-es/asr-calls/primary/08e1795f64b7b88efd997924e01aae67f9c30880b6625aabe8ae2bd95a9b4a4c/outcome.json`: **completed** exit ? (? → ?)
- outcome `state-es/asr-calls/primary/1cdb27a5d9920bce6ceb51162e36c5da9c93dee268dd4e0ce5f91a5f1dba9f61/outcome.json`: **completed** exit ? (? → ?)
- outcome `state-es/asr-calls/primary/7468117aeed5364ed84abdce85660a275ac80542db9086f6418b1940e04ea54a/outcome.json`: **completed** exit ? (? → ?)
- outcome `state-es/asr-calls/primary/7a31e6d3c43aef710f12331ef13a74d00a03abb9889bfc1c3a43ef776e7e9177/outcome.json`: **completed** exit ? (? → ?)
- outcome `state-es/asr-calls/primary/a49f193801dc775571131d05af962a5e12604eaf37accdd04c276ab734b16b9d/outcome.json`: **completed** exit ? (? → ?)
- outcome `state-es/asr-calls/primary/a9032b6292bce92e51ded3ebdb3b390c89a3ebb6dc8c0e2bf7e2a7f8c1d116ef/outcome.json`: **completed** exit ? (? → ?)
- outcome `state-es/asr-calls/primary/b7b81291b94855b5f734cc0acf05975278b6028eb5371373dabd3a4ab5e37dba/outcome.json`: **completed** exit ? (? → ?)
- outcome `state-es/asr-calls/primary/c9e1d7ecd8f9bcb5d24caf5228d2ead3e1c3733b068446943a0e1088101e7686/outcome.json`: **completed** exit ? (? → ?)
- outcome `state-ko/asr-calls/primary/050b4a0c17f99cda18346f045dfc0ad77a813c9305bc4e3b9bf31a17eb191e01/outcome.json`: **completed** exit ? (? → ?)
- outcome `state-ko/asr-calls/primary/1d513947a2558204290b737c497385471eb4084f13c6a8077a0dc845449adebd/outcome.json`: **completed** exit ? (? → ?)
- outcome `state-ko/asr-calls/primary/6ffa9dcec1cf5b9053314a9ab464b1e588adace951f2d5cef1cf645e0259c9e3/outcome.json`: **completed** exit ? (? → ?)
- outcome `state-ko/asr-calls/primary/8cff3b121b05367cef4fe4aa36cdf14760890139bbd984df75ef93020dacb15f/outcome.json`: **completed** exit ? (? → ?)
- outcome `state-ko/asr-calls/primary/ad88585629a2a16c5ef66a289abc72fd4e6af01660191df4f39c1ab5b589673a/outcome.json`: **completed** exit ? (? → ?)
- outcome `state-ko/asr-calls/primary/aeae2885a3d3fb016bc6a936ac6bb4eca2549fc45f00050ad664f00f77183658/outcome.json`: **completed** exit ? (? → ?)
- outcome `state-ko/asr-calls/primary/c99a8c2b3f47afd5c5daec2daf34b214362a636cbf8202f092e9efe40775cf02/outcome.json`: **completed** exit ? (? → ?)
- outcome `state-ko/asr-calls/primary/e556bb73468d0cbb77017a6ae5d0db74f1a87d191ace5b5caea2bbd6eba0d43d/outcome.json`: **completed** exit ? (? → ?)
- outcome `state-ko/asr-calls/primary/ebf7dae6f72852e252ef1c5f9a0785b9dc13799e209c8abe6af1037d0fda76e7/outcome.json`: **completed** exit ? (? → ?)
- outcome `state-ko/asr-calls/primary/fdf86bc45fa9670106621337160254038ae02a448311f76a7baa67c3afbcd47f/outcome.json`: **completed** exit ? (? → ?)
- outcome `state-zh-Hans/asr-calls/primary/23e177bf7b7e505c14e187e128aa009676cb171fe8ecef28ac17714a11e3151a/outcome.json`: **completed** exit ? (? → ?)
- outcome `state-zh-Hans/asr-calls/primary/2c377fd881710196da8ca4565732ae240551e2490651a415412dabca7ce508f3/outcome.json`: **completed** exit ? (? → ?)
- outcome `state-zh-Hans/asr-calls/primary/3081581ed6267d684e7e1683827179480cbd8bcfcb72ed90f5bffe6ef9d39307/outcome.json`: **completed** exit ? (? → ?)
- outcome `state-zh-Hans/asr-calls/primary/338d794399b72b83a17cfb7f7202bc93f395f2fb2069ad6ddedc99892f2a044a/outcome.json`: **completed** exit ? (? → ?)
- outcome `state-zh-Hans/asr-calls/primary/3def727ef19c81d9f01fae53ba95749ca73cbaa03852f085a18aafecccca0244/outcome.json`: **completed** exit ? (? → ?)
- outcome `state-zh-Hans/asr-calls/primary/4449b7fcf8b96b3cabe036fd0cb205133bd0781a7274601d70798902dbde81a0/outcome.json`: **completed** exit ? (? → ?)
- outcome `state-zh-Hans/asr-calls/primary/546b2cb6ae1e66e598c419c30ea4a3b09b2dbaf3fd0d387c33eedf19c7206d85/outcome.json`: **completed** exit ? (? → ?)
- outcome `state-zh-Hans/asr-calls/primary/6a8d1305b177a5b22073bb3e9c12ffa662f3b1448e5276243dcf2019638da3e9/outcome.json`: **completed** exit ? (? → ?)
- outcome `state-zh-Hans/asr-calls/primary/7a884630932fe2775e7e791bed1767f53cada32d571f735bae133a191435a95d/outcome.json`: **completed** exit ? (? → ?)
- outcome `state-zh-Hans/asr-calls/primary/81ed988b748b26c0ca3f64a0e245dc706c8f0067c71e9d8a50a10a6c25580e28/outcome.json`: **completed** exit ? (? → ?)
- outcome `state-zh-Hans/asr-calls/primary/878d45f70ca7ca9e08ff98a6b8dbae634315ccaa07b9ad8988c84b55bbd360db/outcome.json`: **completed** exit ? (? → ?)
- outcome `state-zh-Hans/asr-calls/primary/a490a7f21e385f2166325a2aab10df0b67d48f67d9ee51ae1224a3fcaad0b0fb/outcome.json`: **completed** exit ? (? → ?)
- outcome `state-zh-Hans/asr-calls/primary/ae39d97511597bf81c37dc9ea358a2f5301031f8a81bb99db36a602cffdd3961/outcome.json`: **completed** exit ? (? → ?)
- outcome `state-zh-Hans/asr-calls/primary/afb317f7629093099caef94a731e477be66f715ec29d2eb841db122f1e3023b7/outcome.json`: **completed** exit ? (? → ?)
- outcome `state-zh-Hans/asr-calls/primary/c0222d67a0b380eaf08f88ab51d26b7ffac49aaa57d1a56ccec944097d9e9ffe/outcome.json`: **completed** exit ? (? → ?)
- outcome `state-zh-Hans/asr-calls/primary/c52d227f43eaafb71c7a24c8236714d40041c6fc25893685fac42de6cf33ec18/outcome.json`: **completed** exit ? (? → ?)
- outcome `state-zh-Hans/asr-calls/primary/cbc3f91ffa858e5a42ff685e6ea7422444c2011b493587949a2d9e8dce67e5f7/outcome.json`: **completed** exit ? (? → ?)
- summary `out-es/summary.json` es: **requires_repair** (text QC failed; repair the failed groups in a new candidate revision)
- summary `out-es-es-g2-acc/summary.json` es: **text_waiver_issued**
- summary `out-ko-ko-g2/summary.json` ko: **requires_repair** (text QC failed; repair the failed groups in a new candidate revision)
- summary `out-ko-ko-g2-acc/summary.json` ko: **text_waiver_issued**
- summary `out-zh-Hans/summary.json` zh-Hans: **blocked_prior_failure** (failed groups are unchanged; repair them in a new candidate revision)
- summary `out-zh-Hans-zh-g1/summary.json` zh-Hans: **text_waiver_issued**
- summary `out-zh-Hans-zh-g1-acc2/summary.json` zh-Hans: **text_waiver_issued**

Timings `out-es/timings.tsv`:

| stage | status | seconds |
|---|---|---|
| discover | pass | 0.0 |
| es.text-qc.prefetch | pass | 535.0 |
| es.text-qc | pass | 107.4 |

Timings `out-es-es-g2-acc/timings.tsv`:

| stage | status | seconds |
|---|---|---|
| discover | pass | 0.0 |
| es.text-qc.prefetch | pass | 426.8 |
| es.text-qc | pass | 106.1 |
| es.calibration.prefetch | pass | 936.6 |
| es.calibration | pass | 202.9 |
| es.text-waiver | pass | 0.1 |

Timings `out-ko-ko-g2/timings.tsv`:

| stage | status | seconds |
|---|---|---|
| discover | pass | 0.0 |
| ko.text-qc.prefetch | pass | 567.4 |
| ko.text-qc | pass | 106.3 |

Timings `out-ko-ko-g2-acc/timings.tsv`:

| stage | status | seconds |
|---|---|---|
| discover | pass | 0.0 |
| ko.calibration.prefetch | pass | 925.2 |
| ko.calibration | pass | 188.9 |
| ko.text-waiver | pass | 0.1 |

Timings `out-zh-Hans/timings.tsv`:

| stage | status | seconds |
|---|---|---|
| discover | pass | 0.0 |
| zh-Hans.text-qc.prefetch | pass | 579.8 |
| zh-Hans.text-qc | pass | 114.1 |
| discover | pass | 0.0 |

Timings `out-zh-Hans-zh-g1/timings.tsv`:

| stage | status | seconds |
|---|---|---|
| discover | pass | 0.0 |
| zh-Hans.text-qc.prefetch | pass | 446.5 |
| zh-Hans.text-qc | pass | 107.0 |
| discover | pass | 0.0 |
| zh-Hans.calibration.prefetch | pass | 260.1 |
| zh-Hans.calibration | pass | 193.3 |
| zh-Hans.text-waiver | pass | 0.1 |

Timings `out-zh-Hans-zh-g1-acc2/timings.tsv`:

| stage | status | seconds |
|---|---|---|
| discover | pass | 0.0 |
| zh-Hans.calibration.prefetch | pass | 878.5 |
| zh-Hans.calibration | pass | 191.1 |
| zh-Hans.text-waiver | pass | 0.1 |
- source budget `plan-qc-es-v2/qc-es/.api-budget/source-budget.json`: 1450 of 1450 requests returned; reserved US$14.39; estimated US$1.79 over 1379 priced; cost unknown: missing_or_invalid_token_counts ×71; invoice not verified
- source budget `plan-qc-ko-v2/qc-ko/.api-budget/source-budget.json`: 1430 of 1430 requests returned; reserved US$14.97; estimated US$2.14 over 1331 priced; cost unknown: missing_or_invalid_token_counts ×99; invoice not verified
- source budget `plan-qc-zh-Hans-v2/qc-zh-Hans/.api-budget/source-budget.json`: 1345 of 1345 requests returned; reserved US$14.62; estimated US$2.14 over 1334 priced; cost unknown: missing_or_invalid_token_counts ×11; invoice not verified

Error-like log lines (first 5 per log):

- `text-qc-es.log`: "reason": "text QC failed; repair the failed groups in a new candidate revision",
- `text-qc-zh-Hans.log`: "reason": "failed groups are unchanged; repair them in a new candidate revision",

Not copied: 4435 .json, 4241 .lock, 7 .md, 1 .py, 35 .wav

## audio-qc-15030286-20261018

Source: `~/SynologyDrive/GitHub/Active/sermon-video-zh-subtitles/artifacts/weekend-live/audio-qc-15030286-20261018`

- summary `es-c1/summary.json` es: **requires_repair** (audio QC failed; re-render the failed units as the repair ladder says)
- summary `es-s43/summary.json` es: **requires_repair** (audio QC failed; re-render the failed units as the repair ladder says)
- summary `es-s43-acc/summary.json` es: **audio_waiver_issued**
- summary `ko-c1/summary.json` ko: **requires_repair** (audio QC failed; re-render the failed units as the repair ladder says)
- summary `ko-s43/summary.json` ko: **requires_repair** (audio QC failed; re-render the failed units as the repair ladder says)
- summary `ko-s43-acc/summary.json` ko: **audio_waiver_issued**
- summary `zh-Hans-c1/summary.json` zh-Hans: **requires_repair** (audio QC failed; re-render the failed units as the repair ladder says)
- summary `zh-Hans-c1-acc/summary.json` zh-Hans: **audio_waiver_issued**
- summary `zh-Hans-c1-failed-mirror-1028/summary.json` zh-Hans: **blocked** (speech job input englishSourcePackage is missing or changed; speech job input anchorManifest is missing or changed; speech job input targetLanguageCandidate is missing or changed; speech job input tar)

Timings `es-c1/timings.tsv`:

| stage | status | seconds |
|---|---|---|
| discover | pass | 2.2 |
| es.track-check | pass | 6.9 |
| es.secondary-asr | pass | 5.2 |
| es.audio-qc | pass | 5.7 |

Timings `es-s43/timings.tsv`:

| stage | status | seconds |
|---|---|---|
| discover | pass | 4.4 |
| es.track-check | pass | 7.4 |
| es.secondary-asr | pass | 5.4 |
| es.audio-qc | pass | 5.9 |

Timings `es-s43-acc/timings.tsv`:

| stage | status | seconds |
|---|---|---|
| discover | pass | 2.7 |
| es.track-check | pass | 6.9 |
| es.calibration.prefetch | pass | 178.7 |
| es.calibration | pass | 1223.1 |
| es.audio-waiver | pass | 0.2 |

Timings `ko-c1/timings.tsv`:

| stage | status | seconds |
|---|---|---|
| discover | pass | 2.7 |
| ko.track-check | pass | 8.1 |
| ko.secondary-asr | pass | 8.9 |
| ko.audio-qc | pass | 7.9 |

Timings `ko-s43/timings.tsv`:

| stage | status | seconds |
|---|---|---|
| discover | pass | 2.0 |
| ko.track-check | pass | 7.5 |
| ko.secondary-asr | pass | 9.8 |
| ko.audio-qc | pass | 8.2 |

Timings `ko-s43-acc/timings.tsv`:

| stage | status | seconds |
|---|---|---|
| discover | pass | 1.9 |
| ko.track-check | pass | 7.4 |
| ko.calibration.prefetch | pass | 171.0 |
| ko.calibration | pass | 1610.9 |
| ko.audio-waiver | pass | 1.4 |

Timings `zh-Hans-c1/timings.tsv`:

| stage | status | seconds |
|---|---|---|
| discover | pass | 0.4 |
| discover | pass | 0.4 |
| zh-Hans.track-check | pass | 7.2 |
| zh-Hans.secondary-asr | pass | 4.6 |
| zh-Hans.audio-qc | pass | 5.7 |

Timings `zh-Hans-c1-acc/timings.tsv`:

| stage | status | seconds |
|---|---|---|
| discover | pass | 1.3 |
| zh-Hans.track-check | pass | 6.8 |
| zh-Hans.calibration.prefetch | pass | 174.8 |
| zh-Hans.calibration | pass | 1380.3 |
| zh-Hans.audio-waiver | pass | 0.1 |

Timings `zh-Hans-c1-failed-mirror-1028/timings.tsv`:

| stage | status | seconds |
|---|---|---|
| discover | pass | 0.4 |

Error-like log lines (first 5 per log):

- `es-c1/spark-driver.log`: "reason": "audio QC failed; re-render the failed units as the repair ladder says",
- `es-s43/spark-driver.log`: "reason": "audio QC failed; re-render the failed units as the repair ladder says",
- `es-s43-acc/spark-driver.log`: W1018 14:15:27.854000 49 torch/utils/_pytree.py:630] <enum 'KernelPreference'> is an Enum subclass and is now natively supported by torch.compile as an opaque value type. Calling register_constant() o
- `es-s43-acc/spark-driver.log`: W1018 14:15:27.866000 49 torch/utils/_pytree.py:630] <enum 'ScaleCalculationMode'> is an Enum subclass and is now natively supported by torch.compile as an opaque value type. Calling register_constant
- `es-s43-acc/spark-driver.log`: [0;93m2026-10-18 14:15:28.327932118 [W:onnxruntime:Default, device_discovery.cc:164 DiscoverDevicesForPlatform] GPU device discovery failed: device_discovery.cc:89 ReadFileContents Failed to open fil
- `ko-c1/spark-driver.log`: "reason": "audio QC failed; re-render the failed units as the repair ladder says",
- `ko-s43/spark-driver.log`: "reason": "audio QC failed; re-render the failed units as the repair ladder says",
- `ko-s43-acc/spark-driver.log`: W1018 15:28:04.479000 49 torch/utils/_pytree.py:630] <enum 'KernelPreference'> is an Enum subclass and is now natively supported by torch.compile as an opaque value type. Calling register_constant() o
- `ko-s43-acc/spark-driver.log`: W1018 15:28:04.490000 49 torch/utils/_pytree.py:630] <enum 'ScaleCalculationMode'> is an Enum subclass and is now natively supported by torch.compile as an opaque value type. Calling register_constant
- `ko-s43-acc/spark-driver.log`: [0;93m2026-10-18 15:28:04.915372662 [W:onnxruntime:Default, device_discovery.cc:164 DiscoverDevicesForPlatform] GPU device discovery failed: device_discovery.cc:89 ReadFileContents Failed to open fil
- `zh-Hans-c1/spark-driver.log`: "reason": "audio QC failed; re-render the failed units as the repair ladder says",
- `zh-Hans-c1-acc/spark-driver.log`: W1018 13:41:23.105000 50 torch/utils/_pytree.py:630] <enum 'KernelPreference'> is an Enum subclass and is now natively supported by torch.compile as an opaque value type. Calling register_constant() o
- `zh-Hans-c1-acc/spark-driver.log`: W1018 13:41:23.129000 50 torch/utils/_pytree.py:630] <enum 'ScaleCalculationMode'> is an Enum subclass and is now natively supported by torch.compile as an opaque value type. Calling register_constant
- `zh-Hans-c1-acc/spark-driver.log`: [0;93m2026-10-18 13:41:23.674890724 [W:onnxruntime:Default, device_discovery.cc:164 DiscoverDevicesForPlatform] GPU device discovery failed: device_discovery.cc:89 ReadFileContents Failed to open fil

Not copied: 57 .json, 9 .lock, 3 .md

## study-15030286-20261018

Source: `~/SynologyDrive/GitHub/Active/sermon-video-zh-subtitles/artifacts/weekend-live/study-15030286-20261018`


Not copied: 27 .json, 1 .md, 3 .py

## layer4-15030286-20261018

Source: `~/SynologyDrive/GitHub/Active/sermon-video-zh-subtitles/artifacts/weekend-live/layer4-15030286-20261018`


Error-like log lines (first 5 per log):

- `feedback-sync/deploy.log`: timeoutSeconds: 15

Not copied: 5 .cache, 37 .css, 152 .html, 9 .jpg, 58 .js, 936 .json, 5 .lock, 467 .mjs, 462 .mp3, 36 .pdf, 206 .png, 3 .py, 2 .sh, 18 .srt, 42 .svg, 1 .txt, 1 .zip

## layer1-broadcast-20261018

Source: `~/SynologyDrive/GitHub/Active/sermon-video-zh-subtitles/artifacts/weekend-live/layer1-broadcast-20261018`

- summary `output/summary.json`: **english_source_candidate**
- source budget `.jobs.source-budget/source-budget.json`: 79 of 79 requests returned; reserved US$23.18; estimated US$5.56 over 67 priced; cost unknown: missing_or_invalid_token_counts ×12; invoice not verified

Error-like log lines (first 5 per log):

- `execute-stderr-2.log`: Traceback (most recent call last):
- `execute-stderr-2.log`: raise ValueError('Ambiguous numeric reference: configure its exact token in spoken forms before MFA')
- `execute-stderr-2.log`: ValueError: Ambiguous numeric reference: configure its exact token in spoken forms before MFA
- `execute-stderr-3.log`: Traceback (most recent call last):
- `execute-stderr-3.log`: raise ValueError(code)
- `execute-stderr-3.log`: ValueError: source_immutable_artifact_changed:mfa-preflight.json
- `execute-stderr.log`: Traceback (most recent call last):
- `execute-stderr.log`: raise ValueError(code)
- `execute-stderr.log`: ValueError: source_text_review_required
- `output/accounting/operations.log`: 2026-10-18T14:06:13.671545+00:00 ERROR run=19c785b3dc684ffb9e84e0d25fc21ee4 stage_finished workflowId=402b8119c9eb41ecb046d690adebd804 stage=unified_source_preparation spanId=25ac3d1baf994047bbd9508d0
- `output/accounting/operations.log`: 2026-10-18T14:06:13.672948+00:00 ERROR run=19c785b3dc684ffb9e84e0d25fc21ee4 workflow_finished workflowId=402b8119c9eb41ecb046d690adebd804 status=failed
- `output/accounting/operations.log`: 2026-10-18T14:06:13.673175+00:00 ERROR run=19c785b3dc684ffb9e84e0d25fc21ee4 run_finished workflowId=402b8119c9eb41ecb046d690adebd804 status=failed
- `output/accounting/operations.log`: 2026-10-18T14:12:22.874560+00:00 ERROR run=8ab014a6c3004bd5b429ab0127a22da7 stage_finished workflowId=e55b1e1fc8494d4892cd3906b9e599fb stage=unified_source_preparation spanId=3ef603b75f4747c4887855bf1
- `output/accounting/operations.log`: 2026-10-18T14:12:22.876071+00:00 ERROR run=8ab014a6c3004bd5b429ab0127a22da7 workflow_finished workflowId=e55b1e1fc8494d4892cd3906b9e599fb status=failed
- `output-failed-start0/accounting/operations.log`: 2026-10-18T14:05:01.270535+00:00 ERROR run=c34b617f39e641e28563110951e47453 stage_finished workflowId=c82533512b15446a8a493208f5017830 stage=unified_source_preparation spanId=406b793d176749f38bc9b1b3d
- `output-failed-start0/accounting/operations.log`: 2026-10-18T14:05:01.272560+00:00 ERROR run=c34b617f39e641e28563110951e47453 workflow_finished workflowId=c82533512b15446a8a493208f5017830 status=failed
- `output-failed-start0/accounting/operations.log`: 2026-10-18T14:05:01.272760+00:00 ERROR run=c34b617f39e641e28563110951e47453 run_finished workflowId=c82533512b15446a8a493208f5017830 status=failed
- `output-failed-start0/execute-stderr.log`: Traceback (most recent call last):
- `output-failed-start0/execute-stderr.log`: raise ValueError(code)
- `output-failed-start0/execute-stderr.log`: ValueError: source_extracted_audio_duration_changed

Not copied: 6 .csv, 274 .json, 3 .jsonl, 151 .lock, 1 .md, 13 .wav
