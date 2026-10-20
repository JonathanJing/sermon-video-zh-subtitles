# Run digest 20261019-layer2-binding-memo-replay

Generated 2026-10-19T20:27:01+00:00. Redacted copies only; source hashes are in manifest.json.

## replay-base

Source: `<scratchpad>/replay-base`

- outcome `outcome.json`: **stopped_at_first_cache_miss** exit 1 (2026-10-19T20:12:53+00:00 → 2026-10-19T20:14:18+00:00)

Error-like log lines (first 5 per log):

- `out/zh-Hans/accounting/operations.log`: ... 277 lines omitted; 0 error-like lines, 0 kept below ...
- `out/zh-Hans/accounting/operations.log`: 2026-10-19T20:14:18.102420+00:00 ERROR run=cd6a8bf8117a4bec823f18ca415d69d1 stage_finished workflowId=ab5a21c01662427c9175c895bb48a082 stage=layer2.translator.zh-Hans.group-0025 spanId=c6d250744b714b9
- `out/zh-Hans/accounting/operations.log`: 2026-10-19T20:14:18.103346+00:00 ERROR run=cd6a8bf8117a4bec823f18ca415d69d1 stage_finished workflowId=ab5a21c01662427c9175c895bb48a082 stage=layer2.group.zh-Hans.0025 spanId=2e719f296fe9441497dd8d3ec7
- `out/zh-Hans/accounting/operations.log`: 2026-10-19T20:14:18.104310+00:00 ERROR run=cd6a8bf8117a4bec823f18ca415d69d1 stage_finished workflowId=ab5a21c01662427c9175c895bb48a082 stage=layer2_models spanId=f261286c9c154b928799b8166c5f2974 attem
- `out/zh-Hans/accounting/operations.log`: 2026-10-19T20:14:18.106143+00:00 ERROR run=cd6a8bf8117a4bec823f18ca415d69d1 workflow_finished workflowId=ab5a21c01662427c9175c895bb48a082 stage=canonical_layer2_worker spanId=a15651d7235f480793c1f4370

Not copied: 3 .csv, 178 .json, 1 .jsonl, 4 .lock

## replay-after

Source: `<scratchpad>/replay-after`

- outcome `outcome.json`: **stopped_at_first_cache_miss** exit 1 (2026-10-19T20:12:36+00:00 → 2026-10-19T20:12:52+00:00)

Error-like log lines (first 5 per log):

- `out/zh-Hans/accounting/operations.log`: ... 277 lines omitted; 0 error-like lines, 0 kept below ...
- `out/zh-Hans/accounting/operations.log`: 2026-10-19T20:12:52.935749+00:00 ERROR run=ec6dc33d14c7431296070d49d757c5da stage_finished workflowId=107745e1892843f58eef22f5822f4502 stage=layer2.translator.zh-Hans.group-0025 spanId=cf34c2dd1d3243c
- `out/zh-Hans/accounting/operations.log`: 2026-10-19T20:12:52.937132+00:00 ERROR run=ec6dc33d14c7431296070d49d757c5da stage_finished workflowId=107745e1892843f58eef22f5822f4502 stage=layer2.group.zh-Hans.0025 spanId=5baa421b3e9c48fd942a297317
- `out/zh-Hans/accounting/operations.log`: 2026-10-19T20:12:52.938520+00:00 ERROR run=ec6dc33d14c7431296070d49d757c5da stage_finished workflowId=107745e1892843f58eef22f5822f4502 stage=layer2_models spanId=d73314b383814cb5ae80617a7e8e56f9 attem
- `out/zh-Hans/accounting/operations.log`: 2026-10-19T20:12:52.941389+00:00 ERROR run=ec6dc33d14c7431296070d49d757c5da workflow_finished workflowId=107745e1892843f58eef22f5822f4502 stage=canonical_layer2_worker spanId=bed6304ee467497185dd70e5b

Not copied: 3 .csv, 178 .json, 1 .jsonl, 4 .lock
