#!/usr/bin/env python3
"""Render AuK direct-TTS and Qwen-postprocessed Layer 3 challengers."""
import argparse
import hashlib
import importlib.machinery
import json
from pathlib import Path
import sys
import time
import types


def install_torchaudio_compat_if_missing():
    """Provide the four inference-only APIs AuK uses on NGC ARM64 images.

    The DGX GB10 NGC image ships a CUDA-enabled development PyTorch build but
    no ABI-matched torchaudio wheel. This fallback keeps the official AuK model
    code unchanged and delegates WAV I/O to soundfile; it is not used when a
    real torchaudio installation is available.
    """
    try:
        import torchaudio  # noqa: F401
        return "torchaudio"
    except ModuleNotFoundError:
        import soundfile as sf
        import torch
        import torch.nn.functional as functional

        module = types.ModuleType("torchaudio")
        module.__spec__ = importlib.machinery.ModuleSpec("torchaudio", loader=None)
        module.__version__ = "0.0.compat"

        def load(path):
            audio, rate = sf.read(str(path), dtype="float32", always_2d=True)
            return torch.from_numpy(audio.T.copy()), rate

        def info(path):
            details = sf.info(str(path))
            return types.SimpleNamespace(sample_rate=details.samplerate, num_frames=details.frames,
                                         num_channels=details.channels)

        def save(path, audio, sample_rate, **_kwargs):
            array = audio.detach().to(device="cpu", dtype=torch.float32).numpy()
            sf.write(str(path), array.T, sample_rate, subtype="PCM_16")

        class Resample:
            def __init__(self, original_rate, new_rate):
                self.original_rate = original_rate
                self.new_rate = new_rate

            def __call__(self, audio):
                length = round(audio.shape[-1] * self.new_rate / self.original_rate)
                return functional.interpolate(audio.unsqueeze(0), size=length, mode="linear", align_corners=False).squeeze(0)

        module.load = load
        module.info = info
        module.save = save
        module.transforms = types.SimpleNamespace(Resample=Resample)
        sys.modules["torchaudio"] = module
        return "soundfile_torch_compat_v1"


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def audio_seconds(path):
    import soundfile as sf
    info = sf.info(str(path))
    return info.frames / info.samplerate


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--qwen-path", type=Path, required=True)
    parser.add_argument("--reference", type=Path, required=True)
    parser.add_argument("--qwen-dir", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--cpu-offload", action="store_true")
    args = parser.parse_args()
    plan = json.loads(args.plan.read_text(encoding="utf-8"))
    if plan.get("schemaVersion") != "sermon-layer3-qwen-auk-poc-plan-v1" or plan.get("humanApproval") is not False:
        raise ValueError("invalid or promoted POC plan")
    if sha256(args.reference) != plan["voice"]["referenceAudioSha256"]:
        raise ValueError("Eric reference audio changed")

    audio_backend = install_torchaudio_compat_if_missing()
    from auk.infer.infer_auk import AukInfer, save_audio
    engine = AukInfer(str(args.config), str(args.checkpoint), qwen_path=str(args.qwen_path), cpu_offload=args.cpu_offload)
    args.out.mkdir(parents=True, exist_ok=True)
    identity = {
        "schemaVersion": "sermon-layer3-auk-render-identity-v1",
        "planSha256": sha256(args.plan),
        "aukConfigSha256": sha256(args.config),
        "aukCheckpointSha256": sha256(args.checkpoint),
        "qwenEncoderPath": str(args.qwen_path),
        "referenceAudioSha256": sha256(args.reference),
        "audioBackend": audio_backend,
        "cpuOffload": args.cpu_offload,
        "productionEligible": False,
        "humanApproval": False,
    }
    write_json(args.out / "identity.json", identity)
    receipts = []
    for unit in plan["units"]:
        if not unit.get("challenger"):
            continue
        unit_dir = args.out / unit["sourceUnitId"]
        unit_dir.mkdir(parents=True, exist_ok=True)
        target = unit["targetDurationSeconds"]
        direct_instruction = f'Say the following with the same voice: "{unit["targetText"]}"'
        qwen_path = args.qwen_dir / f'{unit["sourceUnitId"]}.wav'
        if not qwen_path.exists():
            raise ValueError(f"missing Qwen unit for AuK editing: {qwen_path}")
        qwen_duration = audio_seconds(qwen_path)
        speed = qwen_duration / target
        edit_instruction = (
            f"Adjust the speech speed to {speed:.2f}x while preserving the speaker and Korean content. "
            + unit["prosodyInstruction"]
        )
        variants = [
            ("auk_zero_shot", direct_instruction, args.reference),
            ("qwen_then_auk_speed_emphasis", edit_instruction, qwen_path),
        ]
        for name, instruction, input_audio in variants:
            wav_path = unit_dir / f"{name}.wav"
            receipt_path = unit_dir / f"{name}.json"
            if receipt_path.exists():
                receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
                if receipt.get("identity") != identity or receipt.get("audioSha256") != sha256(wav_path):
                    raise ValueError(f"stale cached AuK output: {wav_path}")
                receipts.append(receipt)
                continue
            if wav_path.exists():
                raise ValueError(f"unreceipted AuK output preserved: {wav_path}")
            messages = [{"role": "user", "content": [
                {"type": "text", "text": instruction},
                {"type": "audio", "audio": str(input_audio)},
            ]}]
            started = time.monotonic()
            audio, rate = engine.generate(messages, gen_seconds=target)
            save_audio(audio, rate, str(wav_path))
            receipt = {
                "schemaVersion": "sermon-layer3-auk-unit-receipt-v1",
                "identity": identity,
                "sourceUnitId": unit["sourceUnitId"],
                "variant": name,
                "instruction": instruction,
                "instructionSha256": hashlib.sha256(instruction.encode("utf-8")).hexdigest(),
                "inputAudioSha256": sha256(input_audio),
                "targetDurationSeconds": target,
                "requestedSpeedFactor": speed if name.startswith("qwen_then") else None,
                "audioSha256": sha256(wav_path),
                "sampleRate": rate,
                "durationSeconds": audio_seconds(wav_path),
                "generationSeconds": time.monotonic() - started,
                "fullDecode": "pending_external_check",
                "humanListeningStatus": "pending",
            }
            write_json(receipt_path, receipt)
            receipts.append(receipt)
            print(json.dumps({"sourceUnitId": unit["sourceUnitId"], "variant": name, "durationSeconds": receipt["durationSeconds"]}), flush=True)
    write_json(args.out / "manifest.json", {
        "schemaVersion": "sermon-layer3-auk-render-manifest-v1",
        "identity": identity,
        "status": "generated_waveforms",
        "receipts": receipts,
        "productionEligible": False,
        "humanApproval": False,
    })


if __name__ == "__main__":
    main()
