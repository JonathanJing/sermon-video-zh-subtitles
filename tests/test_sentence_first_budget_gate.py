"""Budget gate and calibrated speaking rates (build_speech)."""

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE / "experiments" / "sentence-first-agent"))

import build_speech as B  # noqa: E402


def test_budget_summary_ratio_and_over_rows():
    rows = [{"id": "s0001", "estimatedSeconds": 2.0, "budgetSeconds": 2.0},
            {"id": "s0002", "estimatedSeconds": 3.0, "budgetSeconds": 2.0},
            {"id": "s0003", "estimatedSeconds": 1.0, "budgetSeconds": 2.0}]
    summary = B.budget_summary(rows)
    assert summary["estimatedSeconds"] == 6.0
    assert summary["budgetSeconds"] == 6.0
    assert summary["ratio"] == 1.0
    assert summary["overBudgetRows"] == 1


def test_budget_summary_handles_missing_fields():
    assert B.budget_summary([{"id": "s0001"}])["ratio"] is None


def test_locale_defaults_are_the_20261121_calibration():
    assert B.DEFAULTS["zh-Hans"][2] == 5.10
    assert B.DEFAULTS["ko"][2] == 6.00
    assert B.DEFAULTS["es"][2] == 14.67


def test_count_patterns_only_count_letters():
    import re
    assert len(re.findall(B.DEFAULTS["zh-Hans"][1], "耶稣必再来，2024 年。")) == 6
    assert len(re.findall(B.DEFAULTS["ko"][1], "예수님은 다시 오십니다")) == 10
    assert len(re.findall(B.DEFAULTS["es"][1], "Jesús volverá")) == 11  # J-e-s-ú-s + v-o-l-v-e-r-á
