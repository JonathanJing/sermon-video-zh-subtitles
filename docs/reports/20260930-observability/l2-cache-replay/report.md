# Weekly Pipeline Report

Status: projected

Projected means a computable recorded DAG, not complete telemetry. Content/device/venue/release acceptance: not evaluated.

## Run d0f2de14caf6

End-to-end wall seconds: 2.8146939277648926
Active critical-path seconds: 2.342017

| Executor | Leaf elapsed seconds (parallel subtotal) |
|---|---:|
| decision_agent | 0 (not_observed; completed spans only) |
| deterministic_program | 2.535574 (measured_completed_spans; completed spans only) |
| engineering_codex | 0 (not_observed; completed spans only) |
| external_service | 0 (not_observed; completed spans only) |
| human | 0 (not_observed; completed spans only) |
| production_model | 0 (not_observed; completed spans only) |

Coverage: {"crossProcessCriticalPath": "not_established", "locales": "recorded", "logCompleteness": "not_established", "orchestrationOverhead": "missing_instrumentation", "pageReady": "not_observed", "queueTiming": "missing_instrumentation", "sourceDuration": "recorded", "statusMeaning": "projected_means_computable_recorded_DAG_not_complete_telemetry"}

| Stage / attempt | Executor / models | Cache | Start → finish | Dependencies | Queue |
|---|---|---|---|---|---|
| diagnostic.real_source_decode / 3048bc9574f5 | deterministic_program /  | False | 2026-09-30T14:38:45.425388+00:00 → 2026-09-30T14:38:47.711118+00:00 |  | missing_instrumentation |
| diagnostic.candidate.es / 79780a2171f6 | deterministic_program /  | False | 2026-09-30T14:38:48.146940+00:00 → 2026-09-30T14:38:48.185371+00:00 | cfbb80bbb682 | missing_instrumentation |
| diagnostic.candidate.ko / eb3059a58046 | deterministic_program /  | False | 2026-09-30T14:38:47.971691+00:00 → 2026-09-30T14:38:48.003685+00:00 | 2856591db06a | missing_instrumentation |
| diagnostic.candidate.zh-Hans / 1b15dad4107a | deterministic_program /  | False | 2026-09-30T14:38:47.826008+00:00 → 2026-09-30T14:38:47.856513+00:00 | e4fc3b604426 | missing_instrumentation |
| layer2.prepare.es.group-0001 / fef2dcc69db1 | deterministic_program / gpt-6-astra,gpt-6-sol | True | 2026-09-30T14:38:48.082355+00:00 → 2026-09-30T14:38:48.088227+00:00 | 07e32512278b | missing_instrumentation |
| layer2.source_admission.es / bfe82c0b96b1 | deterministic_program /  | False | 2026-09-30T14:38:48.071322+00:00 → 2026-09-30T14:38:48.077091+00:00 | 12d1642ebe8a | missing_instrumentation |
| layer2.prepare.es.group-0002 / bd8af7b1eb79 | deterministic_program / gpt-6-astra,gpt-6-sol | True | 2026-09-30T14:38:48.089767+00:00 → 2026-09-30T14:38:48.095459+00:00 | 07e32512278b | missing_instrumentation |
| layer2.prepare.ko.group-0001 / 6134bddb0fd2 | deterministic_program / gpt-6-astra,gpt-6-sol | True | 2026-09-30T14:38:47.927340+00:00 → 2026-09-30T14:38:47.932921+00:00 | c7f3ec019274 | missing_instrumentation |
| layer2.source_admission.zh-Hans / 8e8a90de5c11 | deterministic_program /  | False | 2026-09-30T14:38:47.765857+00:00 → 2026-09-30T14:38:47.771357+00:00 | 12d1642ebe8a | missing_instrumentation |
| layer2.prepare.es.group-0003 / a5186a0e5b70 | deterministic_program / gpt-6-astra,gpt-6-sol | True | 2026-09-30T14:38:48.096292+00:00 → 2026-09-30T14:38:48.101721+00:00 | 07e32512278b | missing_instrumentation |
| layer2.prepare.es.group-0009 / 607c252992d5 | deterministic_program / gpt-6-astra,gpt-6-sol | True | 2026-09-30T14:38:48.127909+00:00 → 2026-09-30T14:38:48.132756+00:00 | 07e32512278b | missing_instrumentation |
| layer2.prepare.zh-Hans.group-0004 / 5d4022a91080 | deterministic_program / gpt-6-astra,gpt-6-sol | True | 2026-09-30T14:38:47.788312+00:00 → 2026-09-30T14:38:47.793220+00:00 | 57337f6b683f | missing_instrumentation |
| layer2.prepare.es.group-0004 / cb47c13c60df | deterministic_program / gpt-6-astra,gpt-6-sol | True | 2026-09-30T14:38:48.102331+00:00 → 2026-09-30T14:38:48.107072+00:00 | 07e32512278b | missing_instrumentation |
| layer2.run_admission.es / 849b66b9879b | deterministic_program /  | False | 2026-09-30T14:38:48.077311+00:00 → 2026-09-30T14:38:48.081908+00:00 | 5b34f6047865 | missing_instrumentation |
| layer2.source_admission.ko / 71ae91374a46 | deterministic_program /  | False | 2026-09-30T14:38:47.919635+00:00 → 2026-09-30T14:38:47.924199+00:00 | 12d1642ebe8a | missing_instrumentation |
| layer2.prepare.es.group-0005 / 27f81469c5f9 | deterministic_program / gpt-6-astra,gpt-6-sol | True | 2026-09-30T14:38:48.107849+00:00 → 2026-09-30T14:38:48.112224+00:00 | 07e32512278b | missing_instrumentation |
| layer2.prepare.es.group-0008 / 691234e9171f | deterministic_program / gpt-6-astra,gpt-6-sol | True | 2026-09-30T14:38:48.122894+00:00 → 2026-09-30T14:38:48.126989+00:00 | 07e32512278b | missing_instrumentation |
| layer2.prepare.es.group-0007 / cd78b4061fd7 | deterministic_program / gpt-6-astra,gpt-6-sol | True | 2026-09-30T14:38:48.117829+00:00 → 2026-09-30T14:38:48.121821+00:00 | 07e32512278b | missing_instrumentation |
| layer2.prepare.zh-Hans.group-0001 / 1d283a8edd70 | deterministic_program / gpt-6-astra,gpt-6-sol | True | 2026-09-30T14:38:47.774849+00:00 → 2026-09-30T14:38:47.778783+00:00 | 57337f6b683f | missing_instrumentation |
| layer2.prepare.zh-Hans.group-0003 / 81f1dd8b272a | deterministic_program / gpt-6-astra,gpt-6-sol | True | 2026-09-30T14:38:47.783807+00:00 → 2026-09-30T14:38:47.787697+00:00 | 57337f6b683f | missing_instrumentation |
| layer2.prepare.zh-Hans.group-0011 / 4ac2f5bb9e41 | deterministic_program / gpt-6-astra,gpt-6-sol | True | 2026-09-30T14:38:47.817646+00:00 → 2026-09-30T14:38:47.821468+00:00 | 57337f6b683f | missing_instrumentation |
| layer2.prepare.zh-Hans.group-0002 / 75d6ddbdbb2d | deterministic_program / gpt-6-astra,gpt-6-sol | True | 2026-09-30T14:38:47.779546+00:00 → 2026-09-30T14:38:47.783223+00:00 | 57337f6b683f | missing_instrumentation |
| layer2.prepare.ko.group-0005 / 848fb3989dcd | deterministic_program / gpt-6-astra,gpt-6-sol | True | 2026-09-30T14:38:47.945393+00:00 → 2026-09-30T14:38:47.949033+00:00 | c7f3ec019274 | missing_instrumentation |
| layer2.prepare.zh-Hans.group-0009 / 81a0cb346e65 | deterministic_program / gpt-6-astra,gpt-6-sol | True | 2026-09-30T14:38:47.809868+00:00 → 2026-09-30T14:38:47.813509+00:00 | 57337f6b683f | missing_instrumentation |
| layer2.prepare.zh-Hans.group-0007 / d03c701b5280 | deterministic_program / gpt-6-astra,gpt-6-sol | True | 2026-09-30T14:38:47.801729+00:00 → 2026-09-30T14:38:47.805343+00:00 | 57337f6b683f | missing_instrumentation |
| layer2.prepare.es.group-0011 / 7f1232fad0b2 | deterministic_program / gpt-6-astra,gpt-6-sol | True | 2026-09-30T14:38:48.137916+00:00 → 2026-09-30T14:38:48.141424+00:00 | 07e32512278b | missing_instrumentation |
| layer2.prepare.ko.group-0002 / 81cb49df4ca2 | deterministic_program / gpt-6-astra,gpt-6-sol | True | 2026-09-30T14:38:47.934946+00:00 → 2026-09-30T14:38:47.938435+00:00 | c7f3ec019274 | missing_instrumentation |
| layer2.prepare.zh-Hans.group-0005 / fdce3aef024f | deterministic_program / gpt-6-astra,gpt-6-sol | True | 2026-09-30T14:38:47.794668+00:00 → 2026-09-30T14:38:47.797952+00:00 | 57337f6b683f | missing_instrumentation |
| layer2.prepare.es.group-0006 / 6844f719c3e0 | deterministic_program / gpt-6-astra,gpt-6-sol | True | 2026-09-30T14:38:48.113049+00:00 → 2026-09-30T14:38:48.116614+00:00 | 07e32512278b | missing_instrumentation |
| layer2.prepare.es.group-0010 / 920ac7d4da0c | deterministic_program / gpt-6-astra,gpt-6-sol | True | 2026-09-30T14:38:48.133708+00:00 → 2026-09-30T14:38:48.136776+00:00 | 07e32512278b | missing_instrumentation |
| layer2.prepare.ko.group-0010 / b207d47f3650 | deterministic_program / gpt-6-astra,gpt-6-sol | True | 2026-09-30T14:38:47.961064+00:00 → 2026-09-30T14:38:47.964020+00:00 | c7f3ec019274 | missing_instrumentation |
| layer2.prepare.zh-Hans.group-0008 / 56ee9497ba96 | deterministic_program / gpt-6-astra,gpt-6-sol | True | 2026-09-30T14:38:47.806278+00:00 → 2026-09-30T14:38:47.809132+00:00 | 57337f6b683f | missing_instrumentation |
| layer2.prepare.zh-Hans.group-0010 / 758024b77a26 | deterministic_program / gpt-6-astra,gpt-6-sol | True | 2026-09-30T14:38:47.814116+00:00 → 2026-09-30T14:38:47.816914+00:00 | 57337f6b683f | missing_instrumentation |
| layer2.run_admission.zh-Hans / c463971a49a6 | deterministic_program /  | False | 2026-09-30T14:38:47.771621+00:00 → 2026-09-30T14:38:47.774345+00:00 | b56c101e35ad | missing_instrumentation |
| layer2.prepare.ko.group-0006 / 62eaf33c7830 | deterministic_program / gpt-6-astra,gpt-6-sol | True | 2026-09-30T14:38:47.949541+00:00 → 2026-09-30T14:38:47.952265+00:00 | c7f3ec019274 | missing_instrumentation |
| layer2.prepare.zh-Hans.group-0006 / 1c8abc3566e7 | deterministic_program / gpt-6-astra,gpt-6-sol | True | 2026-09-30T14:38:47.798655+00:00 → 2026-09-30T14:38:47.801297+00:00 | 57337f6b683f | missing_instrumentation |
| layer2.prepare.ko.group-0004 / 1ff4146b0b5b | deterministic_program / gpt-6-astra,gpt-6-sol | True | 2026-09-30T14:38:47.942085+00:00 → 2026-09-30T14:38:47.944712+00:00 | c7f3ec019274 | missing_instrumentation |
| layer2.prepare.ko.group-0003 / f1063306afea | deterministic_program / gpt-6-astra,gpt-6-sol | True | 2026-09-30T14:38:47.939058+00:00 → 2026-09-30T14:38:47.941615+00:00 | c7f3ec019274 | missing_instrumentation |
| layer2.prepare.ko.group-0007 / 4ef637f6f278 | deterministic_program / gpt-6-astra,gpt-6-sol | True | 2026-09-30T14:38:47.952821+00:00 → 2026-09-30T14:38:47.955339+00:00 | c7f3ec019274 | missing_instrumentation |
| layer2.prepare.ko.group-0011 / 3e49fb385ee1 | deterministic_program / gpt-6-astra,gpt-6-sol | True | 2026-09-30T14:38:47.964495+00:00 → 2026-09-30T14:38:47.966862+00:00 | c7f3ec019274 | missing_instrumentation |
| layer2.run_admission.ko / cd1b53ccd057 | deterministic_program /  | False | 2026-09-30T14:38:47.924422+00:00 → 2026-09-30T14:38:47.926785+00:00 | 1912015378a8 | missing_instrumentation |
| layer2.prepare.ko.group-0008 / 491f695aab6e | deterministic_program / gpt-6-astra,gpt-6-sol | True | 2026-09-30T14:38:47.955845+00:00 → 2026-09-30T14:38:47.958187+00:00 | c7f3ec019274 | missing_instrumentation |
| layer2.evidence_assembly.es / f7aa4aeb8ae4 | deterministic_program /  | False | 2026-09-30T14:38:48.141767+00:00 → 2026-09-30T14:38:48.143915+00:00 | ad5e0712cc6c,b3119f88ed05,bfa0336122af,1a646e481f6e,f2acfb839f7c,6c34a471fee7,ac7fb14f5dcb,d9da317d282b,182b8b7a6475,16f093c60011,d0749cd497a4 | missing_instrumentation |
| layer2.prepare.ko.group-0009 / 49582c0a5cf9 | deterministic_program / gpt-6-astra,gpt-6-sol | True | 2026-09-30T14:38:47.958653+00:00 → 2026-09-30T14:38:47.960615+00:00 | c7f3ec019274 | missing_instrumentation |
| layer2.evidence_assembly.zh-Hans / cb445af79ddb | deterministic_program /  | False | 2026-09-30T14:38:47.821883+00:00 → 2026-09-30T14:38:47.823856+00:00 | 3999753b3ece,52cecef36e25,f5efde8dc9c5,75f40e03a400,7716281fcbcd,b09647f46419,cd495aa93884,090df9de6480,98ef8d1c28c1,fd7b8b84fd78,3c5885450597 | missing_instrumentation |
| layer2.evidence_assembly.ko / cd4354c5a34c | deterministic_program /  | False | 2026-09-30T14:38:47.967110+00:00 → 2026-09-30T14:38:47.968731+00:00 | 0cc3e81431fb,a2036df869f0,f2763ddb9e07,78189c17a565,707360401c6f,06cc36aa4fd0,3fc2ae2c9b7e,8950f8918b77,e2a8aed3a028,d1c067c2bf69,e638657e5c41 | missing_instrumentation |

