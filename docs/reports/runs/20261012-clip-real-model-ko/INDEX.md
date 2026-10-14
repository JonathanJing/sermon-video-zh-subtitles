# Run digest 20261012-clip-real-model-ko

Generated 2026-10-12T06:07:56+00:00. Redacted copies only; source hashes are in manifest.json.

## textqc-out

Source: `/private/tmp/claude-501/-Users-jonathan-jing-SynologyDrive-GitHub-Active-sermon-video-zh-subtitles/59a9f28b-4e1e-4368-ac91-f9155989452b/scratchpad/dev-real/textqc-out`

- summary `summary.json` es: **text_waiver_issued**
- summary `summary.json` ko: **text_waiver_issued**
- summary `summary.json` zh-Hans: **text_waiver_issued**

Timings `timings.tsv`:

| stage | status | seconds |
|---|---|---|
| discover | pass | 0.0 |
| zh-Hans.text-qc.prefetch | pass | 70.8 |
| zh-Hans.text-qc | pass | 8.2 |
| zh-Hans.calibration.prefetch | pass | 503.0 |
| zh-Hans.calibration | pass | 57.9 |
| zh-Hans.text-waiver | pass | 0.0 |
| ko.text-qc.prefetch | pass | 74.7 |
| ko.text-qc | pass | 8.2 |
| ko.calibration.prefetch | pass | 509.3 |
| ko.calibration | pass | 62.1 |
| ko.text-waiver | pass | 0.0 |
| es.text-qc.prefetch | pass | 70.7 |
| es.text-qc | pass | 8.4 |
| es.calibration.prefetch | pass | 531.2 |
| es.calibration | pass | 62.6 |
| es.text-waiver | pass | 0.0 |

Not copied: 12 .json, 1 .lock

## ko-real

Source: `/private/tmp/claude-501/-Users-jonathan-jing-SynologyDrive-GitHub-Active-sermon-video-zh-subtitles/59a9f28b-4e1e-4368-ac91-f9155989452b/scratchpad/dev-real/ko-real`


Error-like log lines (first 5 per log):

- `layer2-jobs/2b25117f0760f6c01c9c0caee53e375e5f2c069cf153c7d44709e006cb7cff9b/worker.log`: Traceback (most recent call last):
- `layer2-jobs/2b25117f0760f6c01c9c0caee53e375e5f2c069cf153c7d44709e006cb7cff9b/worker.log`: raise self._exception
- `layer2-jobs/2b25117f0760f6c01c9c0caee53e375e5f2c069cf153c7d44709e006cb7cff9b/worker.log`: if not condition: raise ContractError(code)
- `layer2-jobs/2b25117f0760f6c01c9c0caee53e375e5f2c069cf153c7d44709e006cb7cff9b/worker.log`: scripts.sermon_review_contracts.ContractError: budget_exhausted
- `text/ko/accounting/operations.log`: ... 355 lines omitted; 0 error-like lines, 0 kept below ...
- `text/ko/accounting/operations.log`: 2026-10-12T05:58:29.555926+00:00 ERROR run=8a7a26ff16214f899dc7bc4d24f600b4 stage_finished workflowId=b024f23b4e0c47e58c2b938a15110a96 stage=layer2.reviewer.ko.group-0026 spanId=a4b1bb132f934e979ed30a
- `text/ko/accounting/operations.log`: 2026-10-12T05:58:29.557045+00:00 ERROR run=8a7a26ff16214f899dc7bc4d24f600b4 stage_finished workflowId=b024f23b4e0c47e58c2b938a15110a96 stage=layer2.group.ko.0026 spanId=209c384fa48f4360b4d28122d6f680e
- `text/ko/accounting/operations.log`: 2026-10-12T05:58:31.822364+00:00 ERROR run=8a7a26ff16214f899dc7bc4d24f600b4 stage_finished workflowId=b024f23b4e0c47e58c2b938a15110a96 stage=layer2_models spanId=4ec5fda995d24608ba9ba1a126c66adf attem
- `text/ko/accounting/operations.log`: 2026-10-12T05:58:31.826283+00:00 ERROR run=8a7a26ff16214f899dc7bc4d24f600b4 workflow_finished workflowId=b024f23b4e0c47e58c2b938a15110a96 stage=canonical_layer2_worker spanId=0aea151e443d413a970705a02

Not copied: 3 .csv, 269 .json, 1 .jsonl, 13 .lock, 1 .py

