# Run digest 20261012-pr360-pr362-offline-review-fixes

Generated 2026-10-13T01:24:13+00:00. Redacted copies only; source hashes are in manifest.json.

## 20261012-pr360-margin-validation

Source: `/private/tmp/sermon-fix-360/artifacts/run/20261012-pr360-margin-validation`

- outcome `outcome.json`: **passed** exit 0 (? → ?)

Timings `timings.tsv`:

| stage | status | elapsedSeconds |
|---|---|---|
| pytest | pass | 11.37 |

## pr362-offline-review-20261012

Source: `/private/tmp/sermon-fix-362/artifacts/pr362-offline-review-20261012`

- outcome `outcome.json`: **pass** exit 0 (? → ?)
- summary `summary.json`: **pass**

Timings `timings.tsv`:

| stage | status | elapsedSeconds |
|---|---|---|
| premerge-offline-regressions | pass | 67.868 |
| final-numeric-separator-guard-pytest | pass | 25.06 |

## pr362-final-base-quickcheck-20261012

Source: `/private/tmp/sermon-fix-362/artifacts/pr362-final-base-quickcheck-20261012`

- outcome `outcome.json`: **pass** exit 0 (? → ?)

Timings `timings.tsv`:

| stage | status | elapsedSeconds |
|---|---|---|
| pytest | pass | 0.86 |

## pr362-range-chain-review-20261012

Source: `/private/tmp/sermon-fix-362/artifacts/pr362-range-chain-review-20261012`

- outcome `outcome.json`: **pass** exit 0 (? → ?)

Timings `timings.tsv`:

| stage | status | elapsedSeconds |
|---|---|---|
| pytest | pass | 0.23 |

## pr362-range-fold-contract-20261012

Source: `/private/tmp/sermon-fix-362/artifacts/pr362-range-fold-contract-20261012`

- outcome `outcome.json`: **pass** exit 0 (? → ?)

Timings `timings.tsv`:

| stage | status | elapsedSeconds |
|---|---|---|
| pytest | pass | 0.83 |

## pr362-counter-structure-contract-20261012

Source: `/private/tmp/sermon-fix-362/artifacts/pr362-counter-structure-contract-20261012`

- outcome `outcome.json`: **pass** exit 0 (? → ?)

Timings `timings.tsv`:

| stage | status | elapsedSeconds |
|---|---|---|
| pytest | pass | 0.95 |

Error-like log lines (first 5 per log):

- `pytest.log`: E       AssertionError: assert '요한복음 3장십육-17절' == '요한복음 3장16-17절'
- `pytest.log`: tests/test_ko_spoken_numerals.py:149: AssertionError
- `pytest.log`: E       AssertionError: assert '요한복음 3장16절벽' == '요한복음 삼장16절벽'
- `pytest.log`: tests/test_ko_spoken_numerals.py:160: AssertionError
- `pytest.log`: tests/test_ko_spoken_numerals.py:175: AssertionError

## pr362-terminal-compound-contract-20261012

Source: `/private/tmp/sermon-fix-362/artifacts/pr362-terminal-compound-contract-20261012`

- outcome `outcome.json`: **pass** exit 0 (? → ?)

Timings `timings.tsv`:

| stage | status | elapsedSeconds |
|---|---|---|
| pytest | pass | 0.97 |

## pr362-implementation-closure-20261012

Source: `/private/tmp/sermon-fix-362/artifacts/pr362-implementation-closure-20261012`

- outcome `outcome.json`: **pass** exit 0 (? → ?)

Timings `timings.tsv`:

| stage | status | elapsedSeconds |
|---|---|---|
| initial-development | interrupted | 159.03 |
| fast-contracts | pass | 9.98 |
| waiver-dependency-mutation | pass | 0.09 |
| final-consumer | pass | 920.76 |

Failed stages: `initial-development`

Error-like log lines (first 5 per log):

- `pytest.log`: E               AssertionError: 2 != 1
- `pytest.log`: tests/test_run_machine_qc_audio_test.py:257: AssertionError
- `pytest.log`: ... 481 lines omitted; 61 error-like lines, 50 kept below ...
- `pytest.log`: [line 56] E           AssertionError: 2 != 0
- `pytest.log`: [line 58] tests/test_run_machine_qc_audio_test.py:237: AssertionError

## pr362-alternative-chain-20261012

Source: `/private/tmp/sermon-fix-362/artifacts/pr362-alternative-chain-20261012`

- outcome `outcome.json`: **pass** exit 0 (? → ?)

Timings `timings.tsv`:

| stage | status | elapsedSeconds |
|---|---|---|
| initial_alternative | fail | 1.01 |
| shared_connector | fail | 1.06 |
| numeric_atom | fail | 1.02 |
| connector_token_import | fail | 3.42 |
| final | pass | 1.01 |

Failed stages: `initial_alternative`, `shared_connector`, `numeric_atom`, `connector_token_import`

Error-like log lines (first 5 per log):

