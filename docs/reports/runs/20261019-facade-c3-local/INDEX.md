# Run digest 20261019-facade-c3-local

Generated 2026-10-19T21:19:43+00:00. Redacted copies only; source hashes are in manifest.json.

## c3-local

Source: `~/SynologyDrive/GitHub/Active/sermon-video-zh-subtitles/.claude/worktrees/opus-haiku-translation-review-4a3b7c/artifacts/c3-local`

- outcome `outcome.json`: **passed_with_load_flakes_and_env_errors** exit 1 (2026-10-19T20:46:32Z → 2026-10-19T21:18:15Z)
- summary `summary.json`: **passed_with_load_flakes_and_env_errors**

Error-like log lines (first 5 per log):

- `pytest.log`: >       with patch.object(slots.Admission, 'reserve', side_effect=slots.contracts.ContractError('resource_broker_busy')):
- `pytest.log`: E       AttributeError: module 'tongxing_production.compute.transports.codex_resources' has no attribute 'contracts'
- `pytest.log`: tests/test_codex_shared_pool_transport.py:62: AttributeError
- `pytest.log`: FAILED tests/test_codex_shared_pool_transport.py::test_busy_before_started_is_proven_no_dispatch
- `pytest.log`: 1 failed, 1111 passed, 27 subtests passed in 146.17s (0:02:26)
- `shards/s0.log`: ... 41 lines omitted; 0 error-like lines, 0 kept below ...
- `shards/s0.log`: run_unittest_ci.py: error: --candidate 'k0=/var/folders/s2/0bt6pz_51h1899zqs32x4vm80000gn/T/tmpuvgnu6le/run/diagnostic-previews/ko/native-1/candidate.json': use LOCALE=PATH once per requested locale (
- `shards/s0.log`: run_unittest_ci.py: error: --candidate 'es=/var/folders/s2/0bt6pz_51h1899zqs32x4vm80000gn/T/tmpuvgnu6le/run/diagnostic-previews/ko/native-1/candidate.json': use LOCALE=PATH once per requested locale (
- `shards/s0.log`: run_unittest_ci.py: error: --candidate '/var/folders/s2/0bt6pz_51h1899zqs32x4vm80000gn/T/tmpuvgnu6le/run/diagnostic-previews/ko/native-1/candidate.json': use LOCALE=PATH once per requested locale (ko)
- `shards/s0.log`: run_unittest_ci.py: error: --candidate 'ko=/var/folders/s2/0bt6pz_51h1899zqs32x4vm80000gn/T/tmpuvgnu6le/run/diagnostic-previews/ko/native-1/candidate.json': use LOCALE=PATH once per requested locale (
- `shards/s1.log`: run_unittest_ci.py: error: Reuse root has no paid ledger to reconcile
- `shards/s1.log`: run_unittest_ci.py: error: Duplicate reuse root; list each approved source only once
- `shards/s1.log`: "failedGroupIds": []
- `shards/s1.log`: "status": "error",
- `shards/s1.log`: "reason": "ValueError: /private/var/folders/s2/0bt6pz_51h1899zqs32x4vm80000gn/T/tmpll7j7az9/out/condensation-record-17af5c10d60c2500.json changed after it was written",
- `shards/s2.log`: ... 544 lines omitted; 13 error-like lines, 13 kept below ...
- `shards/s2.log`: [line 49]     "reason": "text QC failed; repair the failed groups in a new candidate revision",
- `shards/s2.log`: [line 58]     "reason": "failed groups are unchanged; repair them in a new candidate revision",
- `shards/s2.log`: [line 69]     "reason": "text QC failed; repair the failed groups in a new candidate revision",
- `shards/s2.log`: [line 78]     "reason": "failed groups are unchanged; repair them in a new candidate revision",
- `shards/s3.log`: .........................................................................................SERMON_LOGGING_WRITE_FAILED errorType=AccountingWriteError
- `shards/s3.log`: run_unittest_ci.py: error: Choose replay-only --reuse-from or --resume-qc-authorization, not both
- `shards/s3.log`: run_unittest_ci.py: error: --locales must name one or more of zh-Hans, ko, es
- `shards/s3.log`: run_unittest_ci.py: error: --locales must name one or more of zh-Hans, ko, es
- `shards/s3.log`: run_unittest_ci.py: error: --workers must be between 1 and 16
- `shards/s4.log`: run_unittest_ci.py: error: argument --risk-repeats: must be a positive integer
- `shards/s4.log`: ... 386 lines omitted; 9 error-like lines, 9 kept below ...
- `shards/s4.log`: [line 41] runtime_tts_mac.py: error: this bounded diagnostic writes only its declared output directory
- `shards/s4.log`: [line 144]     "status": "error",
- `shards/s4.log`: [line 145]     "reason": "ValueError: /private/var/folders/s2/0bt6pz_51h1899zqs32x4vm80000gn/T/tmpfv7mpz72/real/ko/text-waiver-47c690301186ad9c.json changed after it was written",
- `shards/s5.log`: .............................................................................................................s...........................................................................SERMON_LOGGING_
- `shards/s5.log`: ... 17 lines omitted; 1 error-like lines, 1 kept below ...
- `shards/s5.log`: [line 45] run_unittest_ci.py: error: the secondary ASR uses the OpenAI API: start under scripts/run_with_openai_environment.py --environment dev (prod for formal content)
- `shards/s5.log`: run_unittest_ci.py: error: real audio runs require --api-budget-authorization (planned per-locale QC authorization v4), including --text-backend codex for the secondary ASR budget
- `shards/s5.log`: ...................................................SERMON_LOGGING_WRITE_FAILED errorType=AccountingWriteError
- `shards/s6.log`: run_unittest_ci.py: error: output directory already exists: /var/folders/s2/0bt6pz_51h1899zqs32x4vm80000gn/T/tmpszkm1dbr/sheet
- `shards/s6.log`: run_unittest_ci.py build: error: the following arguments are required: --screening
- `shards/s6.log`: run_unittest_ci.py: error: recording a decision needs --choice, --decided-by
- `shards/s6.log`: ... 65 lines omitted; 0 error-like lines, 0 kept below ...
- `shards/s6.log`: {"component": "post-live-timeline-job", "event": "post_live_timeline_job_checked", "liveSource": {"host": "www.youtube.com", "path": "/watch", "urlHash": "3dd1687429a3473c"}, "loggedAt": "2026-10-19T2
- `shards/s7.log`: ....................................................................................FSERMON_LOGGING_WRITE_FAILED errorType=AccountingWriteError
- `shards/s7.log`: ... 263 lines omitted; 11 error-like lines, 11 kept below ...
- `shards/s7.log`: [line 41]         "error": null,
- `shards/s7.log`: [line 85]   "failedChecks": [],
- `shards/s7.log`: [line 91]     "error": null,
- `shards/s8.log`: run_unittest_ci.py: error: /var/folders/s2/0bt6pz_51h1899zqs32x4vm80000gn/T/tmpkxfbiv7v/digests/20261007-e2e already exists; pick another --name
- `shards/s8.log`: run_unittest_ci.py: error: --name must be YYYYMMDD-<label> using ASCII letters, digits, '.', '_' and '-'
- `shards/s8.log`: ... 161 lines omitted; 3 error-like lines, 3 kept below ...
- `shards/s8.log`: [line 110] .......................s...........................................................................................................s..................s................................SERMON
- `shards/s8.log`: [line 113]   "reason": "every shorten group failed its checks; those groups stay subtitle-only in the dub",
- `shards/s9.log`: ... 46 lines omitted; 2 error-like lines, 2 kept below ...
- `shards/s9.log`: [line 45] run_unittest_ci.py: error: --name must be YYYYMMDD-<label> using ASCII letters, digits, '.', '_' and '-'
- `shards/s9.log`: [line 49] progress: error: ledger already exists; refusing to overwrite
- `shards/s9.log`: ......................................SERMON_LOGGING_WRITE_FAILED errorType=AccountingWriteError
- `shards/s9.log`: "reason": "audio QC failed; re-render the failed units as the repair ladder says",
- `unittest-shards.log`: s4.log: Ran 603 tests in 1167.987s FAILED (errors=1, skipped=2)  exit 1
- `unittest-shards.log`: s7.log: Ran 615 tests in 1006.683s FAILED (failures=1, skipped=4)  exit 1
- `unittest-shards.log`: s9.log: Ran 616 tests in 1887.257s FAILED (failures=1, errors=1, skipped=5)  exit 1
- `unittest-shards.log`: ERROR: test_cloud_run_jobs (unittest.loader._FailedTest.test_cloud_run_jobs)
- `unittest-shards.log`: FAIL: test_129_group_actual_producer_can_assemble_and_resume_without_calls (test_layer2_large_fan_in.LargeLayer2FanInTests.test_129_group_actual_producer_can_assemble_and_resume_without_calls)

Not copied: 10 .json, 2 .txt
