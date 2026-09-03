import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import run_spark_qwen_sermon_ab as subject


def test_public_request_is_deterministic_and_structured():
    request = subject.public_request(
        model="qwen",
        system_prompt="translate",
        user_payload={"b": 2, "a": 1},
        schema={"type": "object"},
    )
    assert request["temperature"] == 0
    assert request["seed"] == 42
    assert request["response_format"]["type"] == "json_schema"
    assert request["messages"][1]["content"] == '{"a":1,"b":2}'


def test_cached_request_rejects_identity_drift(tmp_path, monkeypatch):
    cache = tmp_path / "cache.json"
    cache.write_text(json.dumps({"inputSha256": "wrong", "result": {}}), encoding="utf-8")
    try:
        subject.request_json_cached(
            base_url="http://127.0.0.1:1/v1",
            cache_path=cache,
            stage="first",
            prompt_version="v1",
            model="qwen",
            system_prompt="translate",
            user_payload={"segments": []},
            schema={"type": "object"},
            timeout_seconds=1,
        )
    except RuntimeError as exc:
        assert "Cache identity mismatch" in str(exc)
    else:
        raise AssertionError("identity drift must fail closed")


def test_totals_uses_model_generation_time():
    result = subject.totals([
        {
            "usage": {"prompt_tokens": 10, "completion_tokens": 20},
            "elapsedSeconds": 2.5,
            "timings": {"predicted_ms": 1000},
        }
    ])
    assert result == {
        "requests": 1,
        "promptTokens": 10,
        "completionTokens": 20,
        "elapsedSeconds": 2.5,
        "completionTokensPerSecond": 20.0,
    }
