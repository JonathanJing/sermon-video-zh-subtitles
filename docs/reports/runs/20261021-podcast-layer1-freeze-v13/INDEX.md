# Run digest 20261021-podcast-layer1-freeze-v13

Generated 2026-10-21T18:34:39+00:00. Redacted copies only; source hashes are in manifest.json.

## layer1

Source: `~/SynologyDrive/GitHub/Active/sermon-video-zh-subtitles/artifacts/podcasts/if-i-had-more-time-jesus-sends-and-resurrects-his-own/layer1`

- summary `output-v10/summary.json`: **english_source_candidate**
- summary `output-v12/summary.json`: **english_source_candidate**
- summary `output-v13/summary.json`: **english_source_candidate**
- summary `output-v15/summary.json`: **english_source_candidate**
- summary `output-v16/summary.json`: **english_source_candidate**
- summary `output-v3/summary.json`: **english_source_candidate**
- summary `output-v4/summary.json`: **english_source_candidate**
- summary `output-v5/summary.json`: **english_source_candidate**
- summary `output-v6/summary.json`: **english_source_candidate**
- summary `output-v7/summary.json`: **english_source_candidate**
- summary `output-v8/summary.json`: **english_source_candidate**
- summary `output-v9/summary.json`: **english_source_candidate**
- source budget `.jobs-v10.source-budget/source-budget.json`: 133 of 133 requests returned; reserved US$20.36; estimated US$10.74 over 119 priced; cost unknown: missing_or_invalid_token_counts ×14; invoice not verified
- source budget `.jobs-v2.source-budget/source-budget.json`: 14 of 14 requests returned; reserved US$0.18; cost unknown: missing_or_invalid_token_counts ×14; invoice not verified
- source budget `.jobs-v3.source-budget/source-budget.json`: 14 of 18 requests returned; reserved US$0.97; cost unknown: missing_or_invalid_token_counts ×14; invoice not verified
- source budget `.jobs-v4.source-budget/source-budget.json`: 18 of 18 requests returned; reserved US$0.97; estimated US$0.47 over 4 priced; cost unknown: missing_or_invalid_token_counts ×14; invoice not verified
- source budget `.jobs-v5.source-budget/source-budget.json`: 106 of 106 requests returned; reserved US$14.96; estimated US$7.47 over 92 priced; cost unknown: missing_or_invalid_token_counts ×14; invoice not verified
- source budget `.jobs-v6.source-budget/source-budget.json`: 30 of 31 requests returned; reserved US$3.43; estimated US$1.83 over 16 priced; cost unknown: missing_or_invalid_token_counts ×14; invoice not verified
- source budget `.jobs-v7.source-budget/source-budget.json`: 36 of 36 requests returned; reserved US$4.39; estimated US$2.62 over 22 priced; cost unknown: missing_or_invalid_token_counts ×14; invoice not verified
- source budget `.jobs-v8.source-budget/source-budget.json`: 54 of 54 requests returned; reserved US$7.11; estimated US$3.81 over 40 priced; cost unknown: missing_or_invalid_token_counts ×14; invoice not verified
- source budget `.jobs-v9.source-budget/source-budget.json`: 134 of 134 requests returned; reserved US$20.52; estimated US$10.98 over 120 priced; cost unknown: missing_or_invalid_token_counts ×14; invoice not verified
- source budget `.jobs.source-budget/source-budget.json`: 14 of 14 requests returned; reserved US$0.18; cost unknown: missing_or_invalid_token_counts ×14; invoice not verified
- source budget `.output-v12.judge-budget/source-budget.json`: 0 of 6 requests returned; reserved US$0.98; invoice not verified
- source budget `.output-v13.judge-budget/source-budget.json`: 119 of 119 requests returned; reserved US$20.17; estimated US$10.74 over 119 priced; invoice not verified
- source budget `.output-v15.judge-budget/source-budget.json`: 34 of 35 requests returned; reserved US$5.95; estimated US$3.10 over 34 priced; invoice not verified
- source budget `.output-v16.judge-budget/source-budget.json`: 119 of 119 requests returned; reserved US$8.09; estimated US$2.09 over 119 priced; invoice not verified

Error-like log lines (first 5 per log):