Direct receipt usage (SDK aggregates remain separate):

| Executor | Calls | Input | Cached | Non-cached | Output | Reasoning |
|---|---:|---:|---:|---:|---:|---:|
| decision_agent | 0 | None | None | None | None | None |
| deterministic_program | 0 | None | None | None | None | None |
| engineering_codex | 0 | None | None | None | None | None |
| external_service | 0 | None | None | None | None | None |
| human | 0 | None | None | None | None | None |
| production_model | 0 | None | None | None | None | None |
| unknown | 0 | None | None | None | None | None |

Historical cache receipts (excluded from current API usage/spend):

| Role | Requested / receipt model | Span | Cache hash | Original response hash | Usage provenance | Historical input / output |
|---|---|---|---|---|---|---|
| translator | gpt-6-astra / gpt-6-astra | 3999753b3ece | 143c0fb7cd08 | 634a0af7c9d8 | historical_bound_provider_receipt | 577 / 439 |
| reviewer | gpt-6-sol / gpt-6-sol | 3999753b3ece | 750e97946600 | 965b3cb18bbe | historical_bound_provider_receipt | 885 / 465 |
| translator | gpt-6-astra / gpt-6-astra | 52cecef36e25 | 5a78e2cfee94 | 93cbe6d158ed | historical_bound_provider_receipt | 592 / 324 |
| reviewer | gpt-6-sol / gpt-6-sol | 52cecef36e25 | 60e1d36ad9ae | 8ad9782f8945 | historical_bound_provider_receipt | 857 / 639 |
| translator | gpt-6-astra / gpt-6-astra | f5efde8dc9c5 | ef4050ff0f3b | c5aba0e7f6bb | historical_bound_provider_receipt | 598 / 269 |
| reviewer | gpt-6-sol / gpt-6-sol | f5efde8dc9c5 | 0ace4d0727ff | 0f914f77e63b | historical_bound_provider_receipt | 922 / 566 |
| translator | gpt-6-astra / gpt-6-astra | 75f40e03a400 | dc707b845639 | d86bcbf18277 | historical_bound_provider_receipt | 584 / 267 |
| reviewer | gpt-6-sol / gpt-6-sol | 75f40e03a400 | 890fbb175245 | 2836ca29d9ea | historical_bound_provider_receipt | 908 / 853 |
| translator | gpt-6-astra / gpt-6-astra | 7716281fcbcd | 27510980c79b | f2a175477e8a | historical_bound_provider_receipt | 595 / 375 |
| reviewer | gpt-6-sol / gpt-6-sol | 7716281fcbcd | 8f03845fbd98 | 4fe0a8c6e8a6 | historical_bound_provider_receipt | 917 / 490 |
| translator | gpt-6-astra / gpt-6-astra | b09647f46419 | b63d49c0cc71 | 9269e8bf8916 | historical_bound_provider_receipt | 575 / 373 |
| reviewer | gpt-6-sol / gpt-6-sol | b09647f46419 | 7c92ae2fb7ff | a293e43c3d41 | historical_bound_provider_receipt | 859 / 427 |
| translator | gpt-6-astra / gpt-6-astra | cd495aa93884 | 462a588d40f5 | d0d3579b325f | historical_bound_provider_receipt | 580 / 398 |
| reviewer | gpt-6-sol / gpt-6-sol | cd495aa93884 | 563d9be1ded3 | ccb47f0f661d | historical_bound_provider_receipt | 866 / 447 |
| translator | gpt-6-astra / gpt-6-astra | 090df9de6480 | 9c0dda2df67a | 8747154b3fbc | historical_bound_provider_receipt | 592 / 376 |
| reviewer | gpt-6-sol / gpt-6-sol | 090df9de6480 | 0402e89c9b71 | ff341c3cb845 | historical_bound_provider_receipt | 878 / 543 |
| translator | gpt-6-astra / gpt-6-astra | 98ef8d1c28c1 | 716bddd0a426 | 208340cfc049 | historical_bound_provider_receipt | 631 / 511 |
| reviewer | gpt-6-sol / gpt-6-sol | 98ef8d1c28c1 | cd6608e18b19 | d0f4b66c35b1 | historical_bound_provider_receipt | 1009 / 610 |
| translator | gpt-6-astra / gpt-6-astra | fd7b8b84fd78 | bccad4fc7022 | 93db9f95d83b | historical_bound_provider_receipt | 629 / 425 |
| reviewer | gpt-6-sol / gpt-6-sol | fd7b8b84fd78 | bc9790b8997b | 11078f7d2f8e | historical_bound_provider_receipt | 980 / 964 |
| translator | gpt-6-astra / gpt-6-astra | 3c5885450597 | 0d2bd5fea547 | f3c10c8ddcec | historical_bound_provider_receipt | 580 / 426 |
| reviewer | gpt-6-sol / gpt-6-sol | 3c5885450597 | e11112fc327d | 5edca33aa881 | historical_bound_provider_receipt | 890 / 818 |
| translator | gpt-6-astra / gpt-6-astra | 0cc3e81431fb | 54a66891ac1e | 6f894cafec13 | historical_bound_provider_receipt | 574 / 269 |
| reviewer | gpt-6-sol / gpt-6-sol | 0cc3e81431fb | dd0e86d8fed4 | 810c92179998 | historical_bound_provider_receipt | 901 / 703 |
| translator | gpt-6-astra / gpt-6-astra | a2036df869f0 | cbe3fa9a74e1 | da412150c8c5 | historical_bound_provider_receipt | 589 / 314 |
| reviewer | gpt-6-sol / gpt-6-sol | a2036df869f0 | a1b5f23ae267 | d21dbfce9c90 | historical_bound_provider_receipt | 875 / 695 |
| translator | gpt-6-astra / gpt-6-astra | f2763ddb9e07 | 9dce43c26452 | 05aaecd9d379 | historical_bound_provider_receipt | 595 / 303 |
| reviewer | gpt-6-sol / gpt-6-sol | f2763ddb9e07 | 7aa23f6c75b9 | f51c08654454 | historical_bound_provider_receipt | 955 / 663 |
| translator | gpt-6-astra / gpt-6-astra | 78189c17a565 | dffcf375e922 | e64215e7fc36 | historical_bound_provider_receipt | 581 / 275 |
| reviewer | gpt-6-sol / gpt-6-sol | 78189c17a565 | 94deca5b37fb | 174f5040386d | historical_bound_provider_receipt | 914 / 784 |
| translator | gpt-6-astra / gpt-6-astra | 707360401c6f | 4690eed84b4a | b52f840fed31 | historical_bound_provider_receipt | 592 / 421 |
| reviewer | gpt-6-sol / gpt-6-sol | 707360401c6f | b11ff2d513d5 | 57d00259a4de | historical_bound_provider_receipt | 959 / 691 |
| translator | gpt-6-astra / gpt-6-astra | 06cc36aa4fd0 | b6380dba94d8 | a3041c4a1529 | historical_bound_provider_receipt | 572 / 474 |
| reviewer | gpt-6-sol / gpt-6-sol | 06cc36aa4fd0 | 8449dd93ac48 | 57d9385705f4 | historical_bound_provider_receipt | 891 / 866 |
| translator | gpt-6-astra / gpt-6-astra | 3fc2ae2c9b7e | ed9dbdbece7d | e1376ef9a063 | historical_bound_provider_receipt | 577 / 434 |
| reviewer | gpt-6-sol / gpt-6-sol | 3fc2ae2c9b7e | 5e698f5832ff | 860ca2f8462f | historical_bound_provider_receipt | 890 / 658 |
| translator | gpt-6-astra / gpt-6-astra | 8950f8918b77 | 0fee79583173 | 042fef40e1af | historical_bound_provider_receipt | 589 / 267 |
| reviewer | gpt-6-sol / gpt-6-sol | 8950f8918b77 | ab6df92e5d5e | c5138b68a9a6 | historical_bound_provider_receipt | 913 / 637 |
| translator | gpt-6-astra / gpt-6-astra | e2a8aed3a028 | ad7e1fa8703c | df9de1201740 | historical_bound_provider_receipt | 628 / 607 |
| reviewer | gpt-6-sol / gpt-6-sol | e2a8aed3a028 | 55d6e9ff177b | 440a20be4e03 | historical_bound_provider_receipt | 1055 / 1164 |
| translator | gpt-6-astra / gpt-6-astra | d1c067c2bf69 | 78e0ee94633b | 363603c78bd6 | historical_bound_provider_receipt | 626 / 495 |
| reviewer | gpt-6-sol / gpt-6-sol | d1c067c2bf69 | 1d4c11a4125b | d6d3dad2b6ef | historical_bound_provider_receipt | 1008 / 885 |
| translator | gpt-6-astra / gpt-6-astra | e638657e5c41 | be297a89bff4 | 34328e5e55a3 | historical_bound_provider_receipt | 577 / 386 |
| reviewer | gpt-6-sol / gpt-6-sol | e638657e5c41 | 3d1a412c04cc | 4b39e0a9ca62 | historical_bound_provider_receipt | 906 / 955 |
| translator | gpt-6-astra / gpt-6-astra | ad5e0712cc6c | ad6fb0e5406e | e02146a3dc9b | historical_bound_provider_receipt | 575 / 488 |
| reviewer | gpt-6-sol / gpt-6-sol | ad5e0712cc6c | c7c5e1c15956 | c547d03ed5c5 | historical_bound_provider_receipt | 884 / 784 |
| translator | gpt-6-astra / gpt-6-astra | b3119f88ed05 | 3027955a4273 | 00484a986890 | historical_bound_provider_receipt | 590 / 340 |
| reviewer | gpt-6-sol / gpt-6-sol | b3119f88ed05 | 59d841d7b88a | 70c5a3ce95d7 | historical_bound_provider_receipt | 852 / 658 |
| translator | gpt-6-astra / gpt-6-astra | bfa0336122af | 89a198286e3e | 7bbe66466b69 | historical_bound_provider_receipt | 596 / 250 |
| reviewer | gpt-6-sol / gpt-6-sol | bfa0336122af | ca2100448753 | e734a9464c4b | historical_bound_provider_receipt | 904 / 639 |
| translator | gpt-6-astra / gpt-6-astra | 1a646e481f6e | 5c74d518838e | 7df75bf93f96 | historical_bound_provider_receipt | 582 / 255 |
| reviewer | gpt-6-sol / gpt-6-sol | 1a646e481f6e | 2cec8bdac9c8 | d08d14769720 | historical_bound_provider_receipt | 895 / 611 |
| translator | gpt-6-astra / gpt-6-astra | f2acfb839f7c | a00a995eca43 | bfc73c73aa72 | historical_bound_provider_receipt | 593 / 447 |
| reviewer | gpt-6-sol / gpt-6-sol | f2acfb839f7c | eaa9ce42b314 | bedd699592fa | historical_bound_provider_receipt | 917 / 520 |
| translator | gpt-6-astra / gpt-6-astra | 6c34a471fee7 | bcae76fa20f7 | bf50bfe1ee6d | historical_bound_provider_receipt | 573 / 332 |
| reviewer | gpt-6-sol / gpt-6-sol | 6c34a471fee7 | 6a9aebe8a7fd | 7ef7e1525841 | historical_bound_provider_receipt | 850 / 714 |
| translator | gpt-6-astra / gpt-6-astra | ac7fb14f5dcb | 1b80f042dad7 | c5d7083e4ccf | historical_bound_provider_receipt | 578 / 377 |
| reviewer | gpt-6-sol / gpt-6-sol | ac7fb14f5dcb | 75b31f436053 | db8ff45d7b88 | historical_bound_provider_receipt | 852 / 589 |
| translator | gpt-6-astra / gpt-6-astra | d9da317d282b | 5b6d89ac8d02 | 600cd8d3cc09 | historical_bound_provider_receipt | 590 / 331 |
| reviewer | gpt-6-sol / gpt-6-sol | d9da317d282b | fb6fbb1dabf6 | 2befa194f5d5 | historical_bound_provider_receipt | 871 / 448 |
| translator | gpt-6-astra / gpt-6-astra | 182b8b7a6475 | f3be4a0580ed | 01fc7ccfc299 | historical_bound_provider_receipt | 629 / 294 |
| reviewer | gpt-6-sol / gpt-6-sol | 182b8b7a6475 | 42939d7f8e0f | d7c04e2dbf73 | historical_bound_provider_receipt | 980 / 861 |
| translator | gpt-6-astra / gpt-6-astra | 16f093c60011 | 13dfa2324721 | 4dcafbf93552 | historical_bound_provider_receipt | 627 / 410 |
| reviewer | gpt-6-sol / gpt-6-sol | 16f093c60011 | d3869db767bb | 19be717c9ddb | historical_bound_provider_receipt | 949 / 799 |
| translator | gpt-6-astra / gpt-6-astra | d0749cd497a4 | 770aa9468e41 | 0964f956a888 | historical_bound_provider_receipt | 578 / 364 |
| reviewer | gpt-6-sol / gpt-6-sol | d0749cd497a4 | 46d81a20abb7 | 4267ac50a88b | historical_bound_provider_receipt | 864 / 527 |

Diagnostics:
