from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import compare_spark_qwen_to_gpt as subject


def test_qwen_label_assignment_is_stable_and_mixed():
    values = [subject.qwen_is_a(f"segment-{index}") for index in range(50)]
    assert values == [subject.qwen_is_a(f"segment-{index}") for index in range(50)]
    assert any(values)
    assert not all(values)


def test_number_omissions_counts_segments_not_tokens():
    rows = [
        {"en": "John 3:16 and 17", "zh": "约翰福音3:16"},
        {"en": "There were 2 and 3", "zh": "有两样"},
        {"en": "No number", "zh": "没有数字"},
    ]
    assert subject.number_omissions(rows) == 2


def test_schema_disallows_extra_fields():
    value = subject.schema()
    assert value["additionalProperties"] is False
    assert value["properties"]["segments"]["items"]["additionalProperties"] is False
