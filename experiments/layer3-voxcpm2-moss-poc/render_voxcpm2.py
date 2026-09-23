#!/usr/bin/env python3
"""Render VoxCPM2 clone and style-guided candidates."""
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


def save_audio(soundfile, path, wav, sample_rate):
    path.parent.mkdir(parents=True, exist_ok=True)
    soundfile.write(str(path), wav, sample_rate)


def install_torchaudio_compat_if_needed():
    """Provide the small torchaudio surface used by VoxCPM2 on the NGC ARM64 image."""
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

    def loudness(audio, sample_rate, *unused_args, **unused_kwargs):
        del sample_rate
        rms = torch.sqrt(torch.mean(audio.float() ** 2).clamp_min(1e-12))
        return 20 * torch.log10(rms)

    def gain(audio, gain_db):
        return audio * (10 ** (gain_db / 20))

    module.load = load
    module.save = save
    operations.resample = resample
    operations.loudness = loudness
    operations.gain = gain
    module.functional = operations
    sys.modules["torchaudio"] = module
    sys.modules["torchaudio.functional"] = operations
    return module.__version__


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--model-path", type=Path, required=True)
    parser.add_argument("--reference", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--timesteps", type=int, default=10)
    args = parser.parse_args()
    helper = helpers()
    plan = helper.load_plan(args.plan)
    if helper.sha256(args.reference) != plan["voice"]["referenceAudioSha256"]:
        raise ValueError("Eric reference audio changed")

    audio_backend = install_torchaudio_compat_if_needed()
    import numpy as np
    import soundfile as sf
    import torch
    from voxcpm import VoxCPM
    model = VoxCPM.from_pretrained(str(args.model_path), load_denoiser=False)
    results = []

    def render(sample_id, variant, text, path):
        started = time.monotonic()
        np.random.seed(args.seed)
        torch.manual_seed(args.seed)
        wav = model.generate(
            text=text, reference_wav_path=str(args.reference), cfg_value=2.0,
            inference_timesteps=args.timesteps,
        )
        save_audio(sf, path, wav, model.tts_model.sample_rate)
        row = {
            "sampleId": sample_id, "variant": variant, "text": text,
            "audio": str(path), "audioSha256": helper.sha256(path),
            "elapsedSeconds": time.monotonic() - started,
            "sampleRate": model.tts_model.sample_rate, "seed": args.seed,
            "inferenceTimesteps": args.timesteps,
        }
        results.append(row)
        print(json.dumps(row, ensure_ascii=False), flush=True)

    for unit in plan["primaryUnits"]:
        root = args.out / unit["sourceUnitId"]
        render(unit["sourceUnitId"], "voxcpm2_clone", unit["targetText"], root / "clone.wav")
        controlled = f'({unit["styleInstruction"]}){unit["targetText"]}'
        render(unit["sourceUnitId"], "voxcpm2_style_guided", controlled, root / "style_guided.wav")
    for smoke in plan["multilingualSmoke"]:
        render(smoke["sampleId"], "voxcpm2_clone", smoke["targetText"], args.out / "smoke" / f'{smoke["targetLocale"]}.wav')
    helper.write_json(args.out / "manifest.json", {
        "schemaVersion": "sermon-layer3-voxcpm2-render-manifest-v1", "modelPath": str(args.model_path),
        "referenceAudioSha256": helper.sha256(args.reference), "audioBackend": audio_backend, "results": results,
        "productionEligible": False, "humanApproval": False,
    })


if __name__ == "__main__":
    main()