## ko-real-r2

Source: `/private/tmp/claude-501/-Users-jonathan-jing-SynologyDrive-GitHub-Active-sermon-video-zh-subtitles/59a9f28b-4e1e-4368-ac91-f9155989452b/scratchpad/dev-real/ko-real-r2`


Error-like log lines (first 5 per log):

- `layer2-jobs/8c85663952370f137c17583f7476c7a1e6839d50e9ae4b5d98337824055cc164/worker.log`: Traceback (most recent call last):
- `layer2-jobs/8c85663952370f137c17583f7476c7a1e6839d50e9ae4b5d98337824055cc164/worker.log`: if completed.returncode or response.get('error'): raise SessionError(response.get('error', 'ssh_failed_unknown'))
- `layer2-jobs/8c85663952370f137c17583f7476c7a1e6839d50e9ae4b5d98337824055cc164/worker.log`: scripts.spark_exclusive_session.SessionError: session_not_ready
- `text/ko/accounting/operations.log`: 2026-10-12T06:02:02.570978+00:00 ERROR run=2cad04f0f8b348deaacb15ad0dc03227 stage_finished workflowId=a5253f4eca9148be912d9b98ea02c5a7 stage=canonical_layer2_worker spanId=89720a4c33b9476c9df68284dc70
- `text/ko/accounting/operations.log`: 2026-10-12T06:02:02.574396+00:00 ERROR run=2cad04f0f8b348deaacb15ad0dc03227 workflow_finished workflowId=a5253f4eca9148be912d9b98ea02c5a7 status=failed
- `text/ko/accounting/operations.log`: 2026-10-12T06:02:02.574814+00:00 ERROR run=2cad04f0f8b348deaacb15ad0dc03227 run_finished workflowId=a5253f4eca9148be912d9b98ea02c5a7 status=failed
- `text-r3/ko/accounting/operations.log`: ... 374 lines omitted; 0 error-like lines, 0 kept below ...

Not copied: 6 .csv, 287 .json, 2 .jsonl, 17 .lock, 2 .py

## ko-textqc

Source: `/private/tmp/claude-501/-Users-jonathan-jing-SynologyDrive-GitHub-Active-sermon-video-zh-subtitles/59a9f28b-4e1e-4368-ac91-f9155989452b/scratchpad/dev-real/ko-textqc`

