#!/usr/bin/env python3
"""Fast, isolated link-to-Layer-4 rehearsal with explicit simulated boundaries.

This does not run paid ASR/translation/TTS, create human review receipts, or
produce formal Layer 2-4 packages. It exercises the real Layer 1 anchor builder,
shadow lane planner, and target-audio scheduler, then makes a Dev-only preview.
"""
from __future__ import annotations

import argparse
import copy
from datetime import datetime, timezone
import hashlib
import html
import json
import math
from pathlib import Path
import struct
import tempfile
from time import monotonic
from urllib.parse import urlsplit
import wave

from jsonschema import Draft202012Validator, FormatChecker

try:
    from scripts import prepare_sentence_interpretation_shadow as layer1
    from scripts import prepare_multilingual_weekly_plan as planner
    from scripts import render_formal_target_language_speech as layer3
    from scripts import run_target_language_models as layer2_runner
    from scripts import produce_target_language_candidate as layer2_producer
except ImportError:
    import prepare_sentence_interpretation_shadow as layer1
    import prepare_multilingual_weekly_plan as planner
    import render_formal_target_language_speech as layer3
    import run_target_language_models as layer2_runner
    import produce_target_language_candidate as layer2_producer


ROOT = Path(__file__).resolve().parents[1]
SCHEMA = "sermon-backend-four-layer-dry-run-v2"
FIXTURE_SCHEMA = "sermon-backend-four-layer-dry-run-fixture-v1"
LOCALES = ("zh-Hans", "ko", "es")
RATE = 12000


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def canonical_sha(value: object) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":")).encode()).hexdigest()


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
                    encoding="utf-8")


def schema_check(value: dict, name: str) -> None:
    schema = json.loads((ROOT / "schemas" / name).read_text(encoding="utf-8"))
    errors = list(Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(value))
    if errors:
        raise ValueError(f"{name}: {errors[0].message}")


def checked_fixture(path: Path) -> dict:
    fixture = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(fixture, dict) or fixture.get("schemaVersion") != FIXTURE_SCHEMA \
            or fixture.get("simulationOnly") is not True:
        raise ValueError("A simulation-only fixture is required")
    parsed = urlsplit(fixture.get("sourceUrl", ""))
    if (parsed.scheme != "https" or parsed.hostname is None
            or not parsed.hostname.endswith(".invalid") or parsed.username or parsed.password
            or parsed.port or parsed.fragment):
        raise ValueError("Simulated link must use an HTTPS .invalid host")
    if not isinstance(fixture.get("sourceId"), str) or not fixture["sourceId"].strip():
        raise ValueError("Simulated source ID is required")
    duration = fixture.get("durationSeconds")
    if not isinstance(duration, (int, float)) or not 0 < duration <= 30:
        raise ValueError("Fixture duration must be 0-30 seconds")
    segments = fixture.get("englishSegments")
    if not isinstance(segments, list) or not 1 <= len(segments) <= 8:
        raise ValueError("Fixture needs 1-8 short English segments")
    translations = fixture.get("translations")
    if not isinstance(translations, dict) or set(translations) != set(LOCALES):
        raise ValueError("Fixture needs the three current target locales")
    for locale in LOCALES:
        rows = translations[locale]
        if not isinstance(rows, list) or len(rows) != len(segments) \
                or any(not isinstance(text, str) or not text.strip() for text in rows):
            raise ValueError(f"Missing simulated text: {locale}")
    if not isinstance(fixture.get("speakerId"), str) or not fixture["speakerId"]:
        raise ValueError("Fixture speaker ID is required")
    return fixture


def pcm(duration: float, frequency: float) -> bytes:
    samples = round(duration * RATE)
    return b"".join(struct.pack("<h", round(1600 * math.sin(2 * math.pi * frequency * i / RATE)))
                    for i in range(samples))


