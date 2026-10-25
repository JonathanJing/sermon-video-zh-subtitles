# Run digest 20261020-clip-e2e-scroll-blocked

Generated 2026-10-21T04:36:12+00:00. Redacted copies only; source hashes are in manifest.json.

## clip-e2e-15030286-20261020-scroll

Source: `~/SynologyDrive/GitHub/Active/sermon-video-zh-subtitles/.agents/worktrees/codex/clip-e2e-15030286-7min-20261020/artifacts/clip-e2e-15030286-20261020-scroll`


Timings `timings.tsv`:

| inputs | fail(1) | 177 |
|---|---|---|
| inputs | fail(1) | 1 |
| inputs | fail(1) | 196 |
| inputs | pass | 237 |
| timeline-map | pass | 1 |
| route-probe | pass | 0 |
| plan-layer2 | fail(1) | 0 |
| plan-layer2 | fail(2) | 0 |
| plan-layer2 | fail(2) | 0 |
| plan-layer2 | pass | 1 |
| check-layer2 | pass | 1 |
| layer2 | pass | 2 |
| plan-layer2 | fail(1) | 0 |
| plan-layer2 | pass | 1 |
| check-layer2 | pass | 1 |
| layer2 | pass | 1 |
| plan-layer2 | fail(1) | 0 |
| route-probe | pass | 0 |
| plan-layer2 | pass | 0 |
| check-layer2 | pass | 1 |
| layer2 | pass | 1 |
| check-layer2 | fail(1) | 1 |
| plan-layer2 | pass | 1 |
| check-layer2 | fail(1) | 1 |
| plan-layer2 | pass | 0 |
| check-layer2 | fail(1) | 1 |

Failed stages: `inputs`, `inputs`, `plan-layer2`, `plan-layer2`, `plan-layer2`, `plan-layer2`, `plan-layer2`, `check-layer2`, `check-layer2`, `check-layer2`

Error-like log lines (first 5 per log):

