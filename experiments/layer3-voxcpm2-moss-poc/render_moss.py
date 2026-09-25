#!/usr/bin/env python3
"""Render MOSS-TTS v1.5 clone, duration and explicit-pause candidates."""
import argparse
import importlib.util
import json
from pathlib import Path
import sys
import time
import types


def helpers():
    path = Path(__file__).with_name("poc.py")
    spec = importlib.util.spec_from_file_location("layer3_multimodel_helpers", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def install_torchaudio_compat_if_needed():
    try:
        import torchaudio  # noqa: F401
        return "native"
    except Exception:
        for name in [name for name in sys.modules if name == "torchaudio" or name.startswith("torchaudio.")]:
            sys.modules.pop(name, None)
    import importlib.machinery
    import numpy as np
    import soundfile as sf
    import torch
    import torch.nn.functional as functional
    module = types.ModuleType("torchaudio")
    operations = types.ModuleType("torchaudio.functional")
    module.__spec__ = importlib.machinery.ModuleSpec("torchaudio", loader=None)
    operations.__spec__ = importlib.machinery.ModuleSpec("torchaudio.functional", loader=None)
    module.__version__ = "soundfile-torch-compat-v1"

    def load(path, *unused_args, **unused_kwargs):
        audio, sample_rate = sf.read(str(path), always_2d=True, dtype="float32")
        return torch.from_numpy(audio.T.copy()), sample_rate

    def save(path, audio, sample_rate, *unused_args, **unused_kwargs):
        array = audio.detach().float().cpu().numpy() if hasattr(audio, "detach") else np.asarray(audio)
        if array.ndim == 2:
            array = array.T
        sf.write(str(path), array, sample_rate)

    def resample(audio, original_rate, new_rate, *unused_args, **unused_kwargs):
        if original_rate == new_rate:
            return audio
        length = round(audio.shape[-1] * new_rate / original_rate)
        return functional.interpolate(audio.unsqueeze(0), size=length, mode="linear", align_corners=False).squeeze(0)

    module.load = load
    module.save = save
    operations.resample = resample
    module.functional = operations
    sys.modules["torchaudio"] = module
    sys.modules["torchaudio.functional"] = operations
    return module.__version__


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--model-path", type=Path, required=True)
    parser.add_argument("--codec-path", type=Path, required=True)
    parser.add_argument("--reference", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    helper = helpers()
    plan = helper.load_plan(args.plan)
    if helper.sha256(args.reference) != plan["voice"]["referenceAudioSha256"]:
        raise ValueError("Eric reference audio changed")

    audio_backend = install_torchaudio_compat_if_needed()
    import numpy as np
    import soundfile as sf
    import torch
    from transformers import AutoModel, AutoProcessor
    torch.manual_seed(args.seed)
    torch.backends.cuda.enable_cudnn_sdp(False)
    torch.backends.cuda.enable_flash_sdp(True)
    torch.backends.cuda.enable_mem_efficient_sdp(True)
    torch.backends.cuda.enable_math_sdp(True)
    device = "cuda" if torch.cuda.is_available() else "cpu"
    dtype = torch.bfloat16 if device == "cuda" else torch.float32
    attention = "sdpa" if device == "cuda" else "eager"
    processor = AutoProcessor.from_pretrained(
        str(args.model_path), trust_remote_code=True,
        codec_path=str(args.codec_path),
    )
    if hasattr(processor, "audio_tokenizer"):
        processor.audio_tokenizer = processor.audio_tokenizer.to(device)
    model = AutoModel.from_pretrained(
        str(args.model_path), trust_remote_code=True, local_files_only=True,
        attn_implementation=attention, torch_dtype=dtype,
    ).to(device).eval()
    results = []

    def render(sample_id, variant, text, language, path, tokens=None):
        kwargs = {"text": text, "reference": [str(args.reference)], "language": language}
        if tokens is not None:
            kwargs["tokens"] = tokens
        conversation = [[processor.build_user_message(**kwargs)]]
        batch = processor(conversation, mode="generation")
        started = time.monotonic()
        with torch.inference_mode():
            outputs = model.generate(
                input_ids=batch["input_ids"].to(device), attention_mask=batch["attention_mask"].to(device),
                max_new_tokens=4096,
            )
        messages = [message for message in processor.decode(outputs) if message is not None]
        if len(messages) != 1:
            raise RuntimeError(f"expected one decoded message, got {len(messages)}")
        audio = messages[0].audio_codes_list[0]
        if hasattr(audio, "detach"):
            audio = audio.detach().float().cpu().numpy()
        audio = np.asarray(audio)
        if audio.ndim == 2 and audio.shape[0] <= 2:
            audio = audio.T
        sample_rate = int(processor.model_config.sampling_rate)
        path.parent.mkdir(parents=True, exist_ok=True)
        sf.write(str(path), audio, sample_rate)
        row = {
            "sampleId": sample_id, "variant": variant, "text": text, "language": language,
            "tokens": tokens, "audio": str(path), "audioSha256": helper.sha256(path),
            "elapsedSeconds": time.monotonic() - started, "sampleRate": sample_rate, "seed": args.seed,
        }
        results.append(row)
        print(json.dumps(row, ensure_ascii=False), flush=True)

    for unit in plan["primaryUnits"]:
        root = args.out / unit["sourceUnitId"]
        render(unit["sourceUnitId"], "moss_clone", unit["targetText"], unit["language"], root / "clone.wav")
        render(unit["sourceUnitId"], "moss_duration_control", unit["targetText"], unit["language"], root / "duration_control.wav", round(unit["targetDurationSeconds"] * 12.5))
    pause = plan["pauseProbe"]
    before_duration = next(unit["targetDurationSeconds"] for unit in plan["primaryUnits"] if unit["sourceUnitId"] == pause["beforeSourceUnitId"])
    pause_text = f'{pause["beforeText"]} [pause {pause["pauseSeconds"]:.2f}s] {pause["afterText"]}'
    total_duration = before_duration + pause["pauseSeconds"] + pause["afterDurationSeconds"]
    render(pause["sampleId"], "moss_explicit_pause", pause_text, pause["language"], args.out / pause["sampleId"] / "explicit_pause.wav", round(total_duration * 12.5))
    for smoke in plan["multilingualSmoke"]:
        render(smoke["sampleId"], "moss_clone", smoke["targetText"], smoke["language"], args.out / "smoke" / f'{smoke["targetLocale"]}.wav')
    helper.write_json(args.out / "manifest.json", {
        "schemaVersion": "sermon-layer3-moss-v1.5-render-manifest-v1", "modelPath": str(args.model_path),
        "codecPath": str(args.codec_path), "referenceAudioSha256": helper.sha256(args.reference),
        "audioBackend": audio_backend, "results": results,
        "productionEligible": False, "humanApproval": False,
    })


if __name__ == "__main__":
    main()