- outcome `state/codex-calls/06df0bbeb2c0c8159ff12f92a7b49fdb7be2f7bee37af599bfadcd3614287241/outcome.json`: **completed** exit ? (? → ?)
- outcome `state/codex-calls/106d99db5b55ed445c9af21a08ebc76c62b62bb8fd6bc8c084272d26ee05c9ee/outcome.json`: **completed** exit ? (? → ?)
- outcome `state/codex-calls/1a1ad64715bcb96fc0fd12e4816dc585bdf9a3726bdb5a26f13a499abb557785/outcome.json`: **completed** exit ? (? → ?)
- outcome `state/codex-calls/1ab145bad0f13bb23309b23d5145bfce525fc47500e7ef2bdb9ff1320c92adbb/outcome.json`: **completed** exit ? (? → ?)
- outcome `state/codex-calls/1b40c235a5d279be94f61d63e203b540a0b1d16f0e122c3896de93bf88a2ea3d/outcome.json`: **completed** exit ? (? → ?)
- outcome `state/codex-calls/23297ee120f89fba34dac66026a69093d497dd4c1d83c2448c63dca8bf4e54a6/outcome.json`: **completed** exit ? (? → ?)
- outcome `state/codex-calls/35e56a8c00c08d7abb47043ed4305c27183bc627135a56820533e29b7baaf071/outcome.json`: **completed** exit ? (? → ?)
- outcome `state/codex-calls/3e399066e89227db5dc5b7ed5226f7c0347e167a5ca1d90d1cc193a928e99945/outcome.json`: **completed** exit ? (? → ?)
- outcome `state/codex-calls/3f80dca5487e0858d1b5904aa0b72b6df5df363b2e5ded64d249ccb84047796d/outcome.json`: **completed** exit ? (? → ?)
- outcome `state/codex-calls/4047a7a640054cf2c79eb7086f0c1254c03bcb461ebe9ac6d9a40d472d9d6ecd/outcome.json`: **completed** exit ? (? → ?)
- outcome `state/codex-calls/42c6b7b1e3931464360fe777851a6d15bd42419cf14ef4ea5c5655928fa14a73/outcome.json`: **completed** exit ? (? → ?)
- outcome `state/codex-calls/47a8278d2891ad585833f6103768695ac9ffd10c2005d8f5e9eddd8df6e5e159/outcome.json`: **completed** exit ? (? → ?)
- outcome `state/codex-calls/5946692e2a248b143bd00ccc2a749da65840a2098ac21b009546125000927c73/outcome.json`: **completed** exit ? (? → ?)
- outcome `state/codex-calls/5c5a676c98a9f7f490d2cd6871ad6655f7c2643716996a3402a10bec5ff887c3/outcome.json`: **completed** exit ? (? → ?)
- outcome `state/codex-calls/60c40089fe2a986f631d06c78ce85155a5e4feb23ed148dd4149a61a6e9846e1/outcome.json`: **completed** exit ? (? → ?)
- outcome `state/codex-calls/63be9aac8885f9f2da76df1e0b72d96e73aa803afd7abe4aa2c58e42800f3050/outcome.json`: **completed** exit ? (? → ?)
- outcome `state/codex-calls/71a4f60c3c121783570c2b2a4f25ad96377252d2f48b8dae934fd467da484981/outcome.json`: **completed** exit ? (? → ?)
- outcome `state/codex-calls/781009848b8c6dc21fa9b91e8a13a0258dae34bc5da43e5c5dd38a5eb108d1b8/outcome.json`: **completed** exit ? (? → ?)
- outcome `state/codex-calls/82ee7e91b5511e3e07027ba127c09c095ea4385841de7a84deacd6c22a870b82/outcome.json`: **completed** exit ? (? → ?)
- outcome `state/codex-calls/89b1a591d4e435bbf08769b1b7d8e3f09032a7b0fb300d0e0228b0fa8cfecae2/outcome.json`: **completed** exit ? (? → ?)
- outcome `state/codex-calls/8b13fcc69f731030ef16ef36ee07e797d41a249928c35e35a85d76f2a0827a78/outcome.json`: **completed** exit ? (? → ?)
- outcome `state/codex-calls/8b545b9ee01064dedb3a348329c19f30def7a4e4ea73b8138561f6286e979f15/outcome.json`: **completed** exit ? (? → ?)
- outcome `state/codex-calls/8cd0bc5a8fce58cbf4630c1a4e18aafb69be89ffcca2fb0334eae3f42e1de1ee/outcome.json`: **completed** exit ? (? → ?)
- outcome `state/codex-calls/8d5fe153835ec2910ed3e04aedac00079e8e1175daa342d593e2de62146fc3ae/outcome.json`: **completed** exit ? (? → ?)
- outcome `state/codex-calls/91253c8ceddde702bc619a142742093ec65ccff113f1c143102c86988ac90cde/outcome.json`: **completed** exit ? (? → ?)
- outcome `state/codex-calls/93fe85244bb46ad6e2ebbb4c0157e7d5f55402d01dc569c25d5fd93ea3c975aa/outcome.json`: **completed** exit ? (? → ?)
- outcome `state/codex-calls/949cc298a422c085279d840d966bebb42d32e13ff405840145b6c42fc9cdbbe0/outcome.json`: **completed** exit ? (? → ?)
- outcome `state/codex-calls/99001c25a533976dda573e7e40c8ffb584d67527e89c87a77a7afc89484d0f22/outcome.json`: **completed** exit ? (? → ?)
- outcome `state/codex-calls/99d6a913f42cc8d76f50947b44148bd4baf2573d46dcbf5e907e565c002970da/outcome.json`: **completed** exit ? (? → ?)
- outcome `state/codex-calls/9c1898db9ab1ccb2477b61e20c351839e19dfc57a1eaa8089bb92364e69ef2c8/outcome.json`: **completed** exit ? (? → ?)
- outcome `state/codex-calls/a549e81054b96750829958918816faed3528759976ed3c950e1f23311ae37981/outcome.json`: **completed** exit ? (? → ?)
- outcome `state/codex-calls/b0ef9faa11fee822e8cd5473e6e021023c5c4bd8436ddc9771185a23f80233f4/outcome.json`: **completed** exit ? (? → ?)
- outcome `state/codex-calls/b295f9d11c6668a806d50fc0365b4fdafe00aed8f0078be0085c274137a5789c/outcome.json`: **completed** exit ? (? → ?)
- outcome `state/codex-calls/b57f89c13b6372307fccbf6defc3151481b2739e9dfd64c9c9a11104157987df/outcome.json`: **completed** exit ? (? → ?)
- outcome `state/codex-calls/b8319d49aae3d27ae4324ff0fa9cd230c170a47a226d35d897ed6e9bae5151cf/outcome.json`: **completed** exit ? (? → ?)
- outcome `state/codex-calls/ba7057150e5acd50e9a680c1f1808f0e538c7637831860d086b2a56a80676645/outcome.json`: **completed** exit ? (? → ?)
- outcome `state/codex-calls/be090587f6d066924ad6fbf753788140cad0cbc256a404410265dba766047e3a/outcome.json`: **completed** exit ? (? → ?)
- outcome `state/codex-calls/c5ab6fc93ead363d994a28d01758b05e680ea077757433de804a5ebc9eb7b629/outcome.json`: **completed** exit ? (? → ?)
- outcome `state/codex-calls/cc36b23e14fd7984526ebe6ce938162e334a133eb184492c749c3cfe93404d66/outcome.json`: **completed** exit ? (? → ?)
- outcome `state/codex-calls/ce2a18ae01fd43f8979e38a8d7d6cf809993ae2a3e2e572c5296b82102172f71/outcome.json`: **completed** exit ? (? → ?)
- outcome `state/codex-calls/d129588a58468f09b738725933d34336a49bdcd6eb8efa0012a248746e634eec/outcome.json`: **completed** exit ? (? → ?)
- outcome `state/codex-calls/d72b6f635b77d4b2569cef9260f6915d0162e1edf1a21e168a541ab1a0f27c07/outcome.json`: **completed** exit ? (? → ?)
- outcome `state/codex-calls/d881e45779ddfce6abcfbcb3edc735ce57ad1c4c89568e83f8171d7ea5cc4ddf/outcome.json`: **completed** exit ? (? → ?)
- outcome `state/codex-calls/db7f5e56a0deab5b3ee1e476c78884fa7b0c17d4ecc634cd6698596bc3b1cf83/outcome.json`: **completed** exit ? (? → ?)
- outcome `state/codex-calls/dfb35b04bfc902093c9b736b46b7403526ebc31d0941d01765c89b16c09d1949/outcome.json`: **completed** exit ? (? → ?)
- outcome `state/codex-calls/dfc7ba9d124cca00569dd3cdd63dad543dfde1260feed922a16f3c0376d7317c/outcome.json`: **completed** exit ? (? → ?)
- outcome `state/codex-calls/e15f9640b9fb77d9c7384d60d397469b914bce176cbf017c180a77f16d0625f4/outcome.json`: **completed** exit ? (? → ?)
- outcome `state/codex-calls/e2bbf820b0e859d1a97b3be39d935a220b807963c92d28aba59053969252fd51/outcome.json`: **completed** exit ? (? → ?)
- outcome `state/codex-calls/e6ee65a875c87fbcfae1023bb146cf8cd1d5eadf3027ad7e7a303b9c7202496f/outcome.json`: **completed** exit ? (? → ?)
- outcome `state/codex-calls/ee9f0b5242873a2bc2da2fd6f11542101eb727e15b0560ae8a671f4d13403f5e/outcome.json`: **completed** exit ? (? → ?)
- outcome `state/codex-calls/f3fe1ed07b2c44599a91cdb64a0f3d82cf9dc9e5acb39738c3ec843fa167bba9/outcome.json`: **completed** exit ? (? → ?)
- outcome `state/codex-calls/f401534683c240161694594c25d15f4cfea25f061d0322e1ff67d1c75aa8d79e/outcome.json`: **completed** exit ? (? → ?)
- summary `out/summary.json` ko: **requires_repair** (text QC failed; repair the failed groups in a new candidate revision)
- summary `preflight/summary.json` ko: **ready**

Timings `out/timings.tsv`:

| stage | status | seconds |
|---|---|---|
| discover | pass | 0.0 |
| ko.text-qc.prefetch | pass | 78.4 |
| ko.text-qc | pass | 8.5 |

Timings `preflight/timings.tsv`:

| stage | status | seconds |
|---|---|---|
| discover | pass | 0.0 |

Error-like log lines (first 5 per log):

- `run.log`: "reason": "text QC failed; repair the failed groups in a new candidate revision",

Not copied: 163 .json, 52 .jsonl, 55 .lock, 52 .txt
