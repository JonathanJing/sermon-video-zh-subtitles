# Local ASR model-reviewed quality leaderboard

Reference: `mixed_model_reviewed_and_gpt_reaudited_reference_not_human_gold`; 60 clips / 29.811 minutes.

| Model | MRQS / 100 | WER | Critical-term recall | Valid | Silence hallucinations | Mean RTF | Peak RSS GiB | Gates |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| ASR-WCPP-SMALL-EN-F16 | 96.244 | 4.09% | 95.65% | 60/60 | 0 | 0.0368 | 0.7188 | PASS |
| ASR-WCPP-MEDIUM-EN-F16 | 93.772 | 5.61% | 91.30% | 57/60 | 0 | 0.0777 | 1.8215 | FAIL |

MRQS = 60% WER fidelity + 30% critical-term recall + 5% complete output + 5% silence discipline. Hard gates override the scalar score.

This is a provisional comparison against GPT-Transcribe reference tiers, not human Gold. It cannot authorize production selection until human listening confirmation, streaming replay, and co-residency soak are complete.
