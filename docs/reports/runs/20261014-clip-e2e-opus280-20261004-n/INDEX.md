# Run digest 20261014-clip-e2e-opus280-20261004-n

Generated 2026-10-14T21:15:51+00:00. Redacted copies only; source hashes are in manifest.json.

## clip-e2e-20261004-opus-n

Source: `~/SynologyDrive/GitHub/Active/sermon-video-zh-subtitles/artifacts/clip-e2e-20261004-opus-n`


Timings `timings.tsv`:

| timeline-map | pass | 0 |
|---|---|---|
| route-probe | pass | 0 |
| plan-layer2 | pass | 0 |
| check-layer2 | pass | 1 |
| layer2 | pass | 2 |
| layer2 | pass | 0 |

Error-like log lines (first 5 per log):

- `l2/layer2-jobs/4ddb53255ed5eee621a6d1fd048533eebdac3ef597f4b6866f74cd660658760f/worker.log`: Traceback (most recent call last):
- `l2/layer2-jobs/4ddb53255ed5eee621a6d1fd048533eebdac3ef597f4b6866f74cd660658760f/worker.log`: raise self._exception
- `l2/layer2-jobs/4ddb53255ed5eee621a6d1fd048533eebdac3ef597f4b6866f74cd660658760f/worker.log`: if not condition: raise ContractError(code)
- `l2/layer2-jobs/4ddb53255ed5eee621a6d1fd048533eebdac3ef597f4b6866f74cd660658760f/worker.log`: scripts.sermon_review_contracts.ContractError: budget_ledger_size_limit
- `l2/layer2-jobs/7b9bb3dd230ab81b1881648d3cf38679103bbcfa8f2e1f8a47e00f449f259027/worker.log`: Traceback (most recent call last):
- `l2/layer2-jobs/7b9bb3dd230ab81b1881648d3cf38679103bbcfa8f2e1f8a47e00f449f259027/worker.log`: raise ValueError(message)
- `l2/layer2-jobs/7b9bb3dd230ab81b1881648d3cf38679103bbcfa8f2e1f8a47e00f449f259027/worker.log`: ValueError: Output directory is not empty
- `l2/layer2-jobs/88cdd0f2d994626158363dab2a49f2f4874568866fa3ff2fc26110818cb14f7a/worker.log`: Traceback (most recent call last):
- `l2/layer2-jobs/88cdd0f2d994626158363dab2a49f2f4874568866fa3ff2fc26110818cb14f7a/worker.log`: raise self._exception
- `l2/layer2-jobs/88cdd0f2d994626158363dab2a49f2f4874568866fa3ff2fc26110818cb14f7a/worker.log`: if not condition: raise ContractError(code)
- `l2/layer2-jobs/88cdd0f2d994626158363dab2a49f2f4874568866fa3ff2fc26110818cb14f7a/worker.log`: scripts.sermon_review_contracts.ContractError: budget_ledger_size_limit
- `l2/text/es/accounting/operations.log`: ... 723 lines omitted; 0 error-like lines, 0 kept below ...
- `l2/text/es/accounting/operations.log`: 2026-10-14T21:14:25.538384+00:00 ERROR run=c50c7559a0e741d5a5aae2a47bef56b4 stage_finished workflowId=71d06a65b363497e876b6e40ab7185b3 stage=layer2.translator.es.group-0044 spanId=cfe867838fb34fda8c76
- `l2/text/es/accounting/operations.log`: 2026-10-14T21:14:25.539301+00:00 ERROR run=c50c7559a0e741d5a5aae2a47bef56b4 stage_finished workflowId=71d06a65b363497e876b6e40ab7185b3 stage=layer2.group.es.0044 spanId=892457c5450d4b2ea9ca9ca965a6b40
- `l2/text/es/accounting/operations.log`: 2026-10-14T21:14:26.096879+00:00 ERROR run=c50c7559a0e741d5a5aae2a47bef56b4 stage_finished workflowId=71d06a65b363497e876b6e40ab7185b3 stage=layer2.reviewer.es.group-0040 spanId=972688abd37641468b124a
- `l2/text/es/accounting/operations.log`: 2026-10-14T21:14:26.097796+00:00 ERROR run=c50c7559a0e741d5a5aae2a47bef56b4 stage_finished workflowId=71d06a65b363497e876b6e40ab7185b3 stage=layer2.group.es.0040 spanId=7f581307b36a41888b381b49c62b3da
- `l2/text/ko/accounting/operations.log`: 2026-10-14T21:13:23.233820+00:00 ERROR run=66cc49754e624d16b13cfde7cdefde6c stage_finished workflowId=194ddfa09b3c4f01ac1d729c38475fa9 stage=layer2.run_admission.ko spanId=a514ffac8bad4e7a91763e2a3735
- `l2/text/ko/accounting/operations.log`: 2026-10-14T21:13:23.234411+00:00 ERROR run=66cc49754e624d16b13cfde7cdefde6c stage_finished workflowId=194ddfa09b3c4f01ac1d729c38475fa9 stage=layer2_models spanId=06a949d39023493db0abe27d2cf69132 attem
- `l2/text/ko/accounting/operations.log`: 2026-10-14T21:13:23.235877+00:00 ERROR run=66cc49754e624d16b13cfde7cdefde6c workflow_finished workflowId=194ddfa09b3c4f01ac1d729c38475fa9 stage=canonical_layer2_worker spanId=46777b4ec5d44a808cb303a00
- `l2/text/ko/accounting/operations.log`: 2026-10-14T21:13:23.236622+00:00 ERROR run=66cc49754e624d16b13cfde7cdefde6c stage_finished workflowId=25256cda324b4ef59e6ed9ecea893e2b stage=canonical_layer2_worker spanId=46777b4ec5d44a808cb303a00050
- `l2/text/ko/accounting/operations.log`: 2026-10-14T21:13:23.237988+00:00 ERROR run=66cc49754e624d16b13cfde7cdefde6c workflow_finished workflowId=25256cda324b4ef59e6ed9ecea893e2b status=failed
- `l2/text/zh-Hans/accounting/operations.log`: ... 653 lines omitted; 0 error-like lines, 0 kept below ...
- `l2/text/zh-Hans/accounting/operations.log`: 2026-10-14T21:14:24.330208+00:00 ERROR run=6e8c252fe4964dc3bc5d02f7a4d65432 stage_finished workflowId=f63e1dbfcef34151be068703a6f3a6e8 stage=layer2.reviewer.zh-Hans.group-0037 spanId=80bc26dff7244e2db
- `l2/text/zh-Hans/accounting/operations.log`: 2026-10-14T21:14:24.331363+00:00 ERROR run=6e8c252fe4964dc3bc5d02f7a4d65432 stage_finished workflowId=f63e1dbfcef34151be068703a6f3a6e8 stage=layer2.group.zh-Hans.0037 spanId=4613edb29ebb45d2ba8f0f4120
- `l2/text/zh-Hans/accounting/operations.log`: 2026-10-14T21:14:24.694020+00:00 ERROR run=6e8c252fe4964dc3bc5d02f7a4d65432 stage_finished workflowId=f63e1dbfcef34151be068703a6f3a6e8 stage=layer2.reviewer.zh-Hans.group-0039 spanId=f5beb0f90b32426d8
- `l2/text/zh-Hans/accounting/operations.log`: 2026-10-14T21:14:24.694831+00:00 ERROR run=6e8c252fe4964dc3bc5d02f7a4d65432 stage_finished workflowId=f63e1dbfcef34151be068703a6f3a6e8 stage=layer2.group.zh-Hans.0039 spanId=0e5f5f870edb44228b0644ebb4
- `logs/check-layer2.log`: "failed": [],
- `logs/plan-layer2.log`: == 2026-10-14T21:13:19+00:00 ~/SynologyDrive/GitHub/Active/sermon-video-zh-subtitles/.venv/bin/python ~/.codex/worktrees/opus-layer1-larger-clip/sermon-video-zh-subtitles/scripts/run_with_openai_envir

Not copied: 9 .csv, 1683 .json, 3 .jsonl, 27 .lock, 2 .py, 159 .txt
