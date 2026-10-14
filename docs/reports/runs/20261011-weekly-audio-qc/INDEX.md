# Run digest 20261011-weekly-audio-qc

Generated 2026-10-11T15:41:51+00:00. Redacted copies only; source hashes are in manifest.json.

## audio-qc-54475d42

Source: `~/SynologyDrive/GitHub/Active/sermon-video-zh-subtitles/artifacts/weekend-live/audio-qc-54475d42`

- summary `es-c5a/summary.json` es: **requires_repair** (audio QC failed; re-render the failed units as the repair ladder says)
- summary `es-v1/summary.json` es: **track_check_failed** (compressed_track_differs_from_pcm_master)
- summary `ko-c5/summary.json` ko: **requires_repair** (audio QC failed; re-render the failed units as the repair ladder says)
- summary `ko-c5a/summary.json` ko: **blocked_prior_failure** (failed units still have the same audio; re-render them (new seed or revised text) first)
- summary `ko-c5b/summary.json` ko: **waiver_refused** (Calibration does not allow a waiver: seeded-error detection below minimum for ['audio.dropped_key_word'])
- summary `ko-v1/summary.json` ko: **track_check_failed** (compressed_track_differs_from_pcm_master)
- summary `zh-Hans-c5/summary.json` zh-Hans: **requires_repair** (audio QC failed; re-render the failed units as the repair ladder says)
- summary `zh-Hans-c5a/summary.json` zh-Hans: **blocked_prior_failure** (failed units still have the same audio; re-render them (new seed or revised text) first)
- summary `zh-Hans-v1/summary.json` zh-Hans: **track_check_failed** (compressed_track_differs_from_pcm_master)

Timings `es-c5a/timings.tsv`:

| stage | status | seconds |
|---|---|---|
| discover | pass | 9.9 |
| es.track-check | pass | 8.3 |
| es.secondary-asr | pass | 5.6 |
| es.audio-qc | pass | 6.7 |

Timings `es-v1/timings.tsv`:

| stage | status | seconds |
|---|---|---|
| discover | pass | 32.1 |
| discover | pass | 8.7 |
| es.track-check | pass | 8.0 |

Timings `ko-c5/timings.tsv`:

| stage | status | seconds |
|---|---|---|
| discover | pass | 9.2 |
| ko.track-check | pass | 7.4 |
| ko.secondary-asr | pass | 7.1 |
| ko.audio-qc | pass | 8.1 |

Timings `ko-c5a/timings.tsv`:

| stage | status | seconds |
|---|---|---|
| discover | pass | 10.2 |
| ko.track-check | pass | 7.3 |

Timings `ko-c5b/timings.tsv`:

| stage | status | seconds |
|---|---|---|
| discover | pass | 10.1 |
| ko.track-check | pass | 7.9 |
| ko.calibration.prefetch | pass | 37.1 |
| ko.calibration | pass | 1547.9 |
| ko.audio-waiver | fail | 0.8 |

Failed stages: `ko.audio-waiver`

Timings `ko-v1/timings.tsv`:

| stage | status | seconds |
|---|---|---|
| discover | pass | 51.8 |
| discover | pass | 8.9 |
| ko.track-check | pass | 7.8 |

Timings `zh-Hans-c5/timings.tsv`:

| stage | status | seconds |
|---|---|---|
| discover | pass | 9.9 |
| zh-Hans.track-check | pass | 8.3 |
| zh-Hans.secondary-asr | pass | 2.6 |
| zh-Hans.audio-qc | pass | 6.2 |

Timings `zh-Hans-c5a/timings.tsv`:

| stage | status | seconds |
|---|---|---|
| discover | pass | 10.0 |
| zh-Hans.track-check | pass | 8.3 |

Timings `zh-Hans-v1/timings.tsv`:

| stage | status | seconds |
|---|---|---|
| discover | pass | 36.6 |
| discover | pass | 8.8 |
| zh-Hans.track-check | pass | 7.2 |

Error-like log lines (first 5 per log):

