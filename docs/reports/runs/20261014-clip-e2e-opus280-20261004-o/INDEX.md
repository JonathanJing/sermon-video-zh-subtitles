# Run digest 20261014-clip-e2e-opus280-20261004-o

Generated 2026-10-14T21:22:12+00:00. Redacted copies only; source hashes are in manifest.json.

## clip-e2e-20261004-opus-o

Source: `~/SynologyDrive/GitHub/Active/sermon-video-zh-subtitles/artifacts/clip-e2e-20261004-opus-o`

- summary `textqc-es/out/summary.json` es: **requires_repair** (text QC failed; repair the failed groups in a new candidate revision)
- summary `textqc-ko/out/summary.json` ko: **requires_repair** (text QC failed; repair the failed groups in a new candidate revision)
- summary `textqc-zh-Hans/out/summary.json` zh-Hans: **requires_repair** (text QC failed; repair the failed groups in a new candidate revision)

Timings `textqc-es/out/timings.tsv`:

| stage | status | seconds |
|---|---|---|
| discover | pass | 0.0 |
| es.text-qc.prefetch | pass | 47.3 |
| es.text-qc | pass | 2.7 |

Timings `textqc-ko/out/timings.tsv`:

| stage | status | seconds |
|---|---|---|
| discover | pass | 0.0 |
| ko.text-qc.prefetch | pass | 51.1 |
| ko.text-qc | pass | 2.6 |

Timings `textqc-zh-Hans/out/timings.tsv`:

| stage | status | seconds |
|---|---|---|
| discover | pass | 0.0 |
| zh-Hans.text-qc.prefetch | pass | 70.5 |
| zh-Hans.text-qc | pass | 2.9 |

Timings `timings.tsv`:

| timeline-map | pass | 0 |
|---|---|---|
| route-probe | pass | 0 |
| plan-layer2 | pass | 0 |
| check-layer2 | pass | 1 |
| layer2 | pass | 2 |
| layer2 | pass | 1 |
| plan-qc-ko | pass | 0 |
| check-qc-ko-out | pass | 0 |
| text-qc.ko.out | fail(1) | 54 |
| plan-layer2-ko-r1 | pass | 0 |
| layer2-ko-r1 | pass | 1 |
| layer2-ko-r1 | pass | 0 |
| plan-qc-es | pass | 0 |
| check-qc-es-out | pass | 0 |
| text-qc.es.out | fail(1) | 50 |
| plan-layer2-es-r1 | pass | 0 |
| layer2-es-r1 | pass | 1 |
| layer2-es-r1 | pass | 0 |
| plan-qc-zh-Hans | pass | 0 |
| check-qc-zh-Hans-out | pass | 0 |
| text-qc.zh-Hans.out | fail(1) | 74 |
| plan-layer2-zh-Hans-r1 | pass | 0 |
| layer2-zh-Hans-r1 | pass | 1 |
| layer2-zh-Hans-r1 | pass | 0 |

Failed stages: `text-qc.ko.out`, `text-qc.es.out`, `text-qc.zh-Hans.out`
- source budget `plans/qc-es/qc-es/.api-budget/source-budget.json`: 99 of 99 requests returned; reserved US$1.01; estimated US$0.13 over 99 priced; invoice not verified
- source budget `plans/qc-ko/qc-ko/.api-budget/source-budget.json`: 99 of 99 requests returned; reserved US$1.08; estimated US$0.15 over 99 priced; invoice not verified
- source budget `plans/qc-zh-Hans/qc-zh-Hans/.api-budget/source-budget.json`: 99 of 99 requests returned; reserved US$1.08; estimated US$0.15 over 99 priced; invoice not verified

Error-like log lines (first 5 per log):

