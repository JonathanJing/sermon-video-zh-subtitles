# Run digest 20261019-facade-c4-rebased-local

Generated 2026-10-19T23:40:50+00:00. Redacted copies only; source hashes are in manifest.json.

## c4-local-r2

Source: `~/SynologyDrive/GitHub/Active/sermon-video-zh-subtitles/.claude/worktrees/opus-haiku-translation-review-4a3b7c/artifacts/c4-local-r2`

- outcome `outcome.json`: **passed** exit 0 (2026-10-19T23:01:54Z → 2026-10-19T23:38:19Z)
- summary `summary.json`: **passed**

Error-like log lines (first 5 per log):

- `pytest.log`: >       with patch.object(slots.Admission, 'reserve', side_effect=slots.contracts.ContractError('resource_broker_busy')):
- `pytest.log`: E       AttributeError: module 'tongxing_production.compute.transports.codex_resources' has no attribute 'contracts'
- `pytest.log`: tests/test_codex_shared_pool_transport.py:62: AttributeError
- `pytest.log`: FAILED tests/test_codex_shared_pool_transport.py::test_busy_before_started_is_proven_no_dispatch
- `pytest.log`: 1 failed, 1111 passed, 27 subtests passed in 117.52s (0:01:57)
- `shards/s0.log`: ... 136 lines omitted; 3 error-like lines, 3 kept below ...
- `shards/s0.log`: [line 98]   "reason": "every shorten group failed its checks; those groups stay subtitle-only in the dub",
- `shards/s0.log`: [line 102]   "failedGroupIds": [
- `shards/s0.log`: [line 149] Generation failed: RuntimeError
- `shards/s1.log`: ... 79 lines omitted; 1 error-like lines, 1 kept below ...
- `shards/s1.log`: [line 111] run_unittest_ci.py: error: --candidate 'k0=/var/folders/s2/0bt6pz_51h1899zqs32x4vm80000gn/T/tmpon7urmfj/run/diagnostic-previews/ko/native-1/candidate.json': use LOCALE=PATH once per request
- `shards/s1.log`: run_unittest_ci.py: error: --candidate 'es=/var/folders/s2/0bt6pz_51h1899zqs32x4vm80000gn/T/tmpon7urmfj/run/diagnostic-previews/ko/native-1/candidate.json': use LOCALE=PATH once per requested locale (
- `shards/s1.log`: run_unittest_ci.py: error: --candidate '/var/folders/s2/0bt6pz_51h1899zqs32x4vm80000gn/T/tmpon7urmfj/run/diagnostic-previews/ko/native-1/candidate.json': use LOCALE=PATH once per requested locale (ko)
- `shards/s1.log`: run_unittest_ci.py: error: --candidate 'ko=/var/folders/s2/0bt6pz_51h1899zqs32x4vm80000gn/T/tmpon7urmfj/run/diagnostic-previews/ko/native-1/candidate.json': use LOCALE=PATH once per requested locale (
- `shards/s2.log`: run_unittest_ci.py: error: Reuse root has no paid ledger to reconcile
- `shards/s2.log`: run_unittest_ci.py: error: Duplicate reuse root; list each approved source only once
- `shards/s2.log`: "failedGroupIds": []
- `shards/s2.log`: "status": "error",
- `shards/s2.log`: "reason": "ValueError: /private/var/folders/s2/0bt6pz_51h1899zqs32x4vm80000gn/T/tmpcvwqs2fz/out/condensation-record-17af5c10d60c2500.json changed after it was written",
- `shards/s3.log`: progress: error: ledger already exists; refusing to overwrite
- `shards/s3.log`: .......................................SERMON_LOGGING_WRITE_FAILED errorType=AccountingWriteError
- `shards/s3.log`: ... 251 lines omitted; 9 error-like lines, 9 kept below ...
- `shards/s3.log`: [line 42] run_unittest_ci.py: error: recording a decision needs --choice, --decided-by
- `shards/s3.log`: [line 84]         "error": null,
- `shards/s4.log`: run_unittest_ci.py: error: argument --risk-repeats: must be a positive integer
- `shards/s4.log`: ... 532 lines omitted; 13 error-like lines, 13 kept below ...
- `shards/s4.log`: [line 246] run_unittest_ci.py: error: Choose replay-only --reuse-from or --resume-qc-authorization, not both
- `shards/s4.log`: [line 301] run_unittest_ci.py: error: --locales must name one or more of zh-Hans, ko, es
- `shards/s4.log`: [line 311] run_unittest_ci.py: error: --locales must name one or more of zh-Hans, ko, es
- `shards/s5.log`: run_unittest_ci.py: error: /var/folders/s2/0bt6pz_51h1899zqs32x4vm80000gn/T/tmpwl88ubm9/digests/20261007-e2e already exists; pick another --name
- `shards/s5.log`: run_unittest_ci.py: error: --name must be YYYYMMDD-<label> using ASCII letters, digits, '.', '_' and '-'
- `shards/s5.log`: .......................................SERMON_LOGGING_WRITE_FAILED errorType=AccountingWriteError
- `shards/s5.log`: ....SERMON_LOGGING_WRITE_FAILED errorType=AccountingWriteError
- `shards/s5.log`: "reason": "text QC failed; repair the failed groups in a new candidate revision",
- `shards/s6.log`: .............................................................................................................................SERMON_LOGGING_WRITE_FAILED errorType=AccountingWriteError
- `shards/s6.log`: ... 162 lines omitted; 4 error-like lines, 4 kept below ...
- `shards/s6.log`: [line 63] run_unittest_ci.py: error: the secondary ASR uses the OpenAI API: start under scripts/run_with_openai_environment.py --environment dev (prod for formal content)
- `shards/s6.log`: [line 79] run_unittest_ci.py: error: real audio runs require --api-budget-authorization (planned per-locale QC authorization v4), including --text-backend codex for the secondary ASR budget
- `shards/s6.log`: [line 121] .Model initialization failed: ValueError: test initialization failure
- `shards/s7.log`: run_unittest_ci.py: error: --name must be YYYYMMDD-<label> using ASCII letters, digits, '.', '_' and '-'
- `shards/s7.log`: runtime_tts_mac.py: error: this bounded diagnostic writes only its declared output directory
- `shards/s7.log`: ... 28 lines omitted; 0 error-like lines, 0 kept below ...
- `shards/s7.log`: "status": "error",
- `shards/s7.log`: "reason": "ValueError: /private/var/folders/s2/0bt6pz_51h1899zqs32x4vm80000gn/T/tmpib0bo83o/real/ko/text-waiver-64489bf8499932b4.json changed after it was written",
- `shards/s8.log`: {"component": "api", "errorClass": "ConnectionError", "event": "sermon_production_supervisor_source_check_failed", "loggedAt": "2026-10-19T23:02:30.734505+00:00", "mode": "shadow", "severity": "ERROR"
- `shards/s8.log`: run_unittest_ci.py: error: output directory already exists: /var/folders/s2/0bt6pz_51h1899zqs32x4vm80000gn/T/tmp2xpietdl/sheet
- `shards/s8.log`: run_unittest_ci.py build: error: the following arguments are required: --screening
- `shards/s8.log`: ... 229 lines omitted; 4 error-like lines, 4 kept below ...
- `shards/s8.log`: [line 62]     "reason": "audio QC failed; re-render the failed units as the repair ladder says",
- `shards/s9.log`: ... 102 lines omitted; 7 error-like lines, 7 kept below ...
- `shards/s9.log`: [line 46]     "reason": "text QC failed; repair the failed groups in a new candidate revision",
- `shards/s9.log`: [line 55]     "reason": "failed groups are unchanged; repair them in a new candidate revision",
- `shards/s9.log`: [line 66]     "reason": "text QC failed; repair the failed groups in a new candidate revision",
- `shards/s9.log`: [line 75]     "reason": "failed groups are unchanged; repair them in a new candidate revision",

Not copied: 10 .json, 3 .txt
