# Run digest 20261011-weekly-layer1

Generated 2026-10-11T15:41:32+00:00. Redacted copies only; source hashes are in manifest.json.

## layer1-54475d42

Source: `~/SynologyDrive/GitHub/Active/sermon-video-zh-subtitles/artifacts/weekend-live/layer1-54475d42`

- summary `attempts/a3-judge-input-bound/output/summary.json`: **english_source_candidate**
- summary `attempts/a4-judge-batch8-bound/output2/summary.json`: **english_source_candidate**
- summary `attempts/a5-judge-rejected-before-correction/output3/summary.json`: **english_source_candidate**
- summary `output4/summary.json`: **english_source_candidate**
- summary `output4-rebuild1/summary.json`: **english_source_candidate**
- summary `output4-rebuild2/summary.json`: **english_source_candidate**
- summary `output4-rebuild3/summary.json`: **english_source_candidate**
- summary `output4-rebuild4/summary.json`: **english_source_candidate**

Error-like log lines (first 5 per log):

- `attempts/a1-m4a-sample-count/execute1.log`: Traceback (most recent call last):
- `attempts/a1-m4a-sample-count/execute1.log`: raise ValueError(code)
- `attempts/a1-m4a-sample-count/execute1.log`: ValueError: source_extracted_audio_duration_changed
- `attempts/a1-m4a-sample-count/output/accounting/operations.log`: 2026-10-11T02:05:42.999869+00:00 ERROR run=69d093a536274716b76e664ee2b9ec5f stage_finished workflowId=0b47f3ebc46c493e83e8e580878e529a stage=unified_source_preparation spanId=64b6f85289044cba84ef71bf9
- `attempts/a1-m4a-sample-count/output/accounting/operations.log`: 2026-10-11T02:05:43.001822+00:00 ERROR run=69d093a536274716b76e664ee2b9ec5f workflow_finished workflowId=0b47f3ebc46c493e83e8e580878e529a status=failed
- `attempts/a1-m4a-sample-count/output/accounting/operations.log`: 2026-10-11T02:05:43.002011+00:00 ERROR run=69d093a536274716b76e664ee2b9ec5f run_finished workflowId=0b47f3ebc46c493e83e8e580878e529a status=failed
- `attempts/a2-spoken-forms-missing/execute2.log`: Traceback (most recent call last):
- `attempts/a2-spoken-forms-missing/execute2.log`: raise ValueError('Ambiguous numeric reference: configure its exact token in spoken forms before MFA')
- `attempts/a2-spoken-forms-missing/execute2.log`: ValueError: Ambiguous numeric reference: configure its exact token in spoken forms before MFA
- `attempts/a2-spoken-forms-missing/execute4.log`: Traceback (most recent call last):
- `attempts/a2-spoken-forms-missing/execute4.log`: raise ValueError(code)
- `attempts/a2-spoken-forms-missing/execute4.log`: ValueError: source_immutable_artifact_changed:mfa-preflight.json
- `attempts/a3-judge-input-bound/execute3.log`: Traceback (most recent call last):
- `attempts/a3-judge-input-bound/execute3.log`: raise ValueError(code)
- `attempts/a3-judge-input-bound/execute3.log`: ValueError: source_mfa_outcome_unknown_reconciliation_required
- `attempts/a3-judge-input-bound/execute5.log`: Traceback (most recent call last):
- `attempts/a3-judge-input-bound/execute5.log`: raise ValueError(code)
- `attempts/a3-judge-input-bound/execute5.log`: ValueError: provider_input_bound_exceeded
- `attempts/a3-judge-input-bound/output/accounting/operations.log`: 2026-10-11T02:13:15.404635+00:00 ERROR run=a9943d15d789457e94f2f45b476bcbd8 stage_finished workflowId=44a920bfb03e48a592e4768728e7268b stage=unified_source_preparation spanId=f848357d9739495eb578c14c1
- `attempts/a3-judge-input-bound/output/accounting/operations.log`: 2026-10-11T02:13:15.406201+00:00 ERROR run=a9943d15d789457e94f2f45b476bcbd8 workflow_finished workflowId=44a920bfb03e48a592e4768728e7268b status=failed
- `attempts/a3-judge-input-bound/output/accounting/operations.log`: 2026-10-11T02:13:15.406454+00:00 ERROR run=a9943d15d789457e94f2f45b476bcbd8 run_finished workflowId=44a920bfb03e48a592e4768728e7268b status=failed
- `attempts/a3-judge-input-bound/output/accounting/operations.log`: 2026-10-11T02:15:15.571291+00:00 ERROR run=5879c941c0b241f6a8a0faab46e417c1 stage_finished workflowId=82b2982f3be848619c89ef92fde77599 stage=unified_source_preparation spanId=5302921aae7743eeb2e9d5e35
- `attempts/a3-judge-input-bound/output/accounting/operations.log`: 2026-10-11T02:15:15.572625+00:00 ERROR run=5879c941c0b241f6a8a0faab46e417c1 workflow_finished workflowId=82b2982f3be848619c89ef92fde77599 status=failed
- `attempts/a4-judge-batch8-bound/execute6.log`: Traceback (most recent call last):
- `attempts/a4-judge-batch8-bound/execute6.log`: raise ValueError(code)
- `attempts/a4-judge-batch8-bound/execute6.log`: ValueError: provider_input_bound_exceeded
- `attempts/a4-judge-batch8-bound/monitor6.log`: ... 208 lines omitted; 0 error-like lines, 0 kept below ...
- `attempts/a4-judge-batch8-bound/output2/accounting/operations.log`: 2026-10-11T02:24:09.881939+00:00 ERROR run=9e4b161c9ac94a968e9a6a9ee800712e stage_finished workflowId=f5e49e895d92497ebf0dfe40b8455b73 stage=unified_source_preparation spanId=05b9f4a3ae0f4801a8c7d932c
- `attempts/a4-judge-batch8-bound/output2/accounting/operations.log`: 2026-10-11T02:24:09.883766+00:00 ERROR run=9e4b161c9ac94a968e9a6a9ee800712e workflow_finished workflowId=f5e49e895d92497ebf0dfe40b8455b73 status=failed
- `attempts/a4-judge-batch8-bound/output2/accounting/operations.log`: 2026-10-11T02:24:09.883974+00:00 ERROR run=9e4b161c9ac94a968e9a6a9ee800712e run_finished workflowId=f5e49e895d92497ebf0dfe40b8455b73 status=failed
- `attempts/a5-judge-rejected-before-correction/output3/accounting/operations.log`: 2026-10-11T02:30:10.276583+00:00 ERROR run=1f9c635ee361447b953f012195d0d75e stage_finished workflowId=0a9c3bbda2d04c228257e1b1dff82e7c stage=unified_source_preparation spanId=bbbe8422037a452eb0f021ff9
- `attempts/a5-judge-rejected-before-correction/output3/accounting/operations.log`: 2026-10-11T02:30:10.278434+00:00 ERROR run=1f9c635ee361447b953f012195d0d75e workflow_finished workflowId=0a9c3bbda2d04c228257e1b1dff82e7c status=failed
- `attempts/a5-judge-rejected-before-correction/output3/accounting/operations.log`: 2026-10-11T02:30:10.278611+00:00 ERROR run=1f9c635ee361447b953f012195d0d75e run_finished workflowId=0a9c3bbda2d04c228257e1b1dff82e7c status=failed
- `attempts/a6-phase1-preflight-before-2.7-form/execute10.log`: Traceback (most recent call last):
- `attempts/a6-phase1-preflight-before-2.7-form/execute10.log`: raise ValueError(code)
- `attempts/a6-phase1-preflight-before-2.7-form/execute10.log`: ValueError: source_text_review_required
- `attempts/a6-phase1-preflight-before-2.7-form/execute9.log`: Traceback (most recent call last):
- `attempts/a6-phase1-preflight-before-2.7-form/execute9.log`: raise self._exception
- `attempts/a6-phase1-preflight-before-2.7-form/execute9.log`: raise ValueError('source_budget_busy')
- `attempts/a6-phase1-preflight-before-2.7-form/execute9.log`: ValueError: source_budget_busy
- `attempts/execute7.log`: Traceback (most recent call last):
- `attempts/execute7.log`: if completed.returncode or response.get('error'): raise SessionError(response.get('error', 'ssh_failed_unknown'))
- `attempts/execute7.log`: scripts.spark_exclusive_session.SessionError: session_owner_mismatch
- `attempts/monitor7.log`: ... 256 lines omitted; 0 error-like lines, 0 kept below ...
- `execute11.log`: Traceback (most recent call last):
- `execute11.log`: raise self._exception
- `execute11.log`: raise ValueError(f'Unknown L1 request outcome; reconcile original response before retry: {marker}')
- `execute11.log`: ValueError: Unknown L1 request outcome; reconcile original response before retry: ~/SynologyDrive/GitHub/Active/sermon-video-zh-subtitles/artifacts/weekend-live/layer1-54475d42/output4/judge-requests/
- `output4/accounting/operations.log`: 2026-10-11T03:07:46.606593+00:00 ERROR run=6ec35846f1d94988be084b7902ac3a0c stage_finished workflowId=17c9a0d50af147bab4bc1b3a04892557 stage=unified_source_preparation spanId=63ae9ddc2d3f40ef98598c80e
- `output4/accounting/operations.log`: 2026-10-11T03:07:46.608040+00:00 ERROR run=6ec35846f1d94988be084b7902ac3a0c workflow_finished workflowId=17c9a0d50af147bab4bc1b3a04892557 status=failed
- `output4/accounting/operations.log`: 2026-10-11T03:07:46.608199+00:00 ERROR run=6ec35846f1d94988be084b7902ac3a0c run_finished workflowId=17c9a0d50af147bab4bc1b3a04892557 status=failed
- `output4/accounting/operations.log`: 2026-10-11T03:08:29.832235+00:00 ERROR run=5c0994b1c25041d881d8e8dc103774c0 stage_finished workflowId=1fc377e651374abc8e996fbead4aa72e stage=unified_source_preparation spanId=87c3e33b46a943c0b6af9e671
- `output4/accounting/operations.log`: 2026-10-11T03:08:29.833623+00:00 ERROR run=5c0994b1c25041d881d8e8dc103774c0 workflow_finished workflowId=1fc377e651374abc8e996fbead4aa72e status=failed
- `phase2.log`: 20:10:46 attempt 1 last: ValueError: source_budget_busy
- `phase2.log`: 20:10:53 attempt 2 last: ValueError: Unknown L1 request outcome; reconcile original response before retry: ~/SynologyDrive/Git
- `phase2b.log`: 20:12:56 attempt 1 judge=4/69 last: ValueError: source_budget_busy
- `phase2b.log`: 20:13:22 attempt 2 judge=6/69 last: ValueError: source_budget_busy
- `phase2b.log`: 20:13:47 attempt 3 judge=8/69 last: ValueError: source_budget_busy
- `phase2b.log`: 20:14:13 attempt 4 judge=10/69 last: ValueError: source_budget_busy
- `phase2b.log`: 20:14:41 attempt 5 judge=12/69 last: ValueError: source_budget_busy
- `rebuild3.log`: Traceback (most recent call last):
- `rebuild3.log`: raise ValueError("English source machine judge pass is internally inconsistent")
- `rebuild3.log`: ValueError: English source machine judge pass is internally inconsistent

Not copied: 15 .csv, 1425 .json, 6 .jsonl, 772 .lock, 5 .py, 52 .wav
