#!/usr/bin/env python3
"""Build a deterministic blind A/B page for the long Chinese comparison."""
import argparse
import hashlib
import html
import importlib.util
import json
from pathlib import Path


def load_module(filename, name):
    path = Path(__file__).with_name(filename)
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--run-dir", type=Path, required=True)
    args = parser.parse_args()
    renderer = load_module("render_long_ab.py", "long_ab_renderer")
    helper = load_module("poc.py", "long_ab_build_helpers")
    plan = renderer.load_plan(args.plan)
    candidates = []
    for engine in ("qwen", "voxcpm2"):
        path = args.run_dir / f"{engine}.wav"
        manifest_path = args.run_dir / f"{engine}-manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        audio_hash = helper.sha256(path)
        if (
            manifest.get("schemaVersion") != "sermon-layer3-qwen-voxcpm2-long-ab-render-v1"
            or manifest.get("sampleId") != plan["passage"]["sampleId"]
            or manifest.get("engine") != engine
            or manifest.get("textSha256") != plan["passage"]["textSha256"]
            or manifest.get("audioSha256") != audio_hash
            or Path(manifest.get("audio", "")).name != path.name
            or manifest.get("productionEligible") is not False
            or manifest.get("humanApproval") is not False
        ):
            raise ValueError(f"render manifest does not match plan or audio: {manifest_path}")
        media = helper.probe_audio(path)
        candidates.append({
            "engine": engine, "audio": path.name, "audioSha256": audio_hash, **media,
        })
    blind = []
    for index, row in enumerate(sorted(candidates, key=lambda value: value["audioSha256"]), start=1):
        blind.append({"sampleNumber": index, **row, "humanListening": "pending"})
    receipt = {
        "schemaVersion": "sermon-layer3-qwen-voxcpm2-long-ab-v1",
        "sampleId": plan["passage"]["sampleId"], "text": plan["passage"]["text"],
        "textSha256": plan["passage"]["textSha256"], "blindOrder": "ascending audio SHA-256",
        "candidates": blind, "productionEligible": False, "humanApproval": False,
    }
    helper.write_json(args.run_dir / "blind-map.json", receipt)
    sections = []
    for row in blind:
        sections.append(
            f'<section><h2>样本 {row["sampleNumber"]}</h2>'
            f'<audio controls preload="metadata" src="{html.escape(row["audio"])}"></audio>'
            f'<p>时长 {row["durationSeconds"]:.2f} 秒。请分别记录：音色、重音、停顿、长段稳定性和整体偏好（1–5）。</p></section>'
        )
    page = f'''<!doctype html><meta charset="utf-8"><title>Qwen / VoxCPM2 中文长段 A/B</title>
<style>body{{font:16px system-ui;max-width:900px;margin:32px auto;padding:0 20px;color:#172019}}section{{border:1px solid #ccd5cc;border-radius:14px;padding:18px;margin:18px 0;background:#f6f8f6}}audio{{width:100%}}blockquote{{line-height:1.9;background:#eef3ee;padding:16px;border-radius:10px}}</style>
<h1>Qwen / VoxCPM2 中文长段盲听</h1><p>两个样本使用完全相同文本；顺序按音频哈希固定盲化。仅用于 Layer 3 shadow POC。</p>
<blockquote>{html.escape(plan["passage"]["text"])}</blockquote>{''.join(sections)}'''
    (args.run_dir / "listening.html").write_text(page, encoding="utf-8")
    print(json.dumps({"status": "written", "candidates": len(blind)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
