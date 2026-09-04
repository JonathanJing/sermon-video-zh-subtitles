# Local ASR model-reviewed quality leaderboard

Reference: `model_reviewed_reference_not_human_gold`; 60 clips / 29.811 minutes.

| Model | MRQS / 100 | WER | Critical-term recall | Valid | Silence hallucinations | Mean RTF | Peak RSS GiB | Gates |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| ASR-WCPP-SMALL-EN-F16 | 96.536 | 4.32% | 97.10% | 60/60 | 0 | 0.0368 | 0.7188 | PASS |
| ASR-WCPP-MEDIUM-EN-F16 | 93.620 | 5.87% | 91.30% | 57/60 | 0 | 0.0777 | 1.8215 | FAIL |

MRQS = 60% WER fidelity + 30% critical-term recall + 5% complete output + 5% silence discipline. Hard gates override the scalar score.

This is a provisional comparison against an exact-chunk GPT-Transcribe reference, not human Gold. It cannot authorize production selection until a human calibration subset, streaming replay, and co-residency soak are complete.