- `attempts/a1-ko-stale-marker/dispatch.log`: Traceback (most recent call last):
- `attempts/a1-ko-stale-marker/dispatch.log`: raise ValueError(message)
- `attempts/a1-ko-stale-marker/dispatch.log`: ValueError: unknown_spark_audio_qc_requires_reconciliation
- `attempts/a1-ko-stale-marker/spark-driver.log`: "reason": "failed units still have the same audio; re-render them (new seed or revised text) first",
- `attempts/a1-zh-stale-marker/dispatch.log`: Traceback (most recent call last):
- `attempts/a1-zh-stale-marker/dispatch.log`: raise ValueError(message)
- `attempts/a1-zh-stale-marker/dispatch.log`: ValueError: unknown_spark_audio_qc_requires_reconciliation
- `attempts/a1-zh-stale-marker/spark-driver.log`: "reason": "failed units still have the same audio; re-render them (new seed or revised text) first",
- `chain-accept.log`: "reason": "failed units still have the same audio; re-render them (new seed or revised text) first",
- `chain-accept.log`: "reason": "failed units still have the same audio; re-render them (new seed or revised text) first",
- `chain-accept.log`: "reason": "audio QC failed; re-render the failed units as the repair ladder says",
- `chain-accept2.log`: "reason": "failed units still have the same audio; re-render them (new seed or revised text) first",
- `chain-accept2.log`: "reason": "failed units still have the same audio; re-render them (new seed or revised text) first",
- `chain-accept2.log`: "reason": "audio QC failed; re-render the failed units as the repair ladder says",
- `chain.log`: "status": "track_check_failed",
- `chain.log`: "status": "track_check_failed",
- `chain.log`: "status": "track_check_failed",
- `es-c5/dispatch.log`: Traceback (most recent call last):
- `es-c5/dispatch.log`: raise ValueError(message)
- `es-c5/dispatch.log`: ValueError: audio package missing from the Spark mirror; rsync first
- `es-c5a/dispatch.log`: Traceback (most recent call last):
- `es-c5a/dispatch.log`: raise ValueError(message)
- `es-c5a/dispatch.log`: ValueError: unknown_spark_audio_qc_requires_reconciliation
- `es-c5a/spark-driver.log`: "reason": "audio QC failed; re-render the failed units as the repair ladder says",
- `es-v1/dispatch-a1.log`: Traceback (most recent call last):
- `es-v1/dispatch-a1.log`: if completed.returncode or response.get('error'): raise SessionError(response.get('error', 'ssh_failed_unknown'))
- `es-v1/dispatch-a1.log`: scripts.spark_exclusive_session.SessionError: competing_service_active:llama-server.service
- `es-v1/spark-driver.log`: "status": "track_check_failed",
- `ko-c5/spark-driver.log`: "reason": "audio QC failed; re-render the failed units as the repair ladder says",
- `ko-c5b/spark-driver.log`: W1011 15:30:44.109000 47 torch/utils/_pytree.py:630] <enum 'KernelPreference'> is an Enum subclass and is now natively supported by torch.compile as an opaque value type. Calling register_constant() o
- `ko-c5b/spark-driver.log`: W1011 15:30:44.121000 47 torch/utils/_pytree.py:630] <enum 'ScaleCalculationMode'> is an Enum subclass and is now natively supported by torch.compile as an opaque value type. Calling register_constant
- `ko-c5b/spark-driver.log`: [0;93m2026-10-11 15:30:44.583734752 [W:onnxruntime:Default, device_discovery.cc:164 DiscoverDevicesForPlatform] GPU device discovery failed: device_discovery.cc:89 ReadFileContents Failed to open fil
- `ko-c5b/spark-driver.log`: ko.audio-waiver	fail	0.8
- `ko-c5b/spark-driver.log`: "status": "waiver_refused",
- `ko-v1/dispatch-a1.log`: Traceback (most recent call last):
- `ko-v1/dispatch-a1.log`: if completed.returncode or response.get('error'): raise SessionError(response.get('error', 'ssh_failed_unknown'))
- `ko-v1/dispatch-a1.log`: scripts.spark_exclusive_session.SessionError: competing_service_active:llama-server.service
- `ko-v1/dispatch.log`: Traceback (most recent call last):
- `ko-v1/dispatch.log`: if completed.returncode or response.get('error'): raise SessionError(response.get('error', 'ssh_failed_unknown'))
- `ko-v1/dispatch.log`: scripts.spark_exclusive_session.SessionError: competing_service_active:llama-server.service
- `ko-v1/spark-driver.log`: "status": "track_check_failed",
- `zh-Hans-c5/spark-driver.log`: "reason": "audio QC failed; re-render the failed units as the repair ladder says",
- `zh-Hans-v1/dispatch-a1.log`: Traceback (most recent call last):
- `zh-Hans-v1/dispatch-a1.log`: if completed.returncode or response.get('error'): raise SessionError(response.get('error', 'ssh_failed_unknown'))
- `zh-Hans-v1/dispatch-a1.log`: scripts.spark_exclusive_session.SessionError: competing_service_active:llama-server.service
- `zh-Hans-v1/dispatch.log`: Traceback (most recent call last):
- `zh-Hans-v1/dispatch.log`: if completed.returncode or response.get('error'): raise SessionError(response.get('error', 'ssh_failed_unknown'))
- `zh-Hans-v1/dispatch.log`: scripts.spark_exclusive_session.SessionError: competing_service_active:llama-server.service
- `zh-Hans-v1/spark-driver.log`: "status": "track_check_failed",

Not copied: 50 .json, 9 .lock
