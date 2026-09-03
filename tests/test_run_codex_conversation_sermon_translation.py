from pathlib import Path
import sys
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import run_codex_conversation_sermon_translation as subject


def test_command_is_ephemeral_read_only_and_structured(tmp_path):
    command = subject.codex_command(
        model="gpt-5.6-sol", reasoning_effort="high",
        schema_path=tmp_path / "schema.json", output_path=tmp_path / "out.json",
        workdir=tmp_path,
    )
    assert command[:3] == ["codex", "exec", "-"]
    assert "--ephemeral" in command
    assert command[command.index("--sandbox") + 1] == "read-only"
    assert command[command.index("--model") + 1] == "gpt-5.6-sol"
    assert "--output-schema" in command
    assert "--json" in command


def test_ab_models_are_explicitly_allowed():
    assert subject.ALLOWED_MODELS == {"gpt-5.6-sol", "gpt-5.6-terra"}
    assert subject.DEFAULT_TRANSLATE_MODEL == "gpt-5.6-terra"
    assert subject.DEFAULT_REVIEW_MODEL == "gpt-5.6-sol"


def test_environment_removes_api_keys(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "not-a-real-key")
    monkeypatch.setenv("CODEX_API_KEY", "not-a-real-key")
    env = subject.clean_environment()
    assert "OPENAI_API_KEY" not in env
    assert "CODEX_API_KEY" not in env


def test_exact_ids_fails_closed():
    expected = [{"id": "a"}, {"id": "b"}]
    try:
        subject.exact_ids(expected, [{"id": "b", "zh": "乙"}, {"id": "a", "zh": "甲"}], "test")
    except RuntimeError as exc:
        assert "id mismatch" in str(exc)
    else:
        raise AssertionError("reordered ids must fail")


def test_schema_is_strict():
    schema = subject.review_schema()
    assert schema["additionalProperties"] is False
    assert schema["properties"]["segments"]["items"]["additionalProperties"] is False


def test_extract_usage_reads_only_completed_turn():
    stream = '\n'.join([
        '{"type":"turn.started"}',
        '{"type":"turn.completed","usage":{"input_tokens":123,"cached_input_tokens":45,"output_tokens":67,"elapsed_ms":9}}',
    ])
    assert subject.extract_usage(stream) == {
        "input_tokens": 123,
        "cached_input_tokens": 45,
        "output_tokens": 67,
    }


def test_must_fix_requires_real_correction():
    source = {"id": "a", "zh": "未修改"}
    candidate = {"id": "a", "zh": "未修改", "severity": "must_fix"}
    try:
        subject.require_review_correction(source, candidate)
    except RuntimeError as exc:
        assert "did not change" in str(exc)
    else:
        raise AssertionError("must_fix without a correction must fail")


def test_sol_high_review_disposition_routes_audio_out_and_keeps_no_human_claim():
    passed = subject.review_disposition({"severity": "pass"})
    assert passed["reviewStatus"] == "sol_high_text_review_passed"
    assert passed["qualityTier"] == "model_reviewed_candidate"
    assert passed["datasetCandidateEligibility"] == "candidate"
    assert passed["trainingEligibility"] == "blocked"
    assert "chinese_not_human_approved" not in passed["trainingBlockers"]

    corrected = subject.review_disposition({"severity": "must_fix"})
    assert corrected["reviewStatus"] == "sol_high_text_review_corrected"

    audio = subject.review_disposition({"severity": "needs_audio_review"})
    assert audio["reviewStatus"] == "excluded_requires_audio_evidence"
    assert audio["datasetCandidateEligibility"] == "excluded"
    assert "independent_audio_listening_not_completed" in audio["trainingBlockers"]


def test_imported_candidates_are_bound_to_frozen_english(tmp_path):
    candidate = tmp_path / "candidate.jsonl"
    subject.write_jsonl(candidate, [{"id": "s1", "en": "Frozen source", "zh": "冻结来源"}])
    rows, receipt = subject.imported_candidates(
        candidate, [{"id": "s1", "en": "Frozen source", "sourceTextSha256": "abc"}]
    )
    assert rows[0]["zh"] == "冻结来源"
    assert rows[0]["en"] == "Frozen source"
    assert receipt["imported"] is True
    assert receipt["sharedCodexUsageConsumed"] is False


def test_imported_candidates_reject_english_mismatch(tmp_path):
    candidate = tmp_path / "candidate.jsonl"
    subject.write_jsonl(candidate, [{"id": "s1", "en": "Different", "zh": "候选"}])
    try:
        subject.imported_candidates(candidate, [{"id": "s1", "en": "Frozen"}])
    except RuntimeError as exc:
        assert "English mismatch" in str(exc)
    else:
        raise AssertionError("candidate bound to different English must fail")