- `execute-stderr.log`: Traceback (most recent call last):
- `execute-stderr.log`: raise ValueError('Ambiguous numeric reference: configure its exact token in spoken forms before MFA')
- `execute-stderr.log`: ValueError: Ambiguous numeric reference: configure its exact token in spoken forms before MFA
- `execute-v2-resume-stderr.log`: Traceback (most recent call last):
- `execute-v2-resume-stderr.log`: timeout=14460 if action == 'align' else 180)
- `execute-v2-resume-stderr.log`: raise CalledProcessError(retcode, process.args,
- `execute-v2-resume-stderr.log`: subprocess.CalledProcessError: Command '['ssh', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=15', '-o', 'HostKeyAlias=<host>', '<email>', 'ssh -o BatchMode=yes -o ConnectTimeout=15 <email> \'~/sermon-
- `execute-v2-resume-stderr.log`: The above exception was the direct cause of the following exception:
- `execute-v2-stderr.log`: Traceback (most recent call last):
- `execute-v2-stderr.log`: if not session_id or not owner: raise SessionError('spark_exclusive_session_required')
- `execute-v2-stderr.log`: tongxing_production.compute.spark_exclusive_session.SessionError: spark_exclusive_session_required
- `output/accounting/operations.log`: 2026-10-21T14:48:13.042595+00:00 ERROR run=ad3f26272f4148f8b117a82b9e6c6a33 stage_finished workflowId=34bc31708604449c903e1ba9cf55629a stage=unified_source_preparation spanId=02af3f4ab1b2423bb4b3d2aff
- `output/accounting/operations.log`: 2026-10-21T14:48:13.045948+00:00 ERROR run=ad3f26272f4148f8b117a82b9e6c6a33 workflow_finished workflowId=34bc31708604449c903e1ba9cf55629a status=failed
- `output/accounting/operations.log`: 2026-10-21T14:48:13.046281+00:00 ERROR run=ad3f26272f4148f8b117a82b9e6c6a33 run_finished workflowId=34bc31708604449c903e1ba9cf55629a status=failed
- `output-v10/accounting/operations.log`: ... 35 lines omitted; 0 error-like lines, 0 kept below ...
- `output-v2/accounting/operations.log`: 2026-10-21T14:53:29.631653+00:00 ERROR run=8749675b57664caa885dc91c7f7ae23f stage_finished workflowId=cb1aab878cdf4cb09c332c081c1aae22 stage=unified_source_preparation spanId=c4ef02ff18e04172a87a6c7cf
- `output-v2/accounting/operations.log`: 2026-10-21T14:53:29.635107+00:00 ERROR run=8749675b57664caa885dc91c7f7ae23f workflow_finished workflowId=cb1aab878cdf4cb09c332c081c1aae22 status=failed
- `output-v2/accounting/operations.log`: 2026-10-21T14:53:29.635509+00:00 ERROR run=8749675b57664caa885dc91c7f7ae23f run_finished workflowId=cb1aab878cdf4cb09c332c081c1aae22 status=failed
- `output-v2/accounting/operations.log`: 2026-10-21T14:57:05.113220+00:00 ERROR run=8dbf26ba993f47e5a933ed9b5d0f2eca stage_finished workflowId=17722c99a203434e93c3df2994aa1009 stage=unified_source_preparation spanId=aab8da42e1af4c1f8a2688e01
- `output-v2/accounting/operations.log`: 2026-10-21T14:57:05.115778+00:00 ERROR run=8dbf26ba993f47e5a933ed9b5d0f2eca workflow_finished workflowId=17722c99a203434e93c3df2994aa1009 status=failed
- `output-v3/accounting/operations.log`: 2026-10-21T16:17:54.206582+00:00 INFO run=65af7223e037458d986d24e4402b4dfa model_call_observation workflowId=f78ee058c568424c994439eed35d48c6 stage=unified_source_preparation spanId=4a5d4d836e4a42d69f
- `output-v3/accounting/operations.log`: 2026-10-21T16:17:54.292425+00:00 INFO run=65af7223e037458d986d24e4402b4dfa model_call_observation workflowId=f78ee058c568424c994439eed35d48c6 stage=unified_source_preparation spanId=4a5d4d836e4a42d69f
- `output-v3/accounting/operations.log`: 2026-10-21T16:17:54.293775+00:00 INFO run=65af7223e037458d986d24e4402b4dfa model_call_observation workflowId=f78ee058c568424c994439eed35d48c6 stage=unified_source_preparation spanId=4a5d4d836e4a42d69f
- `output-v3/accounting/operations.log`: 2026-10-21T16:17:54.341221+00:00 INFO run=65af7223e037458d986d24e4402b4dfa model_call_observation workflowId=f78ee058c568424c994439eed35d48c6 stage=unified_source_preparation spanId=4a5d4d836e4a42d69f
- `output-v3/accounting/operations.log`: 2026-10-21T16:17:54.344440+00:00 ERROR run=65af7223e037458d986d24e4402b4dfa stage_finished workflowId=f78ee058c568424c994439eed35d48c6 stage=unified_source_preparation spanId=4a5d4d836e4a42d69f2522a8f
- `output-v4/accounting/operations.log`: 2026-10-21T16:23:20.751572+00:00 ERROR run=7f5f33222ae74f42bcc46acc6005e0f7 stage_finished workflowId=004d2ed0a19d478d95c92cc77e9672c7 stage=unified_source_preparation spanId=59b99c03c2854dee8c1cee25a
- `output-v4/accounting/operations.log`: 2026-10-21T16:23:20.753801+00:00 ERROR run=7f5f33222ae74f42bcc46acc6005e0f7 workflow_finished workflowId=004d2ed0a19d478d95c92cc77e9672c7 status=failed
- `output-v4/accounting/operations.log`: 2026-10-21T16:23:20.754071+00:00 ERROR run=7f5f33222ae74f42bcc46acc6005e0f7 run_finished workflowId=004d2ed0a19d478d95c92cc77e9672c7 status=failed
- `output-v5/accounting/operations.log`: 2026-10-21T16:34:52.936598+00:00 ERROR run=ea21324e368742fa95ca91f456ac84df stage_finished workflowId=82dc81004320486e9a9da9e525166516 stage=unified_source_preparation spanId=aa4612b0421c4663828a6c126
- `output-v5/accounting/operations.log`: 2026-10-21T16:34:52.938537+00:00 ERROR run=ea21324e368742fa95ca91f456ac84df workflow_finished workflowId=82dc81004320486e9a9da9e525166516 status=failed
- `output-v5/accounting/operations.log`: 2026-10-21T16:34:52.938806+00:00 ERROR run=ea21324e368742fa95ca91f456ac84df run_finished workflowId=82dc81004320486e9a9da9e525166516 status=failed
- `output-v6/accounting/operations.log`: 2026-10-21T16:42:05.531880+00:00 INFO run=182790e25e944f61bf6e851e4a9499ac model_call_observation workflowId=b63f1a60dd524109a9119a07bddb2ae0 stage=unified_source_preparation spanId=1895dec84480488cb2
- `output-v6/accounting/operations.log`: 2026-10-21T16:42:35.920650+00:00 ERROR run=182790e25e944f61bf6e851e4a9499ac stage_finished workflowId=b63f1a60dd524109a9119a07bddb2ae0 stage=unified_source_preparation spanId=1895dec84480488cb202c6d99
- `output-v6/accounting/operations.log`: 2026-10-21T16:42:35.922638+00:00 ERROR run=182790e25e944f61bf6e851e4a9499ac workflow_finished workflowId=b63f1a60dd524109a9119a07bddb2ae0 status=failed
- `output-v6/accounting/operations.log`: 2026-10-21T16:42:35.922869+00:00 ERROR run=182790e25e944f61bf6e851e4a9499ac run_finished workflowId=b63f1a60dd524109a9119a07bddb2ae0 status=failed
- `output-v7/accounting/operations.log`: 2026-10-21T16:48:28.788685+00:00 ERROR run=a655d46334f242c893b95305aa09bd2c stage_finished workflowId=aed45795b3154788ad696d7930e4dbe5 stage=unified_source_preparation spanId=2208cff0e81e49a8850d6389c
- `output-v7/accounting/operations.log`: 2026-10-21T16:48:28.790908+00:00 ERROR run=a655d46334f242c893b95305aa09bd2c workflow_finished workflowId=aed45795b3154788ad696d7930e4dbe5 status=failed
- `output-v7/accounting/operations.log`: 2026-10-21T16:48:28.791085+00:00 ERROR run=a655d46334f242c893b95305aa09bd2c run_finished workflowId=aed45795b3154788ad696d7930e4dbe5 status=failed
- `output-v8/accounting/operations.log`: 2026-10-21T16:53:42.339100+00:00 ERROR run=7a8bcbf36a074be19b5f57f2339b0ab5 stage_finished workflowId=8cf0fe9e6e744330981b0a482e7c7951 stage=unified_source_preparation spanId=539451c9c736454cb24f28021
- `output-v8/accounting/operations.log`: 2026-10-21T16:53:42.341015+00:00 ERROR run=7a8bcbf36a074be19b5f57f2339b0ab5 workflow_finished workflowId=8cf0fe9e6e744330981b0a482e7c7951 status=failed
- `output-v8/accounting/operations.log`: 2026-10-21T16:53:42.341179+00:00 ERROR run=7a8bcbf36a074be19b5f57f2339b0ab5 run_finished workflowId=8cf0fe9e6e744330981b0a482e7c7951 status=failed
- `output-v9/accounting/operations.log`: ... 37 lines omitted; 0 error-like lines, 0 kept below ...
- `rebuild-v11.log`: Traceback (most recent call last):
- `rebuild-v11.log`: raise ValueError(f"Boundary override lacks a safe clause split: {words[index]['wordId']}")
- `rebuild-v11.log`: ValueError: Boundary override lacks a safe clause split: chunk-0007-w0234
- `rebuild-v12-stderr.log`: Traceback (most recent call last):
- `rebuild-v12-stderr.log`: raise self._exception
- `rebuild-v12-stderr.log`: raise RuntimeError('claude_language_model_identity_missing')
- `rebuild-v12-stderr.log`: RuntimeError: claude_language_model_identity_missing
- `rebuild-v12.log`: Traceback (most recent call last):
- `rebuild-v12.log`: raise ValueError("Boundary override is unnecessary for a sentence within the duration target")
- `rebuild-v12.log`: ValueError: Boundary override is unnecessary for a sentence within the duration target
- `rebuild-v14.log`: Traceback (most recent call last):
- `rebuild-v14.log`: raise ValueError(f"Boundary override lacks a safe clause split: {words[index]['wordId']}")
- `rebuild-v14.log`: ValueError: Boundary override lacks a safe clause split: chunk-0011-w0136
- `rebuild-v15.log`: Traceback (most recent call last):
- `rebuild-v15.log`: # groups after a failed/unknown sibling. Context-bound request caps are
- `rebuild-v15.log`: raise self._exception
- `rebuild-v15.log`: raise RuntimeError('claude_language_terminal_failure_inspect_receipt')
- `rebuild-v15.log`: RuntimeError: claude_language_terminal_failure_inspect_receipt
- `run-v3.log`: Traceback (most recent call last):
- `run-v3.log`: raise self._exception
- `run-v3.log`: raise RuntimeError('claude_language_terminal_failure_inspect_receipt')
- `run-v3.log`: RuntimeError: claude_language_terminal_failure_inspect_receipt
- `run-v4.log`: Traceback (most recent call last):
- `run-v4.log`: raise self._exception
- `run-v4.log`: raise ValueError(code)
- `run-v4.log`: ValueError: source_judge_input_bound_exceeded
- `run-v5.log`: Traceback (most recent call last):
- `run-v5.log`: raise self._exception
- `run-v5.log`: raise ValueError(code)
- `run-v5.log`: ValueError: source_budget_exhausted
- `run-v6.log`: Traceback (most recent call last):
- `run-v6.log`: raise self._exception
- `run-v6.log`: raise RuntimeError('claude_language_unexpected_turn_count')
- `run-v6.log`: RuntimeError: claude_language_unexpected_turn_count
- `run-v7.log`: Traceback (most recent call last):
- `run-v7.log`: raise self._exception
- `run-v7.log`: raise ValueError(code)
- `run-v7.log`: ValueError: source_judge_input_bound_exceeded
- `run-v8.log`: Traceback (most recent call last):
- `run-v8.log`: raise self._exception
- `run-v8.log`: raise ValueError(code)
- `run-v8.log`: ValueError: source_judge_input_bound_exceeded

Not copied: 30 .csv, 5005 .json, 10 .jsonl, 1576 .lock, 584 .txt, 150 .wav

## output-v13

Source: `~/SynologyDrive/GitHub/Active/sermon-video-zh-subtitles/artifacts/podcasts/if-i-had-more-time-jesus-sends-and-resurrects-his-own/layer1/output-v13`

- summary `summary.json`: **english_source_candidate**

Not copied: 717 .json, 120 .lock, 119 .txt

## output-v16

Source: `~/SynologyDrive/GitHub/Active/sermon-video-zh-subtitles/artifacts/podcasts/if-i-had-more-time-jesus-sends-and-resurrects-his-own/layer1/output-v16`

- summary `summary.json`: **english_source_candidate**

Not copied: 241 .json, 120 .lock