- `l2/attempt-1-week-plugins/layer2-jobs/245293d077cb4d6450f3c21eeac0276a3aae2a9cf4cc8a5f7e318c66a5500caa/worker.log`: Traceback (most recent call last):
- `l2/attempt-1-week-plugins/layer2-jobs/245293d077cb4d6450f3c21eeac0276a3aae2a9cf4cc8a5f7e318c66a5500caa/worker.log`: raise self._exception
- `l2/attempt-1-week-plugins/layer2-jobs/245293d077cb4d6450f3c21eeac0276a3aae2a9cf4cc8a5f7e318c66a5500caa/worker.log`: raise ValueError("15030286 plugin source package differs")
- `l2/attempt-1-week-plugins/layer2-jobs/245293d077cb4d6450f3c21eeac0276a3aae2a9cf4cc8a5f7e318c66a5500caa/worker.log`: ValueError: 15030286 plugin source package differs
- `l2/attempt-1-week-plugins/layer2-jobs/427d330bd26d82c28a40d10e21cce79253851d854b30588e9e54efdc36d4ba9f/worker.log`: Traceback (most recent call last):
- `l2/attempt-1-week-plugins/layer2-jobs/427d330bd26d82c28a40d10e21cce79253851d854b30588e9e54efdc36d4ba9f/worker.log`: raise self._exception
- `l2/attempt-1-week-plugins/layer2-jobs/427d330bd26d82c28a40d10e21cce79253851d854b30588e9e54efdc36d4ba9f/worker.log`: raise ValueError("15030286 plugin source package differs")
- `l2/attempt-1-week-plugins/layer2-jobs/427d330bd26d82c28a40d10e21cce79253851d854b30588e9e54efdc36d4ba9f/worker.log`: ValueError: 15030286 plugin source package differs
- `l2/attempt-1-week-plugins/text/es/accounting/operations.log`: 2026-10-21T04:08:42.446718+00:00 ERROR run=a5edd915b45d48dea5ac9968ba32319a stage_finished workflowId=3042eb451d32428793bda804d9c0f2b3 stage=layer2.review_validation.es.group-0005 spanId=e13be6a833894
- `l2/attempt-1-week-plugins/text/es/accounting/operations.log`: 2026-10-21T04:08:42.447677+00:00 ERROR run=a5edd915b45d48dea5ac9968ba32319a stage_finished workflowId=3042eb451d32428793bda804d9c0f2b3 stage=layer2.group.es.0005 spanId=2a5e64547ced48e3a5867a06c8b40ac
- `l2/attempt-1-week-plugins/text/es/accounting/operations.log`: 2026-10-21T04:08:43.150903+00:00 ERROR run=a5edd915b45d48dea5ac9968ba32319a stage_finished workflowId=3042eb451d32428793bda804d9c0f2b3 stage=layer2.review_validation.es.group-0001 spanId=37f84cdad5fe4
- `l2/attempt-1-week-plugins/text/es/accounting/operations.log`: 2026-10-21T04:08:43.152261+00:00 ERROR run=a5edd915b45d48dea5ac9968ba32319a stage_finished workflowId=3042eb451d32428793bda804d9c0f2b3 stage=layer2.group.es.0001 spanId=b662aa94f81f48bc9171f70581cd9d5
- `l2/attempt-1-week-plugins/text/es/accounting/operations.log`: 2026-10-21T04:08:43.706720+00:00 ERROR run=a5edd915b45d48dea5ac9968ba32319a stage_finished workflowId=3042eb451d32428793bda804d9c0f2b3 stage=layer2.review_validation.es.group-0007 spanId=1723f2478a494
- `l2/attempt-1-week-plugins/text/zh-Hans/accounting/operations.log`: 2026-10-21T04:08:44.222209+00:00 ERROR run=30d5a1d174604d57b3ffa1ff3b083413 stage_finished workflowId=bb90ba72e8c2463ab4a461ce6442c7c1 stage=layer2.review_validation.zh-Hans.group-0001 spanId=e2d7dbc6
- `l2/attempt-1-week-plugins/text/zh-Hans/accounting/operations.log`: 2026-10-21T04:08:44.223741+00:00 ERROR run=30d5a1d174604d57b3ffa1ff3b083413 stage_finished workflowId=bb90ba72e8c2463ab4a461ce6442c7c1 stage=layer2.group.zh-Hans.0001 spanId=92593a4aa570401fa76d29ecd6
- `l2/attempt-1-week-plugins/text/zh-Hans/accounting/operations.log`: 2026-10-21T04:08:45.365535+00:00 ERROR run=30d5a1d174604d57b3ffa1ff3b083413 stage_finished workflowId=bb90ba72e8c2463ab4a461ce6442c7c1 stage=layer2.review_validation.zh-Hans.group-0004 spanId=dc6103ed
- `l2/attempt-1-week-plugins/text/zh-Hans/accounting/operations.log`: 2026-10-21T04:08:45.366401+00:00 ERROR run=30d5a1d174604d57b3ffa1ff3b083413 stage_finished workflowId=bb90ba72e8c2463ab4a461ce6442c7c1 stage=layer2.group.zh-Hans.0004 spanId=ee83c673ff61414f8accb1984a
- `l2/attempt-1-week-plugins/text/zh-Hans/accounting/operations.log`: 2026-10-21T04:08:45.633947+00:00 ERROR run=30d5a1d174604d57b3ffa1ff3b083413 stage_finished workflowId=bb90ba72e8c2463ab4a461ce6442c7c1 stage=layer2.review_validation.zh-Hans.group-0005 spanId=0d16fe26
- `l2/attempt-3-week-import/layer2-jobs/ac0e595c21df046add1cdbf21c63c7276b20bdd3c4aced52cd2ee7354d0af724/worker.log`: Traceback (most recent call last):
- `l2/attempt-3-week-import/layer2-jobs/ac0e595c21df046add1cdbf21c63c7276b20bdd3c4aced52cd2ee7354d0af724/worker.log`: raise self._exception
- `l2/attempt-3-week-import/layer2-jobs/ac0e595c21df046add1cdbf21c63c7276b20bdd3c4aced52cd2ee7354d0af724/worker.log`: raise ValueError("15030286 plugin source package differs")
- `l2/attempt-3-week-import/layer2-jobs/ac0e595c21df046add1cdbf21c63c7276b20bdd3c4aced52cd2ee7354d0af724/worker.log`: ValueError: 15030286 plugin source package differs
- `l2/attempt-3-week-import/layer2-jobs/e0c640413a68631977051f678cdc9722633b6c830e2ea411a5a3a8271469bed5/worker.log`: Traceback (most recent call last):
- `l2/attempt-3-week-import/layer2-jobs/e0c640413a68631977051f678cdc9722633b6c830e2ea411a5a3a8271469bed5/worker.log`: raise self._exception
- `l2/attempt-3-week-import/layer2-jobs/e0c640413a68631977051f678cdc9722633b6c830e2ea411a5a3a8271469bed5/worker.log`: raise ValueError("15030286 plugin source package differs")
- `l2/attempt-3-week-import/layer2-jobs/e0c640413a68631977051f678cdc9722633b6c830e2ea411a5a3a8271469bed5/worker.log`: ValueError: 15030286 plugin source package differs
- `l2/attempt-3-week-import/text/es/accounting/operations.log`: 2026-10-21T04:12:58.237852+00:00 ERROR run=bb6ba40a28a04c42a0172267196dea73 stage_finished workflowId=d52d2d4635384e38b745922c02b17741 stage=layer2.review_validation.es.group-0004 spanId=b5e7a2f670a94
- `l2/attempt-3-week-import/text/es/accounting/operations.log`: 2026-10-21T04:12:58.240462+00:00 ERROR run=bb6ba40a28a04c42a0172267196dea73 stage_finished workflowId=d52d2d4635384e38b745922c02b17741 stage=layer2.group.es.0004 spanId=89754dc258874dd6bd487e2f2b1e755
- `l2/attempt-3-week-import/text/es/accounting/operations.log`: 2026-10-21T04:12:58.246247+00:00 ERROR run=bb6ba40a28a04c42a0172267196dea73 stage_finished workflowId=d52d2d4635384e38b745922c02b17741 stage=layer2.review_validation.es.group-0005 spanId=cfbfdf5cf4064
- `l2/attempt-3-week-import/text/es/accounting/operations.log`: 2026-10-21T04:12:58.247022+00:00 ERROR run=bb6ba40a28a04c42a0172267196dea73 stage_finished workflowId=d52d2d4635384e38b745922c02b17741 stage=layer2.group.es.0005 spanId=e2c44672d217430cadf19fe42c077e6
- `l2/attempt-3-week-import/text/es/accounting/operations.log`: 2026-10-21T04:13:00.406969+00:00 ERROR run=bb6ba40a28a04c42a0172267196dea73 stage_finished workflowId=d52d2d4635384e38b745922c02b17741 stage=layer2.review_validation.es.group-0007 spanId=308e902c43344
- `l2/attempt-3-week-import/text/zh-Hans/accounting/operations.log`: 2026-10-21T04:12:58.750747+00:00 ERROR run=de680b54332a4faba165a17a815068a1 stage_finished workflowId=0eb5c4227178476889f35791c3e7968e stage=layer2.review_validation.zh-Hans.group-0004 spanId=70bbc9ae
- `l2/attempt-3-week-import/text/zh-Hans/accounting/operations.log`: 2026-10-21T04:12:58.751831+00:00 ERROR run=de680b54332a4faba165a17a815068a1 stage_finished workflowId=0eb5c4227178476889f35791c3e7968e stage=layer2.group.zh-Hans.0004 spanId=2d2d6f6503a143f59e0630cf08
- `l2/attempt-3-week-import/text/zh-Hans/accounting/operations.log`: 2026-10-21T04:12:59.888768+00:00 ERROR run=de680b54332a4faba165a17a815068a1 stage_finished workflowId=0eb5c4227178476889f35791c3e7968e stage=layer2.review_validation.zh-Hans.group-0001 spanId=832cb376
- `l2/attempt-3-week-import/text/zh-Hans/accounting/operations.log`: 2026-10-21T04:12:59.889648+00:00 ERROR run=de680b54332a4faba165a17a815068a1 stage_finished workflowId=0eb5c4227178476889f35791c3e7968e stage=layer2.group.zh-Hans.0001 spanId=4100a292fe8b41099bb747e550
- `l2/attempt-3-week-import/text/zh-Hans/accounting/operations.log`: 2026-10-21T04:13:00.694991+00:00 ERROR run=de680b54332a4faba165a17a815068a1 stage_finished workflowId=0eb5c4227178476889f35791c3e7968e stage=layer2.review_validation.zh-Hans.group-0005 spanId=45eea4e0
- `logs/check-layer2.log`: "failed": [],
- `logs/check-layer2.log`: ... 174 lines omitted; 2 error-like lines, 2 kept below ...
- `logs/check-layer2.log`: [line 78]  "failed": [],
- `logs/check-layer2.log`: [line 150]  "failed": [],
- `logs/check-layer2.log`: "status": "fail",
- `logs/inputs.log`: Traceback (most recent call last):
- `logs/inputs.log`: raise ValueError(message)
- `logs/inputs.log`: ValueError: zh-Hans: the audio package was not rendered from this candidate
- `logs/inputs.log`: Traceback (most recent call last):
- `logs/inputs.log`: raise ValueError(message)
- `logs/plan-layer2.log`: Traceback (most recent call last):
- `logs/plan-layer2.log`: raise ValueError(f"Layer 2 {locale} {dimension} cap cannot cover even the initial "
- `logs/plan-layer2.log`: ValueError: Layer 2 es costMicrousd cap cannot cover even the initial 176 calls; use an explicitly approved profile, do not inflate authority implicitly
- `logs/plan-layer2.log`: plan_run_budgets.py: error: argument --out: expected one argument
- `logs/plan-layer2.log`: plan_run_budgets.py: error: argument --out: expected one argument

Not copied: 12 .csv, 397 .json, 4 .jsonl, 48 .lock, 9 .py, 1 .pyc

## clip-e2e-15030286-20261020-scroll-b

Source: `~/SynologyDrive/GitHub/Active/sermon-video-zh-subtitles/.agents/worktrees/codex/clip-e2e-15030286-7min-20261020/artifacts/clip-e2e-15030286-20261020-scroll-b`


Timings `timings.tsv`:

| inputs | pass | 199 |
|---|---|---|
| timeline-map | pass | 0 |
| route-probe | pass | 0 |
| plan-layer2 | pass | 0 |
| check-layer2 | pass | 1 |
| layer2 | pass | 1 |
| check-layer2 | fail(1) | 1 |

Failed stages: `check-layer2`

Error-like log lines (first 5 per log):

- `l2/attempt-1-worker-import/layer2-jobs/0a210184164a5a3cb69feae66b69655b86e3b111818d5d4616dca32335426e26/worker.log`: Traceback (most recent call last):
- `l2/attempt-1-worker-import/layer2-jobs/0a210184164a5a3cb69feae66b69655b86e3b111818d5d4616dca32335426e26/worker.log`: raise self._exception
- `l2/attempt-1-worker-import/layer2-jobs/0a210184164a5a3cb69feae66b69655b86e3b111818d5d4616dca32335426e26/worker.log`: raise ValueError("15030286 plugin source package differs")
- `l2/attempt-1-worker-import/layer2-jobs/0a210184164a5a3cb69feae66b69655b86e3b111818d5d4616dca32335426e26/worker.log`: ValueError: 15030286 plugin source package differs
- `l2/attempt-1-worker-import/layer2-jobs/eb9fa2668d22b24a7b1bb4082432cb2bbf92e6fdaae0695cd8543b742f05c8cf/worker.log`: Traceback (most recent call last):
- `l2/attempt-1-worker-import/layer2-jobs/eb9fa2668d22b24a7b1bb4082432cb2bbf92e6fdaae0695cd8543b742f05c8cf/worker.log`: raise self._exception
- `l2/attempt-1-worker-import/layer2-jobs/eb9fa2668d22b24a7b1bb4082432cb2bbf92e6fdaae0695cd8543b742f05c8cf/worker.log`: raise ValueError("15030286 plugin source package differs")
- `l2/attempt-1-worker-import/layer2-jobs/eb9fa2668d22b24a7b1bb4082432cb2bbf92e6fdaae0695cd8543b742f05c8cf/worker.log`: ValueError: 15030286 plugin source package differs
- `l2/text/es/accounting/operations.log`: 2026-10-21T04:27:00.750462+00:00 ERROR run=d06c60f968cb42ba8a23b5876157fa48 stage_finished workflowId=cbe15e4ade504ccea94feb58cf06ede7 stage=layer2.review_validation.es.group-0005 spanId=e3a991ef600b4
- `l2/text/es/accounting/operations.log`: 2026-10-21T04:27:00.751441+00:00 ERROR run=d06c60f968cb42ba8a23b5876157fa48 stage_finished workflowId=cbe15e4ade504ccea94feb58cf06ede7 stage=layer2.group.es.0005 spanId=c57ad2a8bc14437fb7e41f10f6adbde
- `l2/text/es/accounting/operations.log`: 2026-10-21T04:27:01.086190+00:00 ERROR run=d06c60f968cb42ba8a23b5876157fa48 stage_finished workflowId=cbe15e4ade504ccea94feb58cf06ede7 stage=layer2.review_validation.es.group-0007 spanId=80afe99f26004
- `l2/text/es/accounting/operations.log`: 2026-10-21T04:27:01.087080+00:00 ERROR run=d06c60f968cb42ba8a23b5876157fa48 stage_finished workflowId=cbe15e4ade504ccea94feb58cf06ede7 stage=layer2.group.es.0007 spanId=bab9bdb62d65479db8b012f3289ff6b
- `l2/text/es/accounting/operations.log`: 2026-10-21T04:27:02.741953+00:00 ERROR run=d06c60f968cb42ba8a23b5876157fa48 stage_finished workflowId=cbe15e4ade504ccea94feb58cf06ede7 stage=layer2.review_validation.es.group-0001 spanId=9f2f47a4cde14
- `l2/text/zh-Hans/accounting/operations.log`: 2026-10-21T04:27:01.676518+00:00 ERROR run=8a0ef34741744e9a97f9e39575718f5d stage_finished workflowId=7fa323ba21ca409ea61429864bdd8dd1 stage=layer2.review_validation.zh-Hans.group-0005 spanId=8d805a92
- `l2/text/zh-Hans/accounting/operations.log`: 2026-10-21T04:27:01.677618+00:00 ERROR run=8a0ef34741744e9a97f9e39575718f5d stage_finished workflowId=7fa323ba21ca409ea61429864bdd8dd1 stage=layer2.group.zh-Hans.0005 spanId=6d13aaea76244335924f1f3356
- `l2/text/zh-Hans/accounting/operations.log`: 2026-10-21T04:27:02.448699+00:00 ERROR run=8a0ef34741744e9a97f9e39575718f5d stage_finished workflowId=7fa323ba21ca409ea61429864bdd8dd1 stage=layer2.review_validation.zh-Hans.group-0004 spanId=42225d9b
- `l2/text/zh-Hans/accounting/operations.log`: 2026-10-21T04:27:02.449750+00:00 ERROR run=8a0ef34741744e9a97f9e39575718f5d stage_finished workflowId=7fa323ba21ca409ea61429864bdd8dd1 stage=layer2.group.zh-Hans.0004 spanId=41adee5683f5432e92307c9f6d
- `l2/text/zh-Hans/accounting/operations.log`: 2026-10-21T04:27:03.377880+00:00 ERROR run=8a0ef34741744e9a97f9e39575718f5d stage_finished workflowId=7fa323ba21ca409ea61429864bdd8dd1 stage=layer2.review_validation.zh-Hans.group-0007 spanId=8e503efe
- `logs/check-layer2.log`: "failed": [],
- `logs/check-layer2.log`: "status": "fail",
- `logs/check-layer2.log`: "failed": [
- `logs/check-layer2.log`: "status": "fail",
- `logs/check-layer2.log`: "status": "fail",
- `logs/plan-layer2.log`: == 2026-10-21T04:26:45+00:00 ~/SynologyDrive/GitHub/Active/sermon-video-zh-subtitles/.agents/worktrees/codex/clip-e2e-15030286-7min-20261020/.venv/bin/python ~/SynologyDrive/GitHub/Active/sermon-video

Not copied: 6 .csv, 193 .json, 2 .jsonl, 24 .lock
