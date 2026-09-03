from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import compare_codex_conversation_model_ab as subject


def test_label_assignment_is_stable_and_mixed():
    values = [subject.terra_is_a(f"segment-{index}") for index in range(30)]
    assert values == [subject.terra_is_a(f"segment-{index}") for index in range(30)]
    assert any(values) and not all(values)


def test_credit_calculation_uses_cached_subset():
    usage = {"input_tokens": 1000, "cached_input_tokens": 400, "output_tokens": 200}
    assert subject.credits(usage, "gpt-5.6-sol") == 0.164
    assert subject.credits(usage, "gpt-5.6-terra") == 0.092


def test_schema_is_strict():
    value = subject.schema()
    assert value["additionalProperties"] is False
    assert value["properties"]["segments"]["items"]["additionalProperties"] is False
