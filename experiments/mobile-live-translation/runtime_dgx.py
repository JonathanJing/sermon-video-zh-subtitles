#!/usr/bin/env python3
"""Bounded, offline DGX merged-BF16 MT diagnostic on frozen JSONL inputs.

Run inside the existing sermon-milmmt PyTorch image with read-only model/input
mounts and a new output directory. This does not start a server or alter services.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import re
import statistics
import time
import traceback


ADAPTER_SHA256 = "16ef2fb03cd4468a4d0288b450905e80fc90299adb983d0d3338384975254bba"
EOS_IDS = [1, 106]
CHINESE = re.compile("[\u3400-\u9fff]")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def text_sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def official_prompt(source: str) -> str:
    return f"Translate this from English to Chinese (Simplified):\nEnglish: {source}\nChinese (Simplified):"


def read_samples(path: Path, expected_sha256: str) -> list[dict]:
    if sha256(path) != expected_sha256:
        raise ValueError("Frozen input SHA-256 mismatch")
    samples = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    if len(samples) != 12 or len({row["id"] for row in samples}) != 12:
        raise ValueError("Expected exactly 12 unique frozen diagnostic inputs")
    for row in samples:
        if row.get("schemaVersion") != "mobile-live-translation-runtime-sample-v1":
            raise ValueError("Unsupported sample schema")
        if row.get("sourceEn") != row["source"] or row["prompt"] != official_prompt(row["source"]):
            raise ValueError("Frozen source/prompt mismatch")
        for field, hash_field in (("source", "sourceTextSha256"), ("prompt", "promptSha256")):
            if text_sha256(row[field]) != row[hash_field]:
                raise ValueError(f"Frozen {field} hash mismatch")
        if row.get("releaseEligible") is not False or row.get("humanApprovalClaimed") is not False:
            raise ValueError("Only explicitly unqualified diagnostic samples are accepted")
    return samples


def model_manifest(model_path: Path) -> dict:
    receipt_path = model_path / "merge-receipt.json"
    receipt = json.loads(receipt_path.read_text())
    if receipt["adapterSha256"] != ADAPTER_SHA256 or receipt["dtype"] != "bfloat16":
        raise ValueError("Expected v4.1 merged BF16 identity")
    files = []
    for path in sorted(model_path.iterdir()):
        if path.is_file() and path.suffix in (".json", ".jinja", ".model", ".safetensors"):
            files.append({"name": path.name, "bytes": path.stat().st_size, "sha256": sha256(path)})
    by_name = {entry["name"]: entry for entry in files}
    for expected in receipt["weightFiles"]:
        if by_name.get(expected["name"]) != expected:
            raise ValueError("Merged weight receipt mismatch: " + expected["name"])
    return {"path": str(model_path), "identity": "milmmt-sermon-v41-experimental-merged-bf16",
            "mergeReceiptSha256": sha256(receipt_path), "adapterSha256": ADAPTER_SHA256, "files": files}


class TokenClock:
    """HF CPU token callback plus cumulative-prefix decode; no word buffering."""

    def __init__(self, tokenizer, t0: float):
        self.tokenizer = tokenizer
        self.t0 = t0
        self.prompt_pending = True
        self.ids = []
        self.first_token_ms = self.first_text_ms = self.first_chinese_ms = None
        self.ended = False

    def put(self, value):
        if self.prompt_pending:
            self.prompt_pending = False
            return
        self.ids.extend(value.reshape(-1).tolist())
        if self.first_token_ms is None:
            self.first_token_ms = (time.perf_counter() - self.t0) * 1000
        if self.first_text_ms is None or self.first_chinese_ms is None:
            visible = self.tokenizer.decode(self.ids, skip_special_tokens=True,
                                            clean_up_tokenization_spaces=False).replace("\ufffd", "")
            observed = (time.perf_counter() - self.t0) * 1000
            if visible.strip() and self.first_text_ms is None:
                self.first_text_ms = observed
            if CHINESE.search(visible) and self.first_chinese_ms is None:
                self.first_chinese_ms = observed

    def end(self):
        self.ended = True


def percentile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    rank = (len(ordered) - 1) * q
    low = int(rank)
    high = min(low + 1, len(ordered) - 1)
    return ordered[low] + (ordered[high] - ordered[low]) * (rank - low)


def summarize(rows: list[dict]) -> dict:
    summary = {}
    for stratum in ("all", "short", "natural"):
        subset = [r for r in rows if r["phase"] == "measured" and (stratum == "all" or r["stratum"] == stratum)]
        sample_ids = sorted({row["id"] for row in subset})
        metrics = {}
        for metric in ("firstTokenMs", "firstChineseMs", "fullEosMs", "requestCompleteMs", "tokenizationMs", "inputPrepareMs", "generationMs"):
            per_sample = []
            for sample_id in sample_ids:
                measurements = [row["timings"][metric] for row in subset
                                if row["id"] == sample_id and row["status"] == "completed"
                                and row["timings"].get(metric) is not None]
                if len(measurements) == 3:
                    per_sample.append(statistics.median(measurements))
            metrics[metric] = {"qualifiedUniqueSamples": len(per_sample), "p50": percentile(per_sample, .5),
                               "p95": percentile(per_sample, .95)}
        summary[stratum] = {"runs": len(subset), "uniqueSamples": len(sample_ids),
                            "failedOrIncompleteRuns": sum(r["status"] != "completed" for r in subset), "metrics": metrics}
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--samples", type=Path, required=True)
    parser.add_argument("--samples-sha256", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--image-id", required=True, help="Verified immutable Docker image ID recorded by launcher")
    args = parser.parse_args()
    if args.output_dir.exists():
        raise FileExistsError("Preserve prior evidence; choose a new output directory")
    args.output_dir.mkdir(parents=True)
    report_path = args.output_dir / "run-report.json"
    report = {"schemaVersion": "mobile-live-translation-dgx-runtime-v1", "status": "running",
              "releaseEligible": False, "model": None, "scriptSha256": sha256(Path(__file__)),
              "inputSha256": args.samples_sha256, "imageId": args.image_id,
              "settings": {"repeats": 3, "warmupIndices": [0, 6], "order": ["forward", "reverse", "forward"],
                           "freshKvPerRequest": True, "maxNewTokens": 512, "doSample": False, "numBeams": 1,
                           "eosIds": EOS_IDS, "addSpecialTokens": False, "dtype": "bfloat16"},
              "timingContract": {"origin": "Before official_prompt(source) and tokenization; excludes queue/network/ASR/audio.",
                  "firstTokenMs": "First generated token IDs CPU-visible in HF streamer callback; includes inputPrepareMs.",
                  "firstChineseMs": "First U+3400-U+9FFF after HF cumulative-prefix decode; includes inputPrepareMs.",
                  "fullEosMs": "EOS-terminated generate return, final detokenization and final CUDA synchronization, from origin.",
                  "tokenizationMs": "Tokenizer call only; prompt construction is separately recorded.",
                  "inputPrepareMs": "Inclusive origin-to-generate interval: prompt, tokenization, device copy/materialization and CUDA sync.",
                  "generationMs": "Generate invocation through final detokenization and final CUDA sync.",
                  "modelLoadMs": "Tokenizer plus model from_pretrained and CUDA synchronization; hashing/import time excluded."},
              "limitations": ["HF cumulative-prefix decode differs from MLX native lookahead emission.",
                  "Observer callback/decode overhead is included. Warm batch=1 model diagnostic; no phone or network path.",
                  "BF16 CUDA and MLX Q5 differ in runtime, kernels and quantization; this is a deployment comparison.",
                  "Repeat medians per input, then descriptive percentiles; 6 inputs per stratum do not establish a service SLO."]}

    def save():
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")

    save()
    rows = []
    try:
        started = time.perf_counter()
        samples = read_samples(args.samples, args.samples_sha256)
        report["model"] = model_manifest(args.model)
        report["verificationMs"] = (time.perf_counter() - started) * 1000
        os.environ["HF_HUB_OFFLINE"] = "1"
        os.environ["TRANSFORMERS_OFFLINE"] = "1"
        import torch
        from transformers import AutoModelForImageTextToText, AutoTokenizer
        report["environment"] = {"platform": platform.platform(), "python": platform.python_version(),
            "gpu": torch.cuda.get_device_name(0), "packages": {name: importlib.metadata.version(name)
                for name in ("torch", "transformers", "safetensors", "peft")}}
        torch.manual_seed(42)
        load_started = time.perf_counter()
        tokenizer = AutoTokenizer.from_pretrained(args.model, local_files_only=True, trust_remote_code=False)
        model = AutoModelForImageTextToText.from_pretrained(args.model, dtype=torch.bfloat16,
            device_map="cuda:0", local_files_only=True, trust_remote_code=False).eval()
        torch.cuda.synchronize()
        report["modelLoadMs"] = (time.perf_counter() - load_started) * 1000
        if tokenizer.eos_token_id != 1 or tokenizer.convert_tokens_to_ids("<end_of_turn>") != 106:
            raise ValueError("Frozen tokenizer EOS identities changed")
        save()
        print(json.dumps({"event": "model_ready", "modelLoadMs": report["modelLoadMs"]}), flush=True)

        def generate(sample: dict, phase: str, repeat: int, index: int) -> dict:
            row = {"schemaVersion": "mobile-live-translation-runtime-row-v1", "id": sample["id"],
                "stratum": sample["stratum"], "phase": phase, "repeat": repeat, "index": index,
                "source": sample["source"], "sourceTextSha256": sample["sourceTextSha256"],
                "promptSha256": sample["promptSha256"], "status": "running", "timings": {}}
            t0 = time.perf_counter()
            clock = TokenClock(tokenizer, t0)
            t_gen = None
            try:
                prompt = official_prompt(sample["source"])
                t_tokenize = time.perf_counter()
                encoded_cpu = tokenizer(prompt, return_tensors="pt", add_special_tokens=False)
                t_device = time.perf_counter()
                row["inputTokenIds"] = encoded_cpu["input_ids"][0].tolist()
                row["inputTokens"] = len(row["inputTokenIds"])
                encoded = {key: value.to("cuda:0") for key, value in encoded_cpu.items()}
                torch.cuda.synchronize()
                t_gen = time.perf_counter()
                with torch.inference_mode():
                    output = model.generate(**encoded, do_sample=False, num_beams=1, max_new_tokens=512,
                        repetition_penalty=1.0, pad_token_id=tokenizer.pad_token_id, eos_token_id=EOS_IDS,
                        use_cache=True, streamer=clock)
                ids = output[0, row["inputTokens"]:].detach().cpu().tolist()
                raw = tokenizer.decode(ids, skip_special_tokens=False, clean_up_tokenization_spaces=False)
                text = tokenizer.decode(ids, skip_special_tokens=True, clean_up_tokenization_spaces=False).strip()
                torch.cuda.synchronize()
                completed = time.perf_counter()
                if ids != clock.ids or not clock.ended:
                    raise ValueError("Streamer token coverage or close mismatch")
                eos_terminated = bool(ids) and ids[-1] in EOS_IDS
                row.update({"raw": raw, "text": text, "generatedTokenIds": ids, "generatedTokens": len(ids),
                    "stopReason": "eos" if eos_terminated else "max_tokens_or_missing_eos",
                    "eosTerminated": eos_terminated, "streamerCoverageExact": True,
                    "status": "completed" if eos_terminated and clock.first_chinese_ms is not None else "incomplete"})
                row["timings"] = {"promptMs": (t_tokenize-t0)*1000, "tokenizationMs": (t_device-t_tokenize)*1000,
                    "deviceMaterializeMs": (t_gen-t_device)*1000, "inputPrepareMs": (t_gen-t0)*1000,
                    "generationMs": (completed-t_gen)*1000, "firstTokenMs": clock.first_token_ms,
                    "firstTextMs": clock.first_text_ms, "firstChineseMs": clock.first_chinese_ms,
                    "fullEosMs": (completed-t0)*1000 if eos_terminated else None,
                    "requestCompleteMs": (completed-t0)*1000}
            except Exception as exc:
                row.update({"status": "failed", "stopReason": "error", "generatedTokenIds": clock.ids,
                    "generatedTokens": len(clock.ids), "error": f"{type(exc).__name__}: {exc}",
                    "raw": tokenizer.decode(clock.ids, skip_special_tokens=False),
                    "text": tokenizer.decode(clock.ids, skip_special_tokens=True)})
                row["timings"].update({"firstTokenMs": clock.first_token_ms, "firstTextMs": clock.first_text_ms,
                    "firstChineseMs": clock.first_chinese_ms, "fullEosMs": None,
                    "requestCompleteMs": (time.perf_counter()-t0)*1000})
            return row

        with (args.output_dir / "measurements.jsonl").open("x") as handle:
            schedule = [("warmup", -1, i, samples[i]) for i in (0, 6)]
            for repeat in range(3):
                ordered = list(enumerate(samples))
                if repeat == 1:
                    ordered.reverse()
                schedule.extend(("measured", repeat, i, sample) for i, sample in ordered)
            for phase, repeat, index, sample in schedule:
                row = generate(sample, phase, repeat, index)
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")
                handle.flush()
                os.fsync(handle.fileno())
                rows.append(row)
                print(json.dumps({"event": "request_complete", "phase": phase, "repeat": repeat, "index": index,
                    "status": row["status"], "generatedTokens": row["generatedTokens"], "timings": row["timings"]}), flush=True)
        report["summary"] = summarize(rows)
        report["measurementRows"] = len(rows)
        report["measurementsSha256"] = sha256(args.output_dir / "measurements.jsonl")
        report["status"] = "completed_diagnostic_not_release" if all(r["status"] == "completed" for r in rows) else "failed_partial_not_qualified"
        if report["status"] != "completed_diagnostic_not_release":
            raise RuntimeError("One or more requests failed or lacked EOS/Chinese output; all rows preserved")
    except Exception as exc:
        report["status"] = "failed_partial_not_qualified"
        report["error"] = f"{type(exc).__name__}: {exc}"
        report["traceback"] = traceback.format_exc()
        raise
    finally:
        save()


if __name__ == "__main__":
    main()