- `atom-final-tests.log`: E       AssertionError: assert '요한복음 3장부터만사장까지' == '요한복음 3장부터만4장까지'
- `atom-final-tests.log`: tests/test_ko_spoken_numerals.py:260: AssertionError
- `atom-final-tests.log`: FAILED tests/test_ko_spoken_numerals.py::test_shared_existing_alternative_and_range_connectors[-\ubd80\ud130\ub9cc]
- `atom-final-tests.log`: 1 failed, 218 passed, 34 subtests passed in 1.02s
- `pytest.log`: E       AssertionError: assert '요한복음 3장2나 4장' == '요한복음 3장이나 4장'
- `pytest.log`: tests/test_ko_spoken_numerals.py:239: AssertionError
- `pytest.log`: E       AssertionError: assert '요한복음 3장2나4장' == '요한복음 3장이나4장'
- `pytest.log`: tests/test_ko_spoken_numerals.py:239: AssertionError
- `pytest.log`: E       AssertionError: assert '시편 3편2나 4편' == '시편 3편이나 4편'
- `shared-final-tests.log`: E       AssertionError: assert '요한복음 3장2나 4장' == '요한복음 3장이나 4장'
- `shared-final-tests.log`: tests/test_ko_spoken_numerals.py:239: AssertionError
- `shared-final-tests.log`: E       AssertionError: assert '요한복음 3장2나4장' == '요한복음 3장이나4장'
- `shared-final-tests.log`: tests/test_ko_spoken_numerals.py:239: AssertionError
- `shared-final-tests.log`: E       AssertionError: assert '시편 3편2나 4편' == '시편 3편이나 4편'
- `token-final-tests.log`: ... 8402 lines omitted; 272 error-like lines, 50 kept below ...
- `token-final-tests.log`: [line 64] E           NameError: name '_CONNECTOR' is not defined
- `token-final-tests.log`: [line 66] scripts/screen_target_language_audio_units.py:426: NameError
- `token-final-tests.log`: [line 126] E           NameError: name '_CONNECTOR' is not defined
- `token-final-tests.log`: [line 128] scripts/screen_target_language_audio_units.py:426: NameError

## Connector semantics and spaced Sino followup

- [comma-final.log](pr362-connectors-spaced-sino-20261012/comma-final.log)
- [contract-final.log](pr362-connectors-spaced-sino-20261012/contract-final.log)
- [final-tests.log](pr362-connectors-spaced-sino-20261012/final-tests.log)
- [outcome.json](pr362-connectors-spaced-sino-20261012/outcome.json)
- [pytest.log](pr362-connectors-spaced-sino-20261012/pytest.log)
- [summary.json](pr362-connectors-spaced-sino-20261012/summary.json)
- [timings.tsv](pr362-connectors-spaced-sino-20261012/timings.tsv)

## Split known Bible book ASR anchors

- [outcome.json](pr362-split-book-anchor-20261012/outcome.json)
- [pytest.log](pr362-split-book-anchor-20261012/pytest.log)
- [summary.json](pr362-split-book-anchor-20261012/summary.json)
- [timings.tsv](pr362-split-book-anchor-20261012/timings.tsv)

## Bounded copula, connector spacing and digit padding

- [ci-root1.log](pr362-copula-connector-padding-20261012/ci-root1.log)
- [contract-final.log](pr362-copula-connector-padding-20261012/contract-final.log)
- [delivery-fixture.log](pr362-copula-connector-padding-20261012/delivery-fixture.log)
- [final-pass.log](pr362-copula-connector-padding-20261012/final-pass.log)
- [final-tests.log](pr362-copula-connector-padding-20261012/final-tests.log)
- [outcome.json](pr362-copula-connector-padding-20261012/outcome.json)
- [pytest.log](pr362-copula-connector-padding-20261012/pytest.log)
- [summary.json](pr362-copula-connector-padding-20261012/summary.json)
- [timings.tsv](pr362-copula-connector-padding-20261012/timings.tsv)

## Calibration spoken policy and cache binding

- [contract-final.log](pr362-calibration-spoken-policy-20261012/contract-final.log)
- [outcome.json](pr362-calibration-spoken-policy-20261012/outcome.json)
- [pytest.log](pr362-calibration-spoken-policy-20261012/pytest.log)
- [summary.json](pr362-calibration-spoken-policy-20261012/summary.json)
- [timings.tsv](pr362-calibration-spoken-policy-20261012/timings.tsv)

## Complete copulas and calibration implementation closure

- [closure-final.log](pr362-copula-calibration-closure-20261012/closure-final.log)
- [final-contract.log](pr362-copula-calibration-closure-20261012/final-contract.log)
- [outcome.json](pr362-copula-calibration-closure-20261012/outcome.json)
- [pytest.log](pr362-copula-calibration-closure-20261012/pytest.log)
- [summary.json](pr362-copula-calibration-closure-20261012/summary.json)
- [timings.tsv](pr362-copula-calibration-closure-20261012/timings.tsv)
- [transport-final.log](pr362-copula-calibration-closure-20261012/transport-final.log)
