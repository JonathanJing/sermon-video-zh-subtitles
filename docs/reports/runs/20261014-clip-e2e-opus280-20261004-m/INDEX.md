# Run digest 20261014-clip-e2e-opus280-20261004-m

Generated 2026-10-14T21:11:06+00:00. Redacted copies only; source hashes are in manifest.json.

## clip-e2e-20261004-opus-m

Source: `~/SynologyDrive/GitHub/Active/sermon-video-zh-subtitles/artifacts/clip-e2e-20261004-opus-m`


Timings `timings.tsv`:

| timeline-map | pass | 0 |
|---|---|---|
| route-probe | pass | 0 |
| plan-layer2 | pass | 0 |
| check-layer2 | pass | 1 |
| layer2 | pass | 2 |
| layer2 | pass | 0 |

Error-like log lines (first 5 per log):

- `l2/layer2-jobs/111e446bcf33d98906fda22e22440a8d8339766133ea988374438d92e56b0ce5/worker.log`: Traceback (most recent call last):
- `l2/layer2-jobs/111e446bcf33d98906fda22e22440a8d8339766133ea988374438d92e56b0ce5/worker.log`: raise ValueError(message)
- `l2/layer2-jobs/111e446bcf33d98906fda22e22440a8d8339766133ea988374438d92e56b0ce5/worker.log`: ValueError: CLI transport supports same-run resume only; cross-run cache reuse is not enabled
- `l2/layer2-jobs/4c2d3b80347fd08b18f7cdf601512e63abaad2b05caf3cbbddc0bbcbe20ad9b7/worker.log`: Traceback (most recent call last):
- `l2/layer2-jobs/4c2d3b80347fd08b18f7cdf601512e63abaad2b05caf3cbbddc0bbcbe20ad9b7/worker.log`: raise self._exception
- `l2/layer2-jobs/4c2d3b80347fd08b18f7cdf601512e63abaad2b05caf3cbbddc0bbcbe20ad9b7/worker.log`: raise ValueError(code)
- `l2/layer2-jobs/4c2d3b80347fd08b18f7cdf601512e63abaad2b05caf3cbbddc0bbcbe20ad9b7/worker.log`: ValueError: provider_input_bound_exceeded
- `l2/layer2-jobs/6098e169a86f70ab2f45671dba9622e0796d175d267707f206f2766513a70093/worker.log`: Traceback (most recent call last):
- `l2/layer2-jobs/6098e169a86f70ab2f45671dba9622e0796d175d267707f206f2766513a70093/worker.log`: raise self._exception
- `l2/layer2-jobs/6098e169a86f70ab2f45671dba9622e0796d175d267707f206f2766513a70093/worker.log`: raise ValueError(code)
- `l2/layer2-jobs/6098e169a86f70ab2f45671dba9622e0796d175d267707f206f2766513a70093/worker.log`: ValueError: provider_input_bound_exceeded
- `l2/text/es/accounting/operations.log`: 2026-10-14T21:07:52.458671+00:00 ERROR run=cf954076acaa447fb85de9ecf1202a88 stage_finished workflowId=cd4661ba3e4e4935ba5d74cecd169302 stage=layer2.translator.es.group-0001 spanId=4a951161b2274e5ebbe1
- `l2/text/es/accounting/operations.log`: 2026-10-14T21:07:52.468657+00:00 ERROR run=cf954076acaa447fb85de9ecf1202a88 stage_finished workflowId=cd4661ba3e4e4935ba5d74cecd169302 stage=layer2.translator.es.group-0002 spanId=6481483c260e46bdb9be
- `l2/text/es/accounting/operations.log`: 2026-10-14T21:07:52.468934+00:00 ERROR run=cf954076acaa447fb85de9ecf1202a88 stage_finished workflowId=cd4661ba3e4e4935ba5d74cecd169302 stage=layer2.translator.es.group-0005 spanId=51db9d933e834a629866
- `l2/text/es/accounting/operations.log`: 2026-10-14T21:07:52.469457+00:00 ERROR run=cf954076acaa447fb85de9ecf1202a88 stage_finished workflowId=cd4661ba3e4e4935ba5d74cecd169302 stage=layer2.group.es.0001 spanId=c39ee1622df14b97bdb8a89ba7f7aec
- `l2/text/es/accounting/operations.log`: 2026-10-14T21:07:52.469939+00:00 ERROR run=cf954076acaa447fb85de9ecf1202a88 stage_finished workflowId=cd4661ba3e4e4935ba5d74cecd169302 stage=layer2.translator.es.group-0003 spanId=562f04b309b143588c0e
- `l2/text/ko/accounting/operations.log`: ... 903 lines omitted; 0 error-like lines, 0 kept below ...
- `l2/text/ko/accounting/operations.log`: 2026-10-14T21:09:16.689172+00:00 ERROR run=b19a7f68cd9148ceb17610c5b0fd96b2 stage_finished workflowId=1b1c4ed9e1054be5b376ba5fcf1c50c5 stage=layer2_models spanId=903317c00906447a8fcbd6e0ad502df7 attem
- `l2/text/ko/accounting/operations.log`: 2026-10-14T21:09:16.691427+00:00 ERROR run=b19a7f68cd9148ceb17610c5b0fd96b2 workflow_finished workflowId=1b1c4ed9e1054be5b376ba5fcf1c50c5 stage=canonical_layer2_worker spanId=4d634e1a658641b78d5820153
- `l2/text/ko/accounting/operations.log`: 2026-10-14T21:09:16.811407+00:00 ERROR run=b19a7f68cd9148ceb17610c5b0fd96b2 stage_finished workflowId=65b772dbebe54b948338f8923ab64321 stage=layer2.run_admission.ko spanId=b3a2270c5d5b4f2197e832b9beca
- `l2/text/ko/accounting/operations.log`: 2026-10-14T21:09:16.811962+00:00 ERROR run=b19a7f68cd9148ceb17610c5b0fd96b2 stage_finished workflowId=65b772dbebe54b948338f8923ab64321 stage=layer2_models spanId=671e494bee3a447b81dd3b769046f093 attem
- `l2/text/zh-Hans/accounting/operations.log`: 2026-10-14T21:07:52.888976+00:00 ERROR run=11d1b9c5059749cfad5657c6b74cef3e stage_finished workflowId=447b65f696ae4c05bc85bec7400fa8a7 stage=layer2.translator.zh-Hans.group-0001 spanId=c30f61157a4447b
- `l2/text/zh-Hans/accounting/operations.log`: 2026-10-14T21:07:52.900206+00:00 ERROR run=11d1b9c5059749cfad5657c6b74cef3e stage_finished workflowId=447b65f696ae4c05bc85bec7400fa8a7 stage=layer2.translator.zh-Hans.group-0003 spanId=3e8fa6b0ca65442
- `l2/text/zh-Hans/accounting/operations.log`: 2026-10-14T21:07:52.901004+00:00 ERROR run=11d1b9c5059749cfad5657c6b74cef3e stage_finished workflowId=447b65f696ae4c05bc85bec7400fa8a7 stage=layer2.group.zh-Hans.0001 spanId=6166735a6417471a9d63743b26
- `l2/text/zh-Hans/accounting/operations.log`: 2026-10-14T21:07:52.901339+00:00 ERROR run=11d1b9c5059749cfad5657c6b74cef3e stage_finished workflowId=447b65f696ae4c05bc85bec7400fa8a7 stage=layer2.translator.zh-Hans.group-0006 spanId=5ee74519720142e
- `l2/text/zh-Hans/accounting/operations.log`: 2026-10-14T21:07:52.901895+00:00 ERROR run=11d1b9c5059749cfad5657c6b74cef3e stage_finished workflowId=447b65f696ae4c05bc85bec7400fa8a7 stage=layer2.translator.zh-Hans.group-0005 spanId=edabbb1874db42d
- `logs/check-layer2.log`: "failed": [],
- `logs/plan-layer2.log`: == 2026-10-14T21:07:48+00:00 ~/SynologyDrive/GitHub/Active/sermon-video-zh-subtitles/.venv/bin/python ~/.codex/worktrees/opus-layer1-larger-clip/sermon-video-zh-subtitles/scripts/run_with_openai_envir

Not copied: 9 .csv, 940 .json, 3 .jsonl, 19 .lock, 2 .py, 100 .txt
