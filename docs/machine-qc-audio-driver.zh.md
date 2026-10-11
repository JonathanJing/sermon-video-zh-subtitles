# 机器试听豁免驱动（音频 QC 实跑）

`scripts/run_machine_qc_audio_test.py` 是文字驱动 `scripts/run_machine_qc_clip_test.py` 的音频版本：在已有译文豁免、speech job v3、正式音频包和 v2 ASR 筛查的 Dev 运行上，逐语言跑完机器试听豁免链。规则本身见[机器质检豁免](machine-quality-waiver.zh.md)；本文只说明驱动和传输。

## 链路

1. **预检（不调用模型）**：按规范 JSON 哈希找到音频包，再找它绑定的 speech job（须为 v3，`inputs.textReleaseBasis` 指向译文豁免）、英文源包、锚点、候选、policy、译文豁免，以及与音频包完全对应的筛查收据。检查：包为 `machine_screened`/`candidate` 且无人工决定；译文豁免对当前候选与实现仍有效；筛查为 v2、后端 `qwen-asr-local`、按口播稿重算一致；每句 WAV 哈希不变且可解码；冻结原声时长为正；job 的合成身份与包的 `voice` 一致；文字注错各类、`audio.dropped_key_word`、`audio.wrong_sentence` 在这份材料上都有可试的样例。精简口播稿暂不支持。
2. **整轨核对**：`target_audio_auto_qc.check_track`。
3. **单句音频 QC**：从音频修复账本最新位置读失败次数。一级 ASR 意见直接取筛查收据里的转写（设置即收据的 `asrSettings`）；一级不一致的句子由二级 ASR 复核。收据先写入状态目录，再追加进账本；失败句音频未变时拒绝重跑，超过 4 次的句子判为只显字幕（v1 豁免不放行）。
4. **注错校准**：同一候选、同一批句子音频。文字类沿用文字驱动的回译 judge（共用状态目录时直接命中缓存）；音频类 `wrong_sentence` 走两级 ASR，`dropped_key_word` 用 speech job 自己的 TTS 合成去掉否定词／数字的句子再听。
5. **签发试听豁免**：`machine_quality_release_basis.build_audio_waiver`，并立即用 `validate_audio_waiver` 复验。

收据、校准、豁免都按输入哈希命名，只写一次；重跑复用，产物一变就生成新文件，不覆盖旧证据。`summary.json`、`timings.tsv` 记录结果和耗时。驱动不发布，不写人工批准。

## 传输（`scripts/machine_qc_audio_transports.py`）

| 角色 | 实现 | 说明 |
|---|---|---|
| 一级 ASR | `QwenPrimaryAsr` | 筛查过的音频直接用收据转写；校准新合成的音频，先核对本机 Qwen3-ASR 权重哈希、推理身份（torch、qwen-asr、模型元数据）、筛查脚本哈希、设备与精度都与收据一致，再用同样方式转写 |
| 二级 ASR | `OpenAiTranscribeSecondary` | `gpt-transcribe`（与正式来源转写同一模型），OpenAI 音频转写 API；只上传单句 WAV，不发送预期文字、不带 keywords，避免“补听”。仅在 `run_with_openai_environment.py` 选定的 Project 下运行，key 只从环境读取，不入缓存和日志；设置记录 environment 与 credentialAlias，不记录 key。供应方不提供模型修订，`modelRevision=null`，`runtime.modelPinning` 如实写明 |
| TTS | `QwenTtsRender` | 正式渲染器的 `QwenSynthesizer`，checkpoint 来自渲染器的 checkpoint map 并校验哈希与说话人槽位；`renderIdentity` 取自 speech job（provider、model、`conditioningSha256`、合成身份）。需在 Spark 绑定的模型会话中运行 |

付费调用先写 `started.json`，成功后写 `response.json` 与 `outcome.json`；失败一律记为结果未知，不自动重发，整次运行停止新的派发，直到人工对账。`--max-api-calls` 在派发前限制每语言新的付费请求数。

## 运行

```bash
# 预检，不调用模型
python scripts/run_machine_qc_audio_test.py --out artifacts/machine-qc-audio/20261001 --preflight-only
# 管线演练（全部假传输，豁免只在内存中构建）
python scripts/run_machine_qc_audio_test.py --out artifacts/machine-qc-audio/20261001 --backend fake
# 实跑（Spark，dev Project；--state-dir 与文字驱动相同）
python scripts/run_with_openai_environment.py --environment dev -- \
  python scripts/run_machine_qc_audio_test.py --run-dir artifacts/dev-full-rerun-20261001 \
  --out artifacts/machine-qc-audio/20261001 --state-dir artifacts/dev-full-rerun-20261001/machine-qc-state \
  --asr-model-path /models/Qwen3-ASR-0.6B --tts-checkpoint-map path/to/checkpoint-map.json --locales ko
```

## 限制

- 校准 TTS 的种子、精度、attention 和朗读指令由命令行给出（默认与正式渲染器一致：42、bfloat16、sdpa、无指令）；豁免只绑定合成身份，不核对这些渲染设置与原渲染是否相同。逐句朗读指令（unit instructions）和静音修剪不参与校准合成。
- 尚无真实运行：二级 ASR 的首次付费调用、首次音频校准和首次试听豁免都待授权实跑；本次只有假传输的离线测试。