def test_imported_candidates_reject_duplicate_ids(tmp_path):
    candidate = tmp_path / "candidate.jsonl"
    subject.write_jsonl(candidate, [
        {"id": "s1", "en": "Frozen", "zh": "候选一"},
        {"id": "s1", "en": "Frozen", "zh": "候选二"},
    ])
    try:
        subject.imported_candidates(candidate, [{"id": "s1", "en": "Frozen"}])
    except RuntimeError as exc:
        assert "duplicate ids" in str(exc)
    else:
        raise AssertionError("duplicate ids must fail")


def test_cache_path_is_model_scoped(monkeypatch, tmp_path):
    first_cache = tmp_path / "cache" / "translate" / "gpt-5.6-terra" / "s1_s1.json"
    first_cache.parent.mkdir(parents=True)
    prompt = "prompt"
    schema = subject.translation_schema()
    identity = subject.stable_hash({
        "stage": "translate", "promptVersion": "v1", "model": "gpt-5.6-terra",
        "reasoningEffort": "high", "prompt": prompt, "schema": schema,
    })
    subject.write_json(first_cache, {
        "inputSha256": identity, "result": {"segments": [{"id": "s1", "zh": "译文"}]},
        "usage": {}, "elapsedSeconds": 0,
    })
    rows, receipt = subject.invoke_codex_cached(
        out_dir=tmp_path, stage="translate", prompt_version="v1", prompt=prompt,
        schema=schema, expected=[{"id": "s1"}], model="gpt-5.6-terra",
        reasoning_effort="high", timeout_seconds=1,
    )
    assert rows[0]["zh"] == "译文"
    assert receipt["cacheHit"] is True


def test_invalid_fresh_output_preserves_failure_receipt_without_success_cache(monkeypatch, tmp_path):
    def fake_run(command, **kwargs):
        output_path = Path(command[command.index("--output-last-message") + 1])
        subject.write_json(output_path, {"segments": [{"id": "s1", "zh": "译文"}]})
        return SimpleNamespace(
            returncode=0,
            stdout='{"type":"turn.completed","usage":{"input_tokens":10,"output_tokens":3}}\n',
            stderr="",
        )

    monkeypatch.setattr(subject.subprocess, "run", fake_run)
    try:
        subject.invoke_codex_cached(
            out_dir=tmp_path, stage="translate", prompt_version="v1", prompt="prompt",
            schema=subject.translation_schema(), expected=[{"id": "s1"}, {"id": "s2"}],
            model="gpt-5.6-terra", reasoning_effort="high", timeout_seconds=1,
        )
    except RuntimeError as exc:
        assert "id mismatch" in str(exc)
    else:
        raise AssertionError("incomplete model output must fail")

    assert not list((tmp_path / "cache").rglob("*.json"))
    failures = list((tmp_path / "failures").rglob("*.json"))
    assert len(failures) == 1
    receipt = subject.read_json(failures[0])
    assert receipt["status"] == "invalid_fresh_model_output"
    assert receipt["usage"] == {"input_tokens": 10, "output_tokens": 3}
    assert receipt["sharedCodexUsageConsumed"] is True


def test_invalid_semantic_cache_is_preserved_and_only_bad_batch_is_reexecuted(monkeypatch, tmp_path):
    prompt = "review prompt"
    schema = subject.review_schema()
    identity = subject.stable_hash({
        "stage": "review-v2", "promptVersion": "v2", "model": "gpt-5.6-sol",
        "reasoningEffort": "high", "prompt": prompt, "schema": schema,
    })
    cache = tmp_path / "cache" / "review-v2" / "gpt-5.6-sol" / "s1_s1.json"
    subject.write_json(cache, {
        "inputSha256": identity,
        "result": {"segments": [{
            "id": "s1", "zh": "未修改", "severity": "must_fix",
            "categories": [], "findingZh": "需修改", "recommendationZh": "修改",
        }]},
        "usage": {"input_tokens": 5}, "elapsedSeconds": 1,
        "sharedCodexUsageConsumed": True,
    })
    calls = []

    def fake_run(command, **kwargs):
        calls.append(command)
        output_path = Path(command[command.index("--output-last-message") + 1])
        subject.write_json(output_path, {"segments": [{
            "id": "s1", "zh": "已经修改", "severity": "must_fix",
            "categories": [], "findingZh": "已修改", "recommendationZh": "采用修订",
        }]})
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(subject.subprocess, "run", fake_run)
    rows, receipt = subject.invoke_codex_cached(
        out_dir=tmp_path, stage="review-v2", prompt_version="v2", prompt=prompt,
        schema=schema, expected=[{"id": "s1", "zh": "未修改"}], model="gpt-5.6-sol",
        reasoning_effort="high", timeout_seconds=1,
        row_validator=subject.validate_review_rows,
    )
    assert len(calls) == 1
    assert rows[0]["zh"] == "已经修改"
    assert receipt["cacheHit"] is False
    assert cache.is_file()
    failures = list((tmp_path / "failures").rglob("*.json"))
    assert len(failures) == 1
    assert subject.read_json(failures[0])["status"] == "invalidated_cached_model_output"
