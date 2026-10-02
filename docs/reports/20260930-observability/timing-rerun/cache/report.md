# Weekly Pipeline Report

Status: projected

Projected means a computable recorded DAG, not complete telemetry. Content/device/venue/release acceptance: not evaluated.

## Run 17283bbff17e

End-to-end wall seconds: 2.3008508682250977
Active critical-path seconds: 1.889312

| Executor | Leaf elapsed seconds (parallel subtotal) |
|---|---:|
| decision_agent | 0 (not_observed; completed spans only) |
| deterministic_program | 2.030039 (measured_completed_spans; completed spans only) |
| engineering_codex | 0 (not_observed; completed spans only) |
| external_service | 0 (not_observed; completed spans only) |
| human | 0 (not_observed; completed spans only) |
| production_model | 0 (not_observed; completed spans only) |

Coverage: {"crossProcessCriticalPath": "not_established", "locales": "recorded", "logCompleteness": "not_established", "orchestrationOverhead": "missing_instrumentation", "pageReady": "not_observed", "queueTiming": "missing_instrumentation", "sourceDuration": "recorded", "statusMeaning": "projected_means_computable_recorded_DAG_not_complete_telemetry"}

| Stage / attempt | Executor / models | Cache | Start → finish | Dependencies | Queue |
|---|---|---|---|---|---|
| diagnostic.real_source_decode / 4cba7e39c557 | deterministic_program /  | False | 2026-09-30T15:00:18.166470+00:00 → 2026-09-30T15:00:20.008948+00:00 |  | missing_instrumentation |
| diagnostic.candidate.es / 02e7bccad9ca | deterministic_program /  | False | 2026-09-30T15:00:20.384406+00:00 → 2026-09-30T15:00:20.412813+00:00 | 04efcca735be | missing_instrumentation |
| diagnostic.candidate.zh-Hans / 4d2c290ea4e5 | deterministic_program /  | False | 2026-09-30T15:00:20.119207+00:00 → 2026-09-30T15:00:20.147542+00:00 | fcf598def826 | missing_instrumentation |
| diagnostic.candidate.ko / 3e3e7b862b3a | deterministic_program /  | False | 2026-09-30T15:00:20.243449+00:00 → 2026-09-30T15:00:20.270785+00:00 | b5a3adacb46a | missing_instrumentation |
| layer2.prepare.es.group-0001 / 1452fbbef803 | deterministic_program / gpt-6-astra,gpt-6-sol | True | 2026-09-30T15:00:20.340776+00:00 → 2026-09-30T15:00:20.351318+00:00 | 9f3edd1bb3da | missing_instrumentation |
| layer2.source_admission.zh-Hans / c6503131fd54 | deterministic_program /  | False | 2026-09-30T15:00:20.070832+00:00 → 2026-09-30T15:00:20.076196+00:00 | 583d980500c7 | missing_instrumentation |
| layer2.source_admission.ko / acc51fdd09ff | deterministic_program /  | False | 2026-09-30T15:00:20.206035+00:00 → 2026-09-30T15:00:20.210235+00:00 | 583d980500c7 | missing_instrumentation |
| layer2.source_admission.es / 9b36d3e6eb73 | deterministic_program /  | False | 2026-09-30T15:00:20.333482+00:00 → 2026-09-30T15:00:20.337655+00:00 | 583d980500c7 | missing_instrumentation |
| layer2.prepare.es.group-0007 / 1f10e18fb9cf | deterministic_program / gpt-6-astra,gpt-6-sol | True | 2026-09-30T15:00:20.365147+00:00 → 2026-09-30T15:00:20.368724+00:00 | 9f3edd1bb3da | missing_instrumentation |
| layer2.run_admission.zh-Hans / 8a3a950c4e72 | deterministic_program /  | False | 2026-09-30T15:00:20.076474+00:00 → 2026-09-30T15:00:20.079233+00:00 | 79cf48670705 | missing_instrumentation |
| layer2.prepare.es.group-0006 / 698f10f82357 | deterministic_program / gpt-6-astra,gpt-6-sol | True | 2026-09-30T15:00:20.361809+00:00 → 2026-09-30T15:00:20.364457+00:00 | 9f3edd1bb3da | missing_instrumentation |
| layer2.prepare.es.group-0009 / c45af27c8fd4 | deterministic_program / gpt-6-astra,gpt-6-sol | True | 2026-09-30T15:00:20.371953+00:00 → 2026-09-30T15:00:20.374553+00:00 | 9f3edd1bb3da | missing_instrumentation |
| layer2.prepare.ko.group-0005 / 57ae721d8861 | deterministic_program / gpt-6-astra,gpt-6-sol | True | 2026-09-30T15:00:20.222397+00:00 → 2026-09-30T15:00:20.224951+00:00 | 6262e7464136 | missing_instrumentation |
| layer2.prepare.zh-Hans.group-0002 / 089c378969f8 | deterministic_program / gpt-6-astra,gpt-6-sol | True | 2026-09-30T15:00:20.082038+00:00 → 2026-09-30T15:00:20.084560+00:00 | b38d3f685b75 | missing_instrumentation |
| layer2.prepare.zh-Hans.group-0011 / 445eea0a3348 | deterministic_program / gpt-6-astra,gpt-6-sol | True | 2026-09-30T15:00:20.105976+00:00 → 2026-09-30T15:00:20.108432+00:00 | b38d3f685b75 | missing_instrumentation |
| layer2.run_admission.es / 7fdc4c415800 | deterministic_program /  | False | 2026-09-30T15:00:20.337902+00:00 → 2026-09-30T15:00:20.340346+00:00 | e0d28683a8ed | missing_instrumentation |
| layer2.prepare.zh-Hans.group-0005 / 150991d8edd2 | deterministic_program / gpt-6-astra,gpt-6-sol | True | 2026-09-30T15:00:20.089659+00:00 → 2026-09-30T15:00:20.092110+00:00 | b38d3f685b75 | missing_instrumentation |
| layer2.prepare.zh-Hans.group-0008 / 99dbe45dab01 | deterministic_program / gpt-6-astra,gpt-6-sol | True | 2026-09-30T15:00:20.097649+00:00 → 2026-09-30T15:00:20.100078+00:00 | b38d3f685b75 | missing_instrumentation |
| layer2.prepare.zh-Hans.group-0009 / a721889ea585 | deterministic_program / gpt-6-astra,gpt-6-sol | True | 2026-09-30T15:00:20.100653+00:00 → 2026-09-30T15:00:20.103049+00:00 | b38d3f685b75 | missing_instrumentation |
| layer2.prepare.ko.group-0009 / ee325086db2e | deterministic_program / gpt-6-astra,gpt-6-sol | True | 2026-09-30T15:00:20.232472+00:00 → 2026-09-30T15:00:20.234762+00:00 | 6262e7464136 | missing_instrumentation |
| layer2.prepare.zh-Hans.group-0006 / c88e902c00af | deterministic_program / gpt-6-astra,gpt-6-sol | True | 2026-09-30T15:00:20.092599+00:00 → 2026-09-30T15:00:20.094888+00:00 | b38d3f685b75 | missing_instrumentation |
| layer2.run_admission.ko / bfac35956506 | deterministic_program /  | False | 2026-09-30T15:00:20.210499+00:00 → 2026-09-30T15:00:20.212755+00:00 | 7fd56079d5b2 | missing_instrumentation |
| layer2.prepare.es.group-0003 / 7a7e95e25660 | deterministic_program / gpt-6-astra,gpt-6-sol | True | 2026-09-30T15:00:20.354392+00:00 → 2026-09-30T15:00:20.356656+00:00 | 9f3edd1bb3da | missing_instrumentation |
| layer2.prepare.ko.group-0008 / b56e0f722307 | deterministic_program / gpt-6-astra,gpt-6-sol | True | 2026-09-30T15:00:20.229818+00:00 → 2026-09-30T15:00:20.232029+00:00 | 6262e7464136 | missing_instrumentation |
| layer2.prepare.es.group-0010 / 6500c1afa162 | deterministic_program / gpt-6-astra,gpt-6-sol | True | 2026-09-30T15:00:20.375077+00:00 → 2026-09-30T15:00:20.377179+00:00 | 9f3edd1bb3da | missing_instrumentation |
| layer2.prepare.ko.group-0003 / 2c2d9b885c11 | deterministic_program / gpt-6-astra,gpt-6-sol | True | 2026-09-30T15:00:20.217676+00:00 → 2026-09-30T15:00:20.219718+00:00 | 6262e7464136 | missing_instrumentation |
| layer2.prepare.es.group-0008 / a648ac2490d9 | deterministic_program / gpt-6-astra,gpt-6-sol | True | 2026-09-30T15:00:20.369397+00:00 → 2026-09-30T15:00:20.371445+00:00 | 9f3edd1bb3da | missing_instrumentation |
| layer2.prepare.ko.group-0010 / a382a7de3f8e | deterministic_program / gpt-6-astra,gpt-6-sol | True | 2026-09-30T15:00:20.235198+00:00 → 2026-09-30T15:00:20.237226+00:00 | 6262e7464136 | missing_instrumentation |
| layer2.prepare.ko.group-0002 / 689b591a46f5 | deterministic_program / gpt-6-astra,gpt-6-sol | True | 2026-09-30T15:00:20.215305+00:00 → 2026-09-30T15:00:20.217325+00:00 | 6262e7464136 | missing_instrumentation |
| layer2.prepare.es.group-0002 / aeab309b0b61 | deterministic_program / gpt-6-astra,gpt-6-sol | True | 2026-09-30T15:00:20.351914+00:00 → 2026-09-30T15:00:20.353915+00:00 | 9f3edd1bb3da | missing_instrumentation |
| layer2.prepare.zh-Hans.group-0001 / 901496a3b575 | deterministic_program / gpt-6-astra,gpt-6-sol | True | 2026-09-30T15:00:20.079656+00:00 → 2026-09-30T15:00:20.081657+00:00 | b38d3f685b75 | missing_instrumentation |
| layer2.prepare.es.group-0004 / 0e9aa2d3b257 | deterministic_program / gpt-6-astra,gpt-6-sol | True | 2026-09-30T15:00:20.357270+00:00 → 2026-09-30T15:00:20.359271+00:00 | 9f3edd1bb3da | missing_instrumentation |
| layer2.prepare.zh-Hans.group-0003 / d51791c60cb3 | deterministic_program / gpt-6-astra,gpt-6-sol | True | 2026-09-30T15:00:20.085082+00:00 → 2026-09-30T15:00:20.087063+00:00 | b38d3f685b75 | missing_instrumentation |
| layer2.prepare.es.group-0011 / c6489f08946b | deterministic_program / gpt-6-astra,gpt-6-sol | True | 2026-09-30T15:00:20.377592+00:00 → 2026-09-30T15:00:20.379521+00:00 | 9f3edd1bb3da | missing_instrumentation |
| layer2.prepare.zh-Hans.group-0007 / 353b7babfa5d | deterministic_program / gpt-6-astra,gpt-6-sol | True | 2026-09-30T15:00:20.095292+00:00 → 2026-09-30T15:00:20.097185+00:00 | b38d3f685b75 | missing_instrumentation |
| layer2.prepare.ko.group-0004 / ae5fa45fd218 | deterministic_program / gpt-6-astra,gpt-6-sol | True | 2026-09-30T15:00:20.220117+00:00 → 2026-09-30T15:00:20.222004+00:00 | 6262e7464136 | missing_instrumentation |
| layer2.prepare.ko.group-0001 / e0213fbac85c | deterministic_program / gpt-6-astra,gpt-6-sol | True | 2026-09-30T15:00:20.213072+00:00 → 2026-09-30T15:00:20.214914+00:00 | 6262e7464136 | missing_instrumentation |
| layer2.prepare.ko.group-0006 / 6841d8d638dd | deterministic_program / gpt-6-astra,gpt-6-sol | True | 2026-09-30T15:00:20.225478+00:00 → 2026-09-30T15:00:20.227318+00:00 | 6262e7464136 | missing_instrumentation |
| layer2.prepare.zh-Hans.group-0004 / 1cb0c62c8eef | deterministic_program / gpt-6-astra,gpt-6-sol | True | 2026-09-30T15:00:20.087469+00:00 → 2026-09-30T15:00:20.089265+00:00 | b38d3f685b75 | missing_instrumentation |
| layer2.prepare.zh-Hans.group-0010 / 6b77927d51da | deterministic_program / gpt-6-astra,gpt-6-sol | True | 2026-09-30T15:00:20.103521+00:00 → 2026-09-30T15:00:20.105316+00:00 | b38d3f685b75 | missing_instrumentation |
| layer2.evidence_assembly.es / 77f52ce27888 | deterministic_program /  | False | 2026-09-30T15:00:20.379809+00:00 → 2026-09-30T15:00:20.381610+00:00 | c29df8d2d593,20a967312084,2bbb7d7bc4bd,c0c03a8a8f27,2ef6883f5efc,1166f363bc32,40a85297d3e0,8ac757cf9d6f,4500f372250d,5b3394199c7b,ab0091bfef3c | missing_instrumentation |
| layer2.prepare.es.group-0005 / f3c2dc22d932 | deterministic_program / gpt-6-astra,gpt-6-sol | True | 2026-09-30T15:00:20.359689+00:00 → 2026-09-30T15:00:20.361436+00:00 | 9f3edd1bb3da | missing_instrumentation |
| layer2.prepare.ko.group-0007 / 5c9612c87e69 | deterministic_program / gpt-6-astra,gpt-6-sol | True | 2026-09-30T15:00:20.227767+00:00 → 2026-09-30T15:00:20.229450+00:00 | 6262e7464136 | missing_instrumentation |
| layer2.prepare.ko.group-0011 / b9d61102d766 | deterministic_program / gpt-6-astra,gpt-6-sol | True | 2026-09-30T15:00:20.237600+00:00 → 2026-09-30T15:00:20.239243+00:00 | 6262e7464136 | missing_instrumentation |
| layer2.evidence_assembly.ko / 206d9c94be6e | deterministic_program /  | False | 2026-09-30T15:00:20.239497+00:00 → 2026-09-30T15:00:20.241109+00:00 | df306167909d,ca3285cf32e1,1197a714ad7c,7a9e3b23d46c,3a1f8ed1351e,9eaa70a0693d,368ab34c29b7,5fc919f689eb,75b141733a86,5946b2c2991c,4dc1838914de | missing_instrumentation |
| layer2.evidence_assembly.zh-Hans / a3412e9e0d8e | deterministic_program /  | False | 2026-09-30T15:00:20.108806+00:00 → 2026-09-30T15:00:20.110241+00:00 | a983d6de4167,02ca5c55af04,c5fb23a01e07,b2aaea8b51e1,bbba79da44dc,c8e97a7f5efb,144d76cdf024,d29e09ca6e35,4c5ea225c588,b951292cc82b,bd327dd4dd17 | missing_instrumentation |

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
| translator | gpt-6-astra / gpt-6-astra | a983d6de4167 | 143c0fb7cd08 | 634a0af7c9d8 | historical_bound_provider_receipt | 577 / 439 |
| reviewer | gpt-6-sol / gpt-6-sol | a983d6de4167 | 750e97946600 | 965b3cb18bbe | historical_bound_provider_receipt | 885 / 465 |
| translator | gpt-6-astra / gpt-6-astra | 02ca5c55af04 | 5a78e2cfee94 | 93cbe6d158ed | historical_bound_provider_receipt | 592 / 324 |
| reviewer | gpt-6-sol / gpt-6-sol | 02ca5c55af04 | 60e1d36ad9ae | 8ad9782f8945 | historical_bound_provider_receipt | 857 / 639 |
| translator | gpt-6-astra / gpt-6-astra | c5fb23a01e07 | ef4050ff0f3b | c5aba0e7f6bb | historical_bound_provider_receipt | 598 / 269 |
| reviewer | gpt-6-sol / gpt-6-sol | c5fb23a01e07 | 0ace4d0727ff | 0f914f77e63b | historical_bound_provider_receipt | 922 / 566 |
| translator | gpt-6-astra / gpt-6-astra | b2aaea8b51e1 | dc707b845639 | d86bcbf18277 | historical_bound_provider_receipt | 584 / 267 |
| reviewer | gpt-6-sol / gpt-6-sol | b2aaea8b51e1 | 890fbb175245 | 2836ca29d9ea | historical_bound_provider_receipt | 908 / 853 |
| translator | gpt-6-astra / gpt-6-astra | bbba79da44dc | 27510980c79b | f2a175477e8a | historical_bound_provider_receipt | 595 / 375 |
| reviewer | gpt-6-sol / gpt-6-sol | bbba79da44dc | 8f03845fbd98 | 4fe0a8c6e8a6 | historical_bound_provider_receipt | 917 / 490 |
| translator | gpt-6-astra / gpt-6-astra | c8e97a7f5efb | b63d49c0cc71 | 9269e8bf8916 | historical_bound_provider_receipt | 575 / 373 |
| reviewer | gpt-6-sol / gpt-6-sol | c8e97a7f5efb | 7c92ae2fb7ff | a293e43c3d41 | historical_bound_provider_receipt | 859 / 427 |
| translator | gpt-6-astra / gpt-6-astra | 144d76cdf024 | 462a588d40f5 | d0d3579b325f | historical_bound_provider_receipt | 580 / 398 |
| reviewer | gpt-6-sol / gpt-6-sol | 144d76cdf024 | 563d9be1ded3 | ccb47f0f661d | historical_bound_provider_receipt | 866 / 447 |
| translator | gpt-6-astra / gpt-6-astra | d29e09ca6e35 | 9c0dda2df67a | 8747154b3fbc | historical_bound_provider_receipt | 592 / 376 |
| reviewer | gpt-6-sol / gpt-6-sol | d29e09ca6e35 | 0402e89c9b71 | ff341c3cb845 | historical_bound_provider_receipt | 878 / 543 |
| translator | gpt-6-astra / gpt-6-astra | 4c5ea225c588 | 716bddd0a426 | 208340cfc049 | historical_bound_provider_receipt | 631 / 511 |
| reviewer | gpt-6-sol / gpt-6-sol | 4c5ea225c588 | cd6608e18b19 | d0f4b66c35b1 | historical_bound_provider_receipt | 1009 / 610 |
| translator | gpt-6-astra / gpt-6-astra | b951292cc82b | bccad4fc7022 | 93db9f95d83b | historical_bound_provider_receipt | 629 / 425 |
| reviewer | gpt-6-sol / gpt-6-sol | b951292cc82b | bc9790b8997b | 11078f7d2f8e | historical_bound_provider_receipt | 980 / 964 |
| translator | gpt-6-astra / gpt-6-astra | bd327dd4dd17 | 0d2bd5fea547 | f3c10c8ddcec | historical_bound_provider_receipt | 580 / 426 |
| reviewer | gpt-6-sol / gpt-6-sol | bd327dd4dd17 | e11112fc327d | 5edca33aa881 | historical_bound_provider_receipt | 890 / 818 |
| translator | gpt-6-astra / gpt-6-astra | df306167909d | 54a66891ac1e | 6f894cafec13 | historical_bound_provider_receipt | 574 / 269 |
| reviewer | gpt-6-sol / gpt-6-sol | df306167909d | dd0e86d8fed4 | 810c92179998 | historical_bound_provider_receipt | 901 / 703 |
| translator | gpt-6-astra / gpt-6-astra | ca3285cf32e1 | cbe3fa9a74e1 | da412150c8c5 | historical_bound_provider_receipt | 589 / 314 |
| reviewer | gpt-6-sol / gpt-6-sol | ca3285cf32e1 | a1b5f23ae267 | d21dbfce9c90 | historical_bound_provider_receipt | 875 / 695 |
| translator | gpt-6-astra / gpt-6-astra | 1197a714ad7c | 9dce43c26452 | 05aaecd9d379 | historical_bound_provider_receipt | 595 / 303 |
| reviewer | gpt-6-sol / gpt-6-sol | 1197a714ad7c | 7aa23f6c75b9 | f51c08654454 | historical_bound_provider_receipt | 955 / 663 |
| translator | gpt-6-astra / gpt-6-astra | 7a9e3b23d46c | dffcf375e922 | e64215e7fc36 | historical_bound_provider_receipt | 581 / 275 |
| reviewer | gpt-6-sol / gpt-6-sol | 7a9e3b23d46c | 94deca5b37fb | 174f5040386d | historical_bound_provider_receipt | 914 / 784 |
| translator | gpt-6-astra / gpt-6-astra | 3a1f8ed1351e | 4690eed84b4a | b52f840fed31 | historical_bound_provider_receipt | 592 / 421 |
| reviewer | gpt-6-sol / gpt-6-sol | 3a1f8ed1351e | b11ff2d513d5 | 57d00259a4de | historical_bound_provider_receipt | 959 / 691 |
| translator | gpt-6-astra / gpt-6-astra | 9eaa70a0693d | b6380dba94d8 | a3041c4a1529 | historical_bound_provider_receipt | 572 / 474 |
| reviewer | gpt-6-sol / gpt-6-sol | 9eaa70a0693d | 8449dd93ac48 | 57d9385705f4 | historical_bound_provider_receipt | 891 / 866 |
| translator | gpt-6-astra / gpt-6-astra | 368ab34c29b7 | ed9dbdbece7d | e1376ef9a063 | historical_bound_provider_receipt | 577 / 434 |
| reviewer | gpt-6-sol / gpt-6-sol | 368ab34c29b7 | 5e698f5832ff | 860ca2f8462f | historical_bound_provider_receipt | 890 / 658 |
| translator | gpt-6-astra / gpt-6-astra | 5fc919f689eb | 0fee79583173 | 042fef40e1af | historical_bound_provider_receipt | 589 / 267 |
| reviewer | gpt-6-sol / gpt-6-sol | 5fc919f689eb | ab6df92e5d5e | c5138b68a9a6 | historical_bound_provider_receipt | 913 / 637 |
| translator | gpt-6-astra / gpt-6-astra | 75b141733a86 | ad7e1fa8703c | df9de1201740 | historical_bound_provider_receipt | 628 / 607 |
| reviewer | gpt-6-sol / gpt-6-sol | 75b141733a86 | 55d6e9ff177b | 440a20be4e03 | historical_bound_provider_receipt | 1055 / 1164 |
| translator | gpt-6-astra / gpt-6-astra | 5946b2c2991c | 78e0ee94633b | 363603c78bd6 | historical_bound_provider_receipt | 626 / 495 |
| reviewer | gpt-6-sol / gpt-6-sol | 5946b2c2991c | 1d4c11a4125b | d6d3dad2b6ef | historical_bound_provider_receipt | 1008 / 885 |
| translator | gpt-6-astra / gpt-6-astra | 4dc1838914de | be297a89bff4 | 34328e5e55a3 | historical_bound_provider_receipt | 577 / 386 |
| reviewer | gpt-6-sol / gpt-6-sol | 4dc1838914de | 3d1a412c04cc | 4b39e0a9ca62 | historical_bound_provider_receipt | 906 / 955 |
| translator | gpt-6-astra / gpt-6-astra | c29df8d2d593 | ad6fb0e5406e | e02146a3dc9b | historical_bound_provider_receipt | 575 / 488 |
| reviewer | gpt-6-sol / gpt-6-sol | c29df8d2d593 | c7c5e1c15956 | c547d03ed5c5 | historical_bound_provider_receipt | 884 / 784 |
| translator | gpt-6-astra / gpt-6-astra | 20a967312084 | 3027955a4273 | 00484a986890 | historical_bound_provider_receipt | 590 / 340 |
| reviewer | gpt-6-sol / gpt-6-sol | 20a967312084 | 59d841d7b88a | 70c5a3ce95d7 | historical_bound_provider_receipt | 852 / 658 |
| translator | gpt-6-astra / gpt-6-astra | 2bbb7d7bc4bd | 89a198286e3e | 7bbe66466b69 | historical_bound_provider_receipt | 596 / 250 |
| reviewer | gpt-6-sol / gpt-6-sol | 2bbb7d7bc4bd | ca2100448753 | e734a9464c4b | historical_bound_provider_receipt | 904 / 639 |
| translator | gpt-6-astra / gpt-6-astra | c0c03a8a8f27 | 5c74d518838e | 7df75bf93f96 | historical_bound_provider_receipt | 582 / 255 |
| reviewer | gpt-6-sol / gpt-6-sol | c0c03a8a8f27 | 2cec8bdac9c8 | d08d14769720 | historical_bound_provider_receipt | 895 / 611 |
| translator | gpt-6-astra / gpt-6-astra | 2ef6883f5efc | a00a995eca43 | bfc73c73aa72 | historical_bound_provider_receipt | 593 / 447 |
| reviewer | gpt-6-sol / gpt-6-sol | 2ef6883f5efc | eaa9ce42b314 | bedd699592fa | historical_bound_provider_receipt | 917 / 520 |
| translator | gpt-6-astra / gpt-6-astra | 1166f363bc32 | bcae76fa20f7 | bf50bfe1ee6d | historical_bound_provider_receipt | 573 / 332 |
| reviewer | gpt-6-sol / gpt-6-sol | 1166f363bc32 | 6a9aebe8a7fd | 7ef7e1525841 | historical_bound_provider_receipt | 850 / 714 |
| translator | gpt-6-astra / gpt-6-astra | 40a85297d3e0 | 1b80f042dad7 | c5d7083e4ccf | historical_bound_provider_receipt | 578 / 377 |
| reviewer | gpt-6-sol / gpt-6-sol | 40a85297d3e0 | 75b31f436053 | db8ff45d7b88 | historical_bound_provider_receipt | 852 / 589 |
| translator | gpt-6-astra / gpt-6-astra | 8ac757cf9d6f | 5b6d89ac8d02 | 600cd8d3cc09 | historical_bound_provider_receipt | 590 / 331 |
| reviewer | gpt-6-sol / gpt-6-sol | 8ac757cf9d6f | fb6fbb1dabf6 | 2befa194f5d5 | historical_bound_provider_receipt | 871 / 448 |
| translator | gpt-6-astra / gpt-6-astra | 4500f372250d | f3be4a0580ed | 01fc7ccfc299 | historical_bound_provider_receipt | 629 / 294 |
| reviewer | gpt-6-sol / gpt-6-sol | 4500f372250d | 42939d7f8e0f | d7c04e2dbf73 | historical_bound_provider_receipt | 980 / 861 |
| translator | gpt-6-astra / gpt-6-astra | 5b3394199c7b | 13dfa2324721 | 4dcafbf93552 | historical_bound_provider_receipt | 627 / 410 |
| reviewer | gpt-6-sol / gpt-6-sol | 5b3394199c7b | d3869db767bb | 19be717c9ddb | historical_bound_provider_receipt | 949 / 799 |
| translator | gpt-6-astra / gpt-6-astra | ab0091bfef3c | 770aa9468e41 | 0964f956a888 | historical_bound_provider_receipt | 578 / 364 |
| reviewer | gpt-6-sol / gpt-6-sol | ab0091bfef3c | 46d81a20abb7 | 4267ac50a88b | historical_bound_provider_receipt | 864 / 527 |

Diagnostics:
