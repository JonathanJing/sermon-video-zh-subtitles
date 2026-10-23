# Run digest 20261021-vibevoice-asr-diarization-trial

Generated 2026-10-21T03:45:22+00:00. Redacted copies only; source hashes are in manifest.json.

## run-evidence

Source: `~/SynologyDrive/GitHub/Active/sermon-video-zh-subtitles/tmp/diarization/if-i-had-more-time/run-evidence`

- outcome `outcome.json`: **succeeded** exit 0 (2026-10-21T03:01:41+00:00 → 2026-10-21T03:43:00+00:00)

Timings `timings.tsv`:

| stage | status | elapsed_seconds |
|---|---|---|
| mac-mlx-8bit/load | pass | 14.0 |
| mac-mlx-8bit/encode | pass | 129.4 |
| mac-mlx-8bit/prefill | pass | 115.9 |
| mac-mlx-8bit/generate | pass | 1063.4 |
| mac-mlx-8bit/total | pass | 1206.8 |
| spark-cuda-bf16/load | pass | 106.5 |
| spark-cuda-bf16/preprocess | pass | 1.8 |
| spark-cuda-bf16/encode_and_prefill | pass | 90.8 |
| spark-cuda-bf16/generate | pass | 1726.4 |
| spark-cuda-bf16/total | pass | 1834.7 |
