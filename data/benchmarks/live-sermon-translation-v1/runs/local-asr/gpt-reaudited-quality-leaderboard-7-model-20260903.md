# Local ASR model-reviewed quality leaderboard

Reference: `mixed_model_reviewed_and_gpt_reaudited_reference_not_human_gold`; 60 clips / 29.811 minutes.

| Model | MRQS / 100 | WER | Critical-term recall | Valid | Silence hallucinations | Mean RTF | Peak RSS GiB | Gates |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| mlx-community/Qwen3-ASR-0.6B-8bit | 96.893 | 3.73% | 97.10% | 60/60 | 0 | 0.0653 | 1.1519 | PASS |
| ASR-WCPP-SMALL-EN-F16 | 96.244 | 4.09% | 95.65% | 60/60 | 0 | 0.0368 | 0.7188 | PASS |
| nvidia/parakeet-tdt-0.6b-v3-q8_0 | 95.045 | 4.36% | 92.75% | 58/60 | 0 | 0.0362 | 0.8007 | FAIL |
| nvidia/nemotron-speech-streaming-en-0.6b-q8_0 | 93.931 | 5.49% | 91.30% | 58/60 | 0 | 0.0531 | 1.6688 | FAIL |
| ASR-WCPP-MEDIUM-EN-F16 | 93.772 | 5.61% | 91.30% | 57/60 | 0 | 0.0777 | 1.8215 | FAIL |
| distil-whisper/distil-large-v3-ggml-f16 | 92.453 | 3.52% | 98.55% | 60/60 | 1 | 0.0531 | 1.6866 | FAIL |
| mlx-community/whisper-large-v3-turbo | 91.823 | 3.12% | 95.65% | 60/60 | 1 | 0.0729 | 1.7174 | FAIL |

MRQS = 60% WER fidelity + 30% critical-term recall + 5% complete output + 5% silence discipline. Hard gates override the scalar score.

This is a provisional comparison against GPT-Transcribe reference tiers, not human Gold. It cannot authorize production selection until human listening confirmation, streaming replay, and co-residency soak are complete.
