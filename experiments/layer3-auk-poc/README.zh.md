# Layer 3：Qwen3-TTS / Tencent AuK 双维度 POC

状态：独立 shadow 实验。`productionEligible=false`、`humanApproval=false`。本目录不生成正式 `Target-Language Audio Package`，也不改变上游韩语候选的 `machine_review_pass_human_review_pending` 状态。

2026-09-22 的真实 DGX 结果见 [结果报告](./RESULTS-2026-09-22.zh.md)：AuK 时长条件命中，但 direct TTS 与组合后处理都出现韩语内容退化，当前不注册 adapter。

## 问题与冻结变量

本 POC 不把 AuK 直接注册成生产 adapter，而是分别回答两个问题：

1. **直接生成能力**：同一韩文、同一 Eric 原声参考、同一目标时长下，AuK zero-shot 是否优于 Eric Qwen SFT 单元生成。
2. **韵律后处理能力**：以 Eric Qwen SFT 单元音频为输入，AuK 的速度／强调编辑能否更接近目标时长，同时保留内容和音色。

冻结样本来自六个 `block-59` sourceUnit；Qwen 按六句逐句生成并确定性复制 Layer 1 句间停顿。AuK challenger 只跑：

- `block-59-u001`：7.32 秒，正常叙述中带重点。
- `block-59-u005`：10.64 秒，后接 1.45 秒停顿。

[plan.json](./plan.json) 锁定韩文、目标时长、停顿、Eric checkpoint／参考音频 hash、两个实验维度和验收项。韩文仍只有机器审校，不得把本实验结果写成正式韩语配音验收。

## 候选矩阵

| 维度 | 候选 | 说明 |
|---|---|---|
| POC-1 调度基线 | `qwen_sft_unit` | 六句分别自然语速生成；不拉伸；按 Layer 1 停顿装配 |
| 直接生成 | `qwen_sft_unit` | 已登记 Eric SFT checkpoint |
| 直接生成 | `auk_zero_shot` | Eric 英文参考音频 + 相同韩文 + `gen_seconds` |
| 韵律后处理 | `qwen_sft_unit` | AuK 编辑前的冻结输入 |
| 韵律后处理 | `qwen_then_auk_speed_emphasis` | 根据实测 Qwen 时长计算速度倍率；AuK 接收目标时长和克制的讲道强调说明 |

已有整段 Qwen 韩语音频可以额外切成 `qwen_whole_group_estimated_slice` 供听感参考，但旧 cue 是按文字长度估算，不能当作可靠的逐句内容／时长基线，也不进入最低 10 个正式候选计数。

## 运行

先验证计划：

```bash
python experiments/layer3-auk-poc/layer3_poc.py validate \
  --plan experiments/layer3-auk-poc/plan.json
```

Qwen 使用现有 Eric checkpoint，逐单元生成六条 WAV：

```bash
python experiments/layer3-auk-poc/render_qwen.py \
  --plan experiments/layer3-auk-poc/plan.json \
  --checkpoint /path/to/eric/checkpoint-epoch-0 \
  --out /path/to/run/qwen
```

AuK 按官方 [zero-shot TTS 与 speed editing 接口](https://github.com/Tencent-Hunyuan/AuK/blob/main/docs/COOKBOOK.md)生成两个 challenger 单元的四个 WAV：

```bash
python experiments/layer3-auk-poc/render_auk.py \
  --plan experiments/layer3-auk-poc/plan.json \
  --config /path/to/AuK/config.yaml \
  --checkpoint /path/to/AuK/auk_base.safetensors \
  --qwen-path /path/to/Qwen2.5-Omni-3B \
  --reference /path/to/eric-reference.wav \
  --qwen-dir /path/to/run/qwen \
  --out /path/to/run/auk
```

装配 POC-1（只插入停顿，不改任何单元语速）：

```bash
python experiments/layer3-auk-poc/layer3_poc.py assemble \
  --plan experiments/layer3-auk-poc/plan.json \
  --qwen-dir /path/to/run/qwen \
  --out /path/to/run/qwen-six-unit-assembled.wav
```

所有候选必须完成：FFmpeg 完整解码、韩语 Qwen3-ASR 内容筛查、WavLM speaker embedding 筛查、实测时长误差、确定性停顿检查和盲听。机器筛查脚本不会授予人工通过：

```bash
python experiments/layer3-auk-poc/screen_candidates.py \
  --plan experiments/layer3-auk-poc/plan.json --run-dir /path/to/run --local-files-only

python experiments/layer3-auk-poc/speaker_similarity.py \
  --plan experiments/layer3-auk-poc/plan.json --run-dir /path/to/run \
  --reference /path/to/eric-reference.wav \
  --model-path /path/to/wavlm-base-plus-sv --revision MODEL_COMMIT

python experiments/layer3-auk-poc/layer3_poc.py evaluate \
  --plan experiments/layer3-auk-poc/plan.json --run-dir /path/to/run

python experiments/layer3-auk-poc/layer3_poc.py listening-page \
  --plan experiments/layer3-auk-poc/plan.json --run-dir /path/to/run
```

## 判定边界

- `gen_seconds` 是时长条件，不是逐词强制对齐；最终仍需 forced alignment。
- `speaker_similarity` 只是跨语言机器筛查。音色像 Eric、韩语自然度、情绪与发音必须人耳判断。
- 任何 AuK speed editing 都不满足当前正式包的 `natural_no_time_stretch` 合同。即使 POC 胜出，也只能先提出新的 `prosody_postprocessor` adapter／schema 版本，不能覆写 v1 生产语义。
- 本实验只覆盖两个句子、一个讲员和一个未人工批准的韩语候选，不能外推到整篇、其他语言、发布、设备或现场验收。

## 验证

```bash
.venv/bin/python -m unittest experiments/layer3-auk-poc/test_layer3_auk_poc.py -v
git diff --check
```
