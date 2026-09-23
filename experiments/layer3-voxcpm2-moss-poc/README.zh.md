# Layer 3：VoxCPM2 / MOSS-TTS v1.5 POC

状态：独立 shadow 实验。`productionEligible=false`、`humanApproval=false`；不生成正式 `Target-Language Audio Package`，不改变 Layer 2 的 `machine_review_pass_human_review_pending`。

## 冻结问题

根据 2026-09-22 盲听反馈，本 POC 的主观质量测评改用简体中文。它沿用 Qwen/AuK 实验的 Eric 参考音频、`block-59-u001` / `block-59-u005`、目标时长和机器筛查，回答：

1. **中文直接克隆**：VoxCPM2 与 MOSS-TTS v1.5 是否能在内容完整性、Eric 音色和自然度上挑战 Qwen SFT。
2. **韵律和时序控制**：VoxCPM2 风格/语速提示、MOSS token-level duration 与 `[pause 1.45s]` 是否可靠。
3. **四目标语言 smoke**：同一 `block-59-u001` 的 `zh-Hans`、`ko`、`es`、`vi` Layer 2 候选是否都能完成克隆、解码、ASR 和 speaker screen。

MOSS 使用官方推荐的 8B Delay v1.5，而不是 Local Transformer v1.5。VoxCPM2 使用官方 2B checkpoint。所有文本和参考 hash 由 [plan.json](./plan.json) 冻结。

## 候选矩阵

| 范围 | 候选 |
|---|---|
| 中文 u001/u005 | `qwen_sft_unit`, `voxcpm2_clone`, `voxcpm2_style_guided`, `moss_clone`, `moss_duration_control` |
| 显式停顿 | `u005 + [pause 1.45s] + u006` 的 `moss_explicit_pause` |
| 四目标语言 | 每个 locale 的 `voxcpm2_clone`, `moss_clone` |

共 19 个音频候选。时长、停顿和风格控制只属于 shadow POC；它们不满足当前正式 Layer 3 `natural_no_time_stretch` 合同。

## 运行入口

```bash
python experiments/layer3-voxcpm2-moss-poc/poc.py validate \
  --plan experiments/layer3-voxcpm2-moss-poc/plan.json

python experiments/layer3-voxcpm2-moss-poc/render_voxcpm2.py \
  --plan experiments/layer3-voxcpm2-moss-poc/plan.json \
  --model-path /path/to/VoxCPM2 --reference /path/to/eric-reference.wav \
  --out /path/to/run/voxcpm2

python experiments/layer3-voxcpm2-moss-poc/render_qwen_baseline.py \
  --plan experiments/layer3-voxcpm2-moss-poc/plan.json \
  --checkpoint /path/to/eric/checkpoint --out /path/to/run/baseline/qwen

python experiments/layer3-voxcpm2-moss-poc/render_moss.py \
  --plan experiments/layer3-voxcpm2-moss-poc/plan.json \
  --model-path /path/to/MOSS-TTS-v1.5 --codec-path /path/to/MOSS-Audio-Tokenizer \
  --reference /path/to/eric-reference.wav \
  --out /path/to/run/moss
```

随后运行 `screen_content.py`、`speaker_similarity.py`、`poc.py evaluate` 和 `poc.py listening-page`。机器筛查不会授予人工通过；盲听与 forced alignment 仍是独立门槛。

2026-09-22 的实际 DGX 结果见 [RESULTS-2026-09-22.zh.md](./RESULTS-2026-09-22.zh.md)。

## Qwen / VoxCPM2 中文长段 A/B

后续盲听使用 [long-ab-plan.json](./long-ab-plan.json) 冻结同一段合成中文评测文本。`render_long_ab.py` 分别调用 Eric Qwen SFT 与 VoxCPM2 direct clone；`screen_long_ab.py` 做内容完整性筛查，`build_long_ab.py` 按音频 SHA-256 固定盲化顺序。它只评估长段音色、重音、自然停顿和稳定性，不是讲章翻译或正式 Layer 3 产物。

人耳结果和当前模型决策已写入 [RESULTS-2026-09-22.zh.md](./RESULTS-2026-09-22.zh.md)：长段样本 2（Eric Qwen SFT）获整体偏好，当前中文生成继续使用 Qwen3-TTS SFT。

官方接口依据：[VoxCPM2](https://github.com/OpenBMB/VoxCPM)、[MOSS-TTS v1.5 model card](https://github.com/OpenMOSS/MOSS-TTS/blob/main/docs/moss_tts_model_card.md)。

## 验证

```bash
.venv/bin/python -m unittest experiments/layer3-voxcpm2-moss-poc/test_poc.py -v
git diff --check
```