- `l2/layer2-jobs/089aa63f5aa82969053dd0d5d8136b3478fc253e2db1c67cf4b6dfe424dc1539/worker.log`: Traceback (most recent call last):
- `l2/layer2-jobs/089aa63f5aa82969053dd0d5d8136b3478fc253e2db1c67cf4b6dfe424dc1539/worker.log`: raise ValueError(message)
- `l2/layer2-jobs/089aa63f5aa82969053dd0d5d8136b3478fc253e2db1c67cf4b6dfe424dc1539/worker.log`: ValueError: CLI transport permits only a bound next repair round in the same job
- `l2/layer2-jobs/55d08de62262127356309330c92c4ccf5c035c052bb3a6d0d64c396d2b1128b1/worker.log`: Traceback (most recent call last):
- `l2/layer2-jobs/55d08de62262127356309330c92c4ccf5c035c052bb3a6d0d64c396d2b1128b1/worker.log`: raise ValueError(message)
- `l2/layer2-jobs/55d08de62262127356309330c92c4ccf5c035c052bb3a6d0d64c396d2b1128b1/worker.log`: ValueError: CLI transport permits only a bound next repair round in the same job
- `l2/layer2-jobs/a3a5d158425877f4a8576ac2051e395913055915bd12357e887e8bd92d620449/worker.log`: Traceback (most recent call last):
- `l2/layer2-jobs/a3a5d158425877f4a8576ac2051e395913055915bd12357e887e8bd92d620449/worker.log`: raise ValueError(message)
- `l2/layer2-jobs/a3a5d158425877f4a8576ac2051e395913055915bd12357e887e8bd92d620449/worker.log`: ValueError: CLI transport permits only a bound next repair round in the same job
- `l2/text/es/accounting/operations.log`: ... 820 lines omitted; 0 error-like lines, 0 kept below ...
- `l2/text/ko/accounting/operations.log`: ... 1820 lines omitted; 2 error-like lines, 2 kept below ...
- `l2/text/ko/accounting/operations.log`: [line 1022] 2026-10-14T21:17:27.383883+00:00 ERROR run=003ce5e5f44245acb26fdd04de5c95b0 stage_finished workflowId=0533b7e23fdd4152bb06f9dcd62c06e2 stage=layer2_models spanId=28d29f677a5e4d49a78ee5db87
- `l2/text/ko/accounting/operations.log`: [line 1024] 2026-10-14T21:17:27.385649+00:00 ERROR run=003ce5e5f44245acb26fdd04de5c95b0 workflow_finished workflowId=0533b7e23fdd4152bb06f9dcd62c06e2 stage=canonical_layer2_worker spanId=f656778fea644
- `l2/text/zh-Hans/accounting/operations.log`: ... 825 lines omitted; 0 error-like lines, 0 kept below ...
- `l2-es-r1/text/es/accounting/operations.log`: 2026-10-14T21:20:04.524033+00:00 ERROR run=9ea133f7c6b14457863b8cae82943066 stage_finished workflowId=7992dfe9f8d94412a32b6452208e0c32 stage=layer2.run_admission.es spanId=b945e04e837c4de7bb435e5d5fef
- `l2-es-r1/text/es/accounting/operations.log`: 2026-10-14T21:20:04.524861+00:00 ERROR run=9ea133f7c6b14457863b8cae82943066 stage_finished workflowId=7992dfe9f8d94412a32b6452208e0c32 stage=layer2_models spanId=9f49c979150e4301a733fd2aeb430839 attem
- `l2-es-r1/text/es/accounting/operations.log`: 2026-10-14T21:20:04.525454+00:00 ERROR run=9ea133f7c6b14457863b8cae82943066 workflow_finished workflowId=7992dfe9f8d94412a32b6452208e0c32 stage=canonical_layer2_worker spanId=b726da65b8b243de8343a9009
- `l2-es-r1/text/es/accounting/operations.log`: 2026-10-14T21:20:04.526216+00:00 ERROR run=9ea133f7c6b14457863b8cae82943066 stage_finished workflowId=f4c2b4a682ff44be86a58b79bc5ffb66 stage=canonical_layer2_worker spanId=b726da65b8b243de8343a9009937
- `l2-es-r1/text/es/accounting/operations.log`: 2026-10-14T21:20:04.527685+00:00 ERROR run=9ea133f7c6b14457863b8cae82943066 workflow_finished workflowId=f4c2b4a682ff44be86a58b79bc5ffb66 status=failed
- `l2-ko-r1/text/ko/accounting/operations.log`: 2026-10-14T21:19:07.382034+00:00 ERROR run=8785364a6cd1411e9582921fe89e1c17 stage_finished workflowId=5fa7124800db43aea6a64ef7bac3aea9 stage=layer2.run_admission.ko spanId=4254d0e0ca4e4781bb4df4294d9f
- `l2-ko-r1/text/ko/accounting/operations.log`: 2026-10-14T21:19:07.382851+00:00 ERROR run=8785364a6cd1411e9582921fe89e1c17 stage_finished workflowId=5fa7124800db43aea6a64ef7bac3aea9 stage=layer2_models spanId=ebfe1b28a7e74302868861fe0631702a attem
- `l2-ko-r1/text/ko/accounting/operations.log`: 2026-10-14T21:19:07.383475+00:00 ERROR run=8785364a6cd1411e9582921fe89e1c17 workflow_finished workflowId=5fa7124800db43aea6a64ef7bac3aea9 stage=canonical_layer2_worker spanId=6c841393441b4ac3a059d58ad
- `l2-ko-r1/text/ko/accounting/operations.log`: 2026-10-14T21:19:07.384276+00:00 ERROR run=8785364a6cd1411e9582921fe89e1c17 stage_finished workflowId=bcc589fb29c84d83a0d36b8cae64f563 stage=canonical_layer2_worker spanId=6c841393441b4ac3a059d58adde8
- `l2-ko-r1/text/ko/accounting/operations.log`: 2026-10-14T21:19:07.385754+00:00 ERROR run=8785364a6cd1411e9582921fe89e1c17 workflow_finished workflowId=bcc589fb29c84d83a0d36b8cae64f563 status=failed
- `l2-zh-Hans-r1/text/zh-Hans/accounting/operations.log`: 2026-10-14T21:21:25.463619+00:00 ERROR run=584fbeba6b8c40fe8674647d2312bdbd stage_finished workflowId=f64c53e43f824ac9a87ae82aeef902e0 stage=layer2.run_admission.zh-Hans spanId=5a816826f9b749c595f4cb8
- `l2-zh-Hans-r1/text/zh-Hans/accounting/operations.log`: 2026-10-14T21:21:25.464144+00:00 ERROR run=584fbeba6b8c40fe8674647d2312bdbd stage_finished workflowId=f64c53e43f824ac9a87ae82aeef902e0 stage=layer2_models spanId=dd84b842d51246ac8598a6ce05cdbd05 attem
- `l2-zh-Hans-r1/text/zh-Hans/accounting/operations.log`: 2026-10-14T21:21:25.464552+00:00 ERROR run=584fbeba6b8c40fe8674647d2312bdbd workflow_finished workflowId=f64c53e43f824ac9a87ae82aeef902e0 stage=canonical_layer2_worker spanId=a03f120c04524ac09853f0b5c
- `l2-zh-Hans-r1/text/zh-Hans/accounting/operations.log`: 2026-10-14T21:21:25.465212+00:00 ERROR run=584fbeba6b8c40fe8674647d2312bdbd stage_finished workflowId=12b6bb2a9e87465fb575b13ac3b7789a stage=canonical_layer2_worker spanId=a03f120c04524ac09853f0b5c438
- `l2-zh-Hans-r1/text/zh-Hans/accounting/operations.log`: 2026-10-14T21:21:25.466314+00:00 ERROR run=584fbeba6b8c40fe8674647d2312bdbd workflow_finished workflowId=12b6bb2a9e87465fb575b13ac3b7789a status=failed
- `logs/check-layer2.log`: "failed": [],
- `logs/check-qc-es-out.log`: "failed": [],
- `logs/check-qc-ko-out.log`: "failed": [],
- `logs/check-qc-zh-Hans-out.log`: "failed": [],
- `logs/plan-layer2-es-r1.log`: == 2026-10-14T21:20:02+00:00 ~/SynologyDrive/GitHub/Active/sermon-video-zh-subtitles/.venv/bin/python ~/.codex/worktrees/opus-layer1-larger-clip/sermon-video-zh-subtitles/scripts/run_with_openai_envir
- `logs/plan-layer2-ko-r1.log`: == 2026-10-14T21:19:05+00:00 ~/SynologyDrive/GitHub/Active/sermon-video-zh-subtitles/.venv/bin/python ~/.codex/worktrees/opus-layer1-larger-clip/sermon-video-zh-subtitles/scripts/run_with_openai_envir
- `logs/plan-layer2-zh-Hans-r1.log`: == 2026-10-14T21:21:23+00:00 ~/SynologyDrive/GitHub/Active/sermon-video-zh-subtitles/.venv/bin/python ~/.codex/worktrees/opus-layer1-larger-clip/sermon-video-zh-subtitles/scripts/run_with_openai_envir
- `logs/plan-layer2.log`: == 2026-10-14T21:17:22+00:00 ~/SynologyDrive/GitHub/Active/sermon-video-zh-subtitles/.venv/bin/python ~/.codex/worktrees/opus-layer1-larger-clip/sermon-video-zh-subtitles/scripts/run_with_openai_envir
- `logs/plan-qc-es.log`: == 2026-10-14T21:19:11+00:00 ~/SynologyDrive/GitHub/Active/sermon-video-zh-subtitles/.venv/bin/python ~/.codex/worktrees/opus-layer1-larger-clip/sermon-video-zh-subtitles/scripts/run_with_openai_envir
- `logs/plan-qc-ko.log`: == 2026-10-14T21:18:10+00:00 ~/SynologyDrive/GitHub/Active/sermon-video-zh-subtitles/.venv/bin/python ~/.codex/worktrees/opus-layer1-larger-clip/sermon-video-zh-subtitles/scripts/run_with_openai_envir
- `logs/plan-qc-zh-Hans.log`: == 2026-10-14T21:20:08+00:00 ~/SynologyDrive/GitHub/Active/sermon-video-zh-subtitles/.venv/bin/python ~/.codex/worktrees/opus-layer1-larger-clip/sermon-video-zh-subtitles/scripts/run_with_openai_envir
- `logs/text-qc.es.out.log`: "reason": "text QC failed; repair the failed groups in a new candidate revision",
- `logs/text-qc.ko.out.log`: "reason": "text QC failed; repair the failed groups in a new candidate revision",
- `logs/text-qc.zh-Hans.out.log`: "reason": "text QC failed; repair the failed groups in a new candidate revision",

Not copied: 18 .csv, 1882 .json, 6 .jsonl, 345 .lock, 2 .py, 43 .txt