def wav(path: Path, signal: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(RATE)
        handle.writeframes(signal)


def simulated_policy(locale: str) -> dict:
    """Prompt inputs for a short fixture, never a frozen production policy."""
    return {"schemaVersion": "sermon-dry-run-model-policy-v1", "simulationOnly": True,
            "targetLocale": locale,
            "translator": {"model": "gpt-6-astra", "reasoningEffort": "medium",
                           "promptVersion": "dry-run-fixture-v1"},
            "reviewer": {"model": "gpt-6-sol", "reasoningEffort": "medium",
                         "promptVersion": "dry-run-fixture-v1"},
            "batching": {"batchSize": 1, "workers": 1},
            "terminology": {"seriesNames": [], "properNames": []},
            "scripture": {"quoteCheckPolicy": "references_only"},
            "formatting": {"speechRegister": "fixture_only"},
            "languageReview": {"registerRules": ["Use the fixed dry-run wording only."]}}


def render_preview(report: dict, fixture: dict, translated: dict, audio: dict) -> str:
    esc = html.escape
    blocks = []
    for locale in LOCALES:
        rows = "".join(f"<li><span>{esc(source['text'])}</span><strong>{esc(text)}</strong></li>"
                       for source, text in zip(fixture["englishSegments"], translated[locale]["texts"]))
        blocks.append(f'<section><h2>{esc(locale)}</h2><ol>{rows}</ol>'
                      f'<audio controls preload="none" src="media/{locale}.wav"></audio></section>')
    return ('<!doctype html><html lang="zh-Hans"><head><meta charset="utf-8">'
            '<meta name="robots" content="noindex,nofollow">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            '<title>后端四层模拟 · DRY RUN</title><style>'
            'body{font:1rem/1.6 system-ui,sans-serif;max-width:50rem;margin:auto;padding:1.3rem;'
            'color:#14342b;background:#f4f8f6}header,section{background:white;border:1px solid #bfd3cb;'
            'border-radius:1rem;padding:1rem;margin:1rem 0}strong{display:block}li{margin:.7rem 0}'
            'audio{width:100%}.warning{color:#8b3c13;font-weight:700}</style></head><body>'
            '<header><p class="warning">DRY RUN · SIMULATED · 不可用于正式发布</p>'
            '<h1>模拟链接 → Layer 1–4</h1>'
            f'<p>来源：{esc(fixture["sourceUrl"])}</p>'
            '<p>短音频为合成测试音，不是讲员配音；文字为固定测试夹具。</p>'
            '<p>正式人审门禁保持关闭。此页只验证后端交接和 Dev 页面链路。</p>'
            '<a href="report.json">查看阶段与耗时记录</a></header>'
            + "".join(blocks) + '</body></html>\n')


def run(fixture_path: Path, out: Path, *, fail_at: str | None = None) -> dict:
    if out.exists() or out.is_symlink():
        raise ValueError("Use a new dry-run output directory")
    if fail_at and fail_at not in ({"intake", "layer1", "layer4"} | {
            f"layer2:{locale}" for locale in LOCALES} | {
            f"layer3:{locale}" for locale in LOCALES} | {
            f"layer2:{locale}:unit-{index}:{role}"
            for locale in LOCALES for index in range(8) for role in ("astra", "sol")}):
        raise ValueError("Unknown failure injection point")
    out.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{out.name}-", dir=out.parent))
    events = []
    report = {"schemaVersion": SCHEMA, "simulationOnly": True, "status": "running",
              "fixtureSha256": digest(fixture_path), "sourceAcquisition": "simulated_no_network",
              "externalCalls": {"download": 0, "asr": 0, "translation": 0, "tts": 0, "firebase": 0},
              "formalApproval": False, "productionReleaseEligible": False,
              "sharedControlLoops": {"layer2": "astra_sol_group_runner",
                                     "layer3": "pcm16_schedule_and_assembly"},
              "layers": {}, "events": events}

    def step(name, action):
        started = datetime.now(timezone.utc).isoformat()
        clock = monotonic()
        event = {"step": name, "startedAt": started, "status": "running"}
        events.append(event)
        try:
            if fail_at == name:
                raise ValueError(f"Injected dry-run failure at {name}")
            result = action()
            event["status"] = "pass"
            return result
        except Exception as exc:
            event["status"] = "fail"
            event["error"] = str(exc)
            raise
        finally:
            event["endedAt"] = datetime.now(timezone.utc).isoformat()
            event["elapsedMs"] = round((monotonic() - clock) * 1000, 3)

    try:
        fixture = step("intake", lambda: checked_fixture(fixture_path))
        report["sourceUrlSha256"] = hashlib.sha256(fixture["sourceUrl"].encode()).hexdigest()
        report["sourceId"] = fixture["sourceId"]
        source_root = temporary / "source"

        def make_media_fixture():
            source_root.mkdir()
            wav(source_root / "source-media.wav", pcm(float(fixture["durationSeconds"]), 220))
            write_json(source_root / "aligned-segments.json", fixture["englishSegments"])
            write_json(source_root / "summary.json", {
                "sourceDurationSeconds": fixture["durationSeconds"],
                "sermonStartSeconds": 0, "sermonEndSeconds": fixture["durationSeconds"],
                "models": {"referenceAsr": "fixture_no_model"}, "readingAligner": "fixture_word_times",
                "pipelineInputIdentity": {"sourceAudio": {
                    "sha256": digest(source_root / "source-media.wav"),
                    "sizeBytes": (source_root / "source-media.wav").stat().st_size}},
            })
        step("media_fixture", make_media_fixture)

        def make_layer1():
            receipt = layer1.prepare_shadow(
                source_root / "aligned-segments.json", temporary / "layer1",
                summary_path=source_root / "summary.json", source_id=fixture["sourceId"],
                source_url_hash=report["sourceUrlSha256"], service_date=fixture["serviceDate"])
            package = json.loads(Path(receipt["artifacts"]["englishSourcePackage"]["path"]).read_text())
            anchor = json.loads(Path(receipt["artifacts"]["anchorManifest"]["path"]).read_text())
            schema_check(package, "sermon-english-source-package-v1.schema.json")
            if package["translationEligible"] or package["review"]["humanApproval"]:
                raise ValueError("Fixture must not gain formal Layer 1 approval")
            if len(anchor["sourceUnits"]) != len(fixture["englishSegments"]):
                raise ValueError("Fixture anchors no longer match fixed translation units")
            report["layers"]["layer1"] = {"status": "candidate_blocked_at_human_gate",
                "sourcePackageStatus": package["status"], "sourceUnits": len(anchor["sourceUnits"]),
                "sourcePackageJsonSha256": canonical_sha(package),
                "anchorManifestJsonSha256": canonical_sha(anchor),
                "humanReview": "pending", "asr": "simulated", "alignment": "fixture_word_times"}
            return package, anchor

        source, anchor = step("layer1", make_layer1)
        def make_shadow_plan():
            projected = copy.deepcopy(source)
            projected["status"] = "candidate_ready_for_translation"
            projected["candidateTranslationEligible"] = True
            projected["simulationProjection"] = True  # Deliberately invalid as a formal package.
            registry = json.loads((ROOT / "config/speaker-voice-registry.json").read_text())
            value = planner.prepare_plan(projected, registry, speaker_id=fixture["speakerId"],
                                         target_locales=list(LOCALES), mode="shadow")
            schema_check(value, "sermon-multilingual-weekly-plan-v1.schema.json")
            try:
                planner.prepare_plan(projected, registry, speaker_id=fixture["speakerId"],
                                     target_locales=list(LOCALES), mode="production")
            except ValueError as exc:
                if "ready_for_translation Layer 1" not in str(exc):
                    raise
                report["productionPlannerGate"] = "rejected_simulated_source"
            else:
                raise ValueError("Production planner accepted a simulated source")
            return value
        plan = step("shadow_plan", make_shadow_plan)
        write_json(temporary / "shadow-lane-plan.json", {"simulationOnly": True, "plan": plan})
        report["shadowPlanId"] = plan["planId"]
        translated = {}
        for locale in LOCALES:
            def make_text(locale=locale):
                policy = simulated_policy(locale)
                units = anchor["sourceUnits"]
                by_id = {unit["sourceUnitId"]: text for unit, text in
                         zip(units, fixture["translations"][locale])}
                request = {"schemaVersion": "sermon-dry-run-layer2-request-v1",
                           "simulationOnly": True, "sourceLocale": "en",
                           "targetLocale": locale,
                           "englishSourcePackageJsonSha256": canonical_sha(source),
                           "anchorManifestSha256": canonical_sha(anchor),
                           "translationPolicySha256": canonical_sha(policy),
                           "sourceUnits": [{"sourceUnitId": unit["sourceUnitId"],
                                            "english": unit["english"]} for unit in units],
                           "generation": None, "groups": None}
                group_plan = layer2_runner.group_plan(request, anchor)
                group_index = {row["translationGroupId"]: index
                               for index, row in enumerate(group_plan)}
                calls = []

                def fake_model_call(api_key, payload):
                    if api_key != "simulation-no-secret":
                        raise ValueError("Dry run attempted to use a model API key")
                    inputs = json.loads(payload["messages"][1]["content"])
                    group_id = inputs["translationGroupId"]
                    source_ids = inputs["sourceUnitIds"]
                    if group_id not in group_index or source_ids != group_plan[group_index[group_id]]["sourceUnitIds"]:
                        raise ValueError("Simulated model group identity changed")
                    role = "astra" if payload["model"] == "gpt-6-astra" else "sol"
                    if role == "sol" and payload["model"] != "gpt-6-sol":
                        raise ValueError("Unexpected simulated model role")
                    texts = [by_id[unit_id] for unit_id in source_ids]
                    result = {"translationGroupId": group_id,
                              "sourceUnitIds": source_ids, "targetUtterances": texts,
                              "coverage": [{"sourceUnitId": unit_id, "targetText": text}
                                           for unit_id, text in zip(source_ids, texts)]}
                    if role == "sol":
                        if inputs.get("astraDraft", {}).get("sourceUnitIds") != source_ids:
                            raise ValueError("Sol did not receive the matching Astra draft")
                        result["semanticReview"] = {
                            "status": "pass", "checks": {check: "pass" for check in
                                                          layer2_runner.SEMANTIC_CHECKS},
                            "evidence": "Deterministic fixture response; no semantic judgement.",
                            "uncertainty": [], "issues": []}
                    calls.append({"role": role, "groupId": group_id})
                    response_id = f"dry-{locale}-{group_index[group_id]:03d}-{role}"
                    return step(f"layer2:{locale}:unit-{group_index[group_id]}:{role}",
                                lambda: {"id": response_id, "model": payload["model"],
                                         "choices": [{"finish_reason": "stop", "message": {
                                             "content": json.dumps(result, ensure_ascii=False)}}]})

                evidence = layer2_runner._run_prepared_groups(
                    request, anchor, policy, temporary / "layer2-model-loop" / locale,
                    "simulation-no-secret", fake_model_call, simulation_only=True)
                if len(calls) != 2 * len(group_plan) or [call["role"] for call in calls] != [
                        role for _ in group_plan for role in ("astra", "sol")]:
                    raise ValueError("Simulated Astra/Sol call order changed")
                try:
                    layer2_producer.prepare_request(source, anchor, policy)
                except ValueError as exc:
                    if "Approved English Source Package" not in str(exc):
                        raise
                else:
                    raise ValueError("Formal Layer 2 accepted simulated source")
                groups = [{"translationGroupId": row["translationGroupId"],
                           "sourceUnitIds": row["sourceUnitIds"],
                           "targetText": "".join(row["targetUtterances"])}
                          for row in evidence["groups"]]
                value = {"schemaVersion": "sermon-dry-run-layer2-shadow-v1",
                         "simulationOnly": True, "status": "simulated_text",
                         "targetLocale": locale,
                         "englishSourcePackageJsonSha256": canonical_sha(source),
                         "anchorManifestJsonSha256": canonical_sha(anchor),
                         "groups": groups, "texts": fixture["translations"][locale],
                         "modelLoopEvidenceJsonSha256": canonical_sha(evidence)}
                write_json(temporary / "layer2" / f"{locale}.json", value)
                report["layers"].setdefault("layer2", {})[locale] = {
                    "status": "simulated_text", "groups": len(groups),
                    "jsonSha256": canonical_sha(value), "humanReview": "not_run",
                    "modelCalls": len(calls), "formalGate": "rejected_simulated_source"}
                return value
            translated[locale] = step(f"layer2:{locale}", make_text)

        audio = {}
        for index, locale in enumerate(LOCALES):
            def make_audio(locale=locale, index=index):
                groups = translated[locale]["groups"]
                context = {"anchor": anchor, "candidate": {"groups": groups},
                           "job": {"targetLocale": locale}, "clip_timeline_map": {
                               "anchorOffsetSeconds": 0,
                               "clipDurationSeconds": fixture["durationSeconds"]}}
                rows = [{"durationSeconds": 0.55} for _ in groups]
                schedule = layer3.schedule(context, rows, layer3.DEFAULT_POLICY)
                if schedule["status"] != "pass" or len(schedule["entries"]) != len(groups):
                    raise ValueError(f"Simulated 1x scheduling failed: {locale}")
                signals = []
                for unit_index, entry in enumerate(schedule["entries"]):
                    def make_tone():
                        tone = pcm(0.55, 330 + index * 110)
                        signals.append(tone)
                    step(f"layer3:{locale}:unit-{unit_index}", make_tone)
                path = temporary / "public/flow/media" / f"{locale}.wav"
                signal = layer3.assemble_pcm16_track(
                    schedule, signals, RATE, 1, float(fixture["durationSeconds"]))
                wav(path, signal)
                with wave.open(str(path), "rb") as handle:
                    if handle.getnframes() != round(float(fixture["durationSeconds"]) * RATE):
                        raise ValueError("Simulated audio duration changed")
                write_json(temporary / "layer3" / f"{locale}.json", {
                    "schemaVersion": "sermon-dry-run-layer3-shadow-v1", "simulationOnly": True,
                    "status": "simulated_audio", "targetLocale": locale,
                    "layer2JsonSha256": canonical_sha(translated[locale]),
                    "schedule": schedule, "audioSha256": digest(path)})
                report["layers"].setdefault("layer3", {})[locale] = {
                    "status": "simulated_audio", "schedule": "pass",
                    "audioSha256": digest(path), "durationSeconds": fixture["durationSeconds"],
                    "wholeTrackListening": "not_run"}
                return path
            audio[locale] = step(f"layer3:{locale}", make_audio)

        if fail_at and fail_at != "layer4" and not any(
                event["step"] == fail_at for event in events):
            raise ValueError(f"Failure injection point was not reached: {fail_at}")

        def make_layer4():
            public = temporary / "public/flow"
            report["layers"]["layer4"] = {"status": "preview_only",
                "formalCatalogModified": False, "releasePackageCreated": False,
                "devHttpVerification": "not_run"}
            (public / "index.html").write_text(
                render_preview(report, fixture, translated, audio), encoding="utf-8")
            if any((temporary / name).exists() for name in
                   ("public/multilingual-v3.json", "public/releases-v2")):
                raise ValueError("Simulated run created formal release files")
        step("layer4", make_layer4)
        report["status"] = "pass_simulated"
        public_report = {key: value for key, value in report.items() if key != "events"}
        public_report["events"] = events
        write_json(temporary / "public/flow/report.json", public_report)
    except Exception as exc:
        report["status"] = "failed"
        report["failure"] = str(exc)
    finally:
        report["finishedAt"] = datetime.now(timezone.utc).isoformat()
        report["publicFiles"] = [
            {"path": path.relative_to(temporary / "public").as_posix(),
             "bytes": path.stat().st_size, "sha256": digest(path)}
            for path in sorted((temporary / "public").rglob("*")) if path.is_file()
        ] if (temporary / "public").exists() else []
        write_json(temporary / "run-report.json", report)
        temporary.rename(out)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", type=Path, default=ROOT / "config/backend-four-layer-dry-run.fixture.json")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--fail-at")
    args = parser.parse_args()
    result = run(args.fixture, args.out, fail_at=args.fail_at)
    print(json.dumps({"status": result["status"], "output": str(args.out),
                      "events": len(result["events"]), "failure": result.get("failure")}, ensure_ascii=False))
    return 0 if result["status"] == "pass_simulated" else 2


if __name__ == "__main__":
    raise SystemExit(main())
