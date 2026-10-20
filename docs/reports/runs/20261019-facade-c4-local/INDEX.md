# Run digest 20261019-facade-c4-local

Generated 2026-10-19T22:13:36+00:00. Redacted copies only; source hashes are in manifest.json.

## c4-local

Source: `~/SynologyDrive/GitHub/Active/sermon-video-zh-subtitles/.claude/worktrees/opus-haiku-translation-review-4a3b7c/artifacts/c4-local`

- outcome `outcome.json`: **passed** exit 0 (2026-10-19T21:54:39Z → 2026-10-19T22:12:43Z)
- summary `summary.json`: **passed**

Error-like log lines (first 5 per log):

- `pytest.log`: >       with patch.object(slots.Admission, 'reserve', side_effect=slots.contracts.ContractError('resource_broker_busy')):
- `pytest.log`: E       AttributeError: module 'tongxing_production.compute.transports.codex_resources' has no attribute 'contracts'
- `pytest.log`: tests/test_codex_shared_pool_transport.py:62: AttributeError
- `pytest.log`: FAILED tests/test_codex_shared_pool_transport.py::test_busy_before_started_is_proven_no_dispatch
- `pytest.log`: 1 failed, 1111 passed, 27 subtests passed in 133.98s (0:02:13)
- `shards/s0.log`: {"component": "api", "errorClass": "ConnectionError", "event": "sermon_production_supervisor_source_check_failed", "loggedAt": "2026-10-19T21:54:56.446154+00:00", "mode": "shadow", "severity": "ERROR"
- `shards/s0.log`: ... 54 lines omitted; 0 error-like lines, 0 kept below ...
- `shards/s0.log`: run_unittest_ci.py: error: --candidate 'k0=/var/folders/s2/0bt6pz_51h1899zqs32x4vm80000gn/T/tmpqxtd566q/run/diagnostic-previews/ko/native-1/candidate.json': use LOCALE=PATH once per requested locale (
- `shards/s0.log`: run_unittest_ci.py: error: --candidate 'es=/var/folders/s2/0bt6pz_51h1899zqs32x4vm80000gn/T/tmpqxtd566q/run/diagnostic-previews/ko/native-1/candidate.json': use LOCALE=PATH once per requested locale (
- `shards/s0.log`: run_unittest_ci.py: error: --candidate '/var/folders/s2/0bt6pz_51h1899zqs32x4vm80000gn/T/tmpqxtd566q/run/diagnostic-previews/ko/native-1/candidate.json': use LOCALE=PATH once per requested locale (ko)
- `shards/s1.log`: runtime_tts_mac.py: error: this bounded diagnostic writes only its declared output directory
- `shards/s1.log`: "failedChecks": [],
- `shards/s1.log`: run_unittest_ci.py: error: Reuse root has no paid ledger to reconcile
- `shards/s1.log`: run_unittest_ci.py: error: Duplicate reuse root; list each approved source only once
- `shards/s1.log`: "failedGroupIds": []
- `shards/s2.log`: "error": null,
- `shards/s2.log`: ... 293 lines omitted; 13 error-like lines, 13 kept below ...
- `shards/s2.log`: [line 83]   "failedChecks": [],
- `shards/s2.log`: [line 89]     "error": null,
- `shards/s2.log`: [line 135]     "reason": "text QC failed; repair the failed groups in a new candidate revision",
- `shards/s3.log`: .........................................................................................SERMON_LOGGING_WRITE_FAILED errorType=AccountingWriteError
- `shards/s3.log`: run_unittest_ci.py: error: Choose replay-only --reuse-from or --resume-qc-authorization, not both
- `shards/s3.log`: ... 110 lines omitted; 4 error-like lines, 4 kept below ...
- `shards/s3.log`: [line 83] run_unittest_ci.py: error: --locales must name one or more of zh-Hans, ko, es
- `shards/s3.log`: [line 93] run_unittest_ci.py: error: --locales must name one or more of zh-Hans, ko, es
- `shards/s4.log`: run_unittest_ci.py: error: argument --risk-repeats: must be a positive integer
- `shards/s4.log`: run_unittest_ci.py: error: output directory already exists: /var/folders/s2/0bt6pz_51h1899zqs32x4vm80000gn/T/tmpi_eu5k5f/sheet
- `shards/s4.log`: run_unittest_ci.py build: error: the following arguments are required: --screening
- `shards/s4.log`: ... 10 lines omitted; 0 error-like lines, 0 kept below ...
- `shards/s4.log`: "status": "error",
- `shards/s5.log`: ... 13 lines omitted; 2 error-like lines, 2 kept below ...
- `shards/s5.log`: [line 52] progress: error: ledger already exists; refusing to overwrite
- `shards/s5.log`: [line 53] ...........................................SERMON_LOGGING_WRITE_FAILED errorType=AccountingWriteError
- `shards/s5.log`: .....................................SERMON_LOGGING_WRITE_FAILED errorType=AccountingWriteError
- `shards/s5.log`: run_unittest_ci.py: error: the secondary ASR uses the OpenAI API: start under scripts/run_with_openai_environment.py --environment dev (prod for formal content)
- `shards/s6.log`: ... 298 lines omitted; 6 error-like lines, 6 kept below ...
- `shards/s6.log`: [line 47] run_unittest_ci.py: error: recording a decision needs --choice, --decided-by
- `shards/s6.log`: [line 127] .............s........................s.....SERMON_LOGGING_WRITE_FAILED errorType=AccountingWriteError
- `shards/s6.log`: [line 128] ..................................SERMON_LOGGING_WRITE_FAILED errorType=AccountingWriteError
- `shards/s6.log`: [line 129] .......................SERMON_LOGGING_WRITE_FAILED errorType=AccountingWriteError
- `shards/s7.log`: ... 150 lines omitted; 7 error-like lines, 7 kept below ...
- `shards/s7.log`: [line 53]     "reason": "text QC failed; repair the failed groups in a new candidate revision",
- `shards/s7.log`: [line 62]     "reason": "failed groups are unchanged; repair them in a new candidate revision",
- `shards/s7.log`: [line 71]     "reason": "failed groups are unchanged; repair them in a new candidate revision",
- `shards/s7.log`: [line 80]     "reason": "text QC failed; repair the failed groups in a new candidate revision",
- `shards/s8.log`: run_unittest_ci.py: error: /var/folders/s2/0bt6pz_51h1899zqs32x4vm80000gn/T/tmpdg9_qptr/digests/20261007-e2e already exists; pick another --name
- `shards/s8.log`: run_unittest_ci.py: error: --name must be YYYYMMDD-<label> using ASCII letters, digits, '.', '_' and '-'
- `shards/s8.log`: ..............................................SERMON_LOGGING_WRITE_FAILED errorType=AccountingWriteError
- `shards/s8.log`: ... 163 lines omitted; 5 error-like lines, 5 kept below ...
- `shards/s8.log`: [line 110] .......................s...........................................................................................................s................s...............................SERMON_LO
- `shards/s9.log`: run_unittest_ci.py: error: --name must be YYYYMMDD-<label> using ASCII letters, digits, '.', '_' and '-'
- `shards/s9.log`: ... 348 lines omitted; 4 error-like lines, 4 kept below ...
- `shards/s9.log`: [line 50]     "reason": "audio QC failed; re-render the failed units as the repair ladder says",
- `shards/s9.log`: [line 59]     "reason": "failed units still have the same audio; re-render them (new seed or revised text) first",
- `shards/s9.log`: [line 98] run_unittest_ci.py: error: real runs need --state-dir: the run's persistent state dir holding its repair ledger
- `targeted-before-fix.log`: ...............F......................................ssss.........................................................................................................................................SERMO
- `targeted-before-fix.log`: .............................................................................................SERMON_LOGGING_WRITE_FAILED errorType=AccountingWriteError
- `targeted-before-fix.log`: python -m unittest: error: QC stages require --qc-inputs binding the frozen source and locale policies
- `targeted-before-fix.log`: python -m unittest: error: Output must be new or empty
- `targeted-before-fix.log`: ... 157 lines omitted; 33 error-like lines, 33 kept below ...

Not copied: 10 .json, 3 .txt
