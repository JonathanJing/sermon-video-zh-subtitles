# Run digest 20261017-layer1-resi-1730-initial

Generated 2026-10-18T02:32:47+00:00. Redacted copies only; source hashes are in manifest.json.

## layer1-15030286-20261017

Source: `~/SynologyDrive/GitHub/Active/sermon-video-zh-subtitles/artifacts/weekend-live/layer1-15030286-20261017`

- outcome `outcome.json`: **blocked** exit ? (? → ?)
- summary `output-v2/summary.json`: **english_source_candidate**
- source budget `.jobs-v2.source-budget/source-budget.json`: 76 of 76 requests returned; reserved US$22.63; estimated US$5.50 over 65 priced; cost unknown: missing_or_invalid_token_counts ×11; invoice not verified
- source budget `.jobs.source-budget/source-budget.json`: 11 of 11 requests returned; reserved US$0.14; cost unknown: missing_or_invalid_token_counts ×11; invoice not verified

Error-like log lines (first 5 per log):

- `execute-stderr.log`: Traceback (most recent call last):
- `execute-stderr.log`: raise ValueError('Ambiguous numeric reference: configure its exact token in spoken forms before MFA')
- `execute-stderr.log`: ValueError: Ambiguous numeric reference: configure its exact token in spoken forms before MFA
- `execute-v2-stderr.log`: Traceback (most recent call last):
- `execute-v2-stderr.log`: if not session_id or not owner: raise SessionError('spark_exclusive_session_required')
- `execute-v2-stderr.log`: tongxing_production.compute.spark_exclusive_session.SessionError: spark_exclusive_session_required
- `output/accounting/operations.log`: 2026-10-18T02:10:06.230518+00:00 ERROR run=1e6f9d72d26141c2a438ff3245a049b3 stage_finished workflowId=39e45884207845d38e2c0e7676256584 stage=unified_source_preparation spanId=285ea443af3044d1b35515bc1
- `output/accounting/operations.log`: 2026-10-18T02:10:06.232256+00:00 ERROR run=1e6f9d72d26141c2a438ff3245a049b3 workflow_finished workflowId=39e45884207845d38e2c0e7676256584 status=failed
- `output/accounting/operations.log`: 2026-10-18T02:10:06.232424+00:00 ERROR run=1e6f9d72d26141c2a438ff3245a049b3 run_finished workflowId=39e45884207845d38e2c0e7676256584 status=failed
- `output-v2/accounting/operations.log`: 2026-10-18T02:11:42.762248+00:00 ERROR run=75ac391da24e4d2fa6cd1d9e381158b8 stage_finished workflowId=5f34ac2c7f414198b5517b55ed96072c stage=unified_source_preparation spanId=4bbfd720b84c479db63b1b96c
- `output-v2/accounting/operations.log`: 2026-10-18T02:11:42.763852+00:00 ERROR run=75ac391da24e4d2fa6cd1d9e381158b8 workflow_finished workflowId=5f34ac2c7f414198b5517b55ed96072c status=failed
- `output-v2/accounting/operations.log`: 2026-10-18T02:11:42.764011+00:00 ERROR run=75ac391da24e4d2fa6cd1d9e381158b8 run_finished workflowId=5f34ac2c7f414198b5517b55ed96072c status=failed

Not copied: 6 .csv, 306 .json, 2 .jsonl, 159 .lock, 24 .wav
