# 多语言片段 POC 固化流程

状态：本文把 2026-09-20 六句证道片段已跑通的 Layer 2、Layer 3 和 Dev Layer 4 路径固化为可复跑的 shadow 流程。它不改变四层正式合同，不授予人工批准，也不把 POC 产物升级为生产发布包。

## 已冻结的执行图

```text
Layer 1 English Source Package（共享且不可在下游修补）
                    │
          每个 targetLocale 独立扇出
                    ▼
Layer 2 翻译候选 → GPT semantic judge → human translation pending
                    │
             同 locale 哈希绑定
                    ▼
Layer 3 voice render → full decode → ASR screening → human listening pending
                    │
             同 locale 哈希绑定
                    ▼
Layer 4 Dev catalog/release → Firebase HTTP/Range 验证
```

- Layer 1 只有一份。其 identity 改变时，全部语言 lane 失效。
- Layer 2 与 Layer 3 按 locale 独立运行；某一语言失败不会阻塞其他语言，但失败 lane 不能进入下一层。
- GPT judge 只检查源句覆盖、句意、否定、名称、数字、引语归属和无增义。`machine_review_pass_human_review_pending` 仍不是人工认可。
- ASR 相似度只用于复核排序。达到 `0.85` 只表示转写一致性筛查通过，不证明发音、自然度或讲员相似度；低于门线必须写成 `requires_review`。
- 当前字幕时间是 `estimated_proportional_to_target_text_poc`，只能用于 App POC。生产 Layer 3 必须换成真实音频对齐结果。

## 固化的生成与校验步骤

Layer 2 生成器使用 Secret Manager 中现有的 OpenAI API key；它在一个新目录中写入四种语言候选和收据，不允许覆盖已有运行：

```bash
python scripts/generate_multilingual_fragment_poc.py \
  --anchor-manifest /path/anchor-manifest.json \
  --english-source-package /path/english-source-package.json \
  --source-unit block-59-u001 --source-unit block-59-u002 \
  --source-unit block-59-u003 --source-unit block-59-u004 \
  --source-unit block-59-u005 --source-unit block-59-u006 \
  --api-key-secret OPENAI_API_KEY \
  --out artifacts/multilingual-poc/<run-id>/layer2
```

Layer 3 renderer 完成 WAV 后，先打包并完整解码，再运行现有 ASR 筛查，最后一次性绑定 Layer 2/3/ASR 收据：

```bash
python scripts/package_multilingual_fragment_poc.py \
  --layer2 artifacts/multilingual-poc/<run-id>/layer2 \
  --layer3 artifacts/multilingual-poc/<run-id>/layer3

python scripts/screen_multilingual_voice_demos.py ... \
  --out artifacts/multilingual-poc/<run-id>/layer3/asr-screening.json

python scripts/finalize_multilingual_fragment_poc.py \
  --layer2 artifacts/multilingual-poc/<run-id>/layer2 \
  --layer3 artifacts/multilingual-poc/<run-id>/layer3

python scripts/finalize_multilingual_fragment_poc.py \
  --layer2 artifacts/multilingual-poc/<run-id>/layer2 \
  --layer3 artifacts/multilingual-poc/<run-id>/layer3 \
  --check-only
```

`finalize_multilingual_fragment_poc.py` 检查候选 JSON hash、Layer 3 对 Layer 2 的绑定、renderer 音频 hash、ASR 预期文字 hash、MP3 hash 和 locale 完整覆盖。任何一项不一致就停止。写入模式只会记录机器筛查状态，始终保留 `productionEligible=false`、`humanApproval=false`。

Firebase 的 JSON 包进入 Git，音频不进入 Git。部署前从已验证的 artifact 目录暂存 canonical 包和 MP3：

```bash
python scripts/stage_multilingual_fragment_poc_firebase.py \
  --layer2 artifacts/multilingual-poc/<run-id>/layer2 \
  --layer3 artifacts/multilingual-poc/<run-id>/layer3 \
  --source-media artifacts/resi-live-20260919/mariners-20260919-service-1080p.mp4
```

暂存脚本要求 Layer 2/3 哈希绑定，并要求 Layer 3、`weekly.json` 与 MP3 的 SHA-256 完全一致。若 catalog 含英文来源页，`sourceWindow` 必须显式声明 `timebase=sermon_relative_seconds` 和完整来源媒体中的 `sourceMediaOffsetSeconds`；脚本先把证道相对时间转换成完整视频绝对时间，再截取原始讲员音频、完整解码并核对固定哈希。禁止把证道相对秒数直接用作完整聚会视频的 seek 位置。这条 `en` lane 是 Layer 1 对照，不是假装成目标语言翻译。`firebase/dev/public/media/` 被 `.gitignore` 排除，避免把生成媒体提交到仓库。

## 当前模型能力与越南语决策

| locale | 当前 adapter | 2026-09-20 片段机器筛查 | 当前结论 |
|---|---|---:|---|
| `zh-Hans` | Qwen3-TTS 讲员 SFT | `0.961905` | 可继续 shadow 与人耳审核 |
| `ko` | Qwen3-TTS 讲员 SFT | `0.878505` | 可继续 shadow 与韩语母语审核 |
| `es` | Qwen3-TTS 讲员 SFT | `1.0` | 可继续 shadow 与西语母语审核 |
| `vi` | Gwen-TTS reference clone | `0.195652` | 停止晋升，进入替代模型对照 |

Qwen3-TTS 当前官方十种语言为中文、英文、日文、韩文、德文、法文、俄文、葡萄牙文、西班牙文和意大利文，不含越南语。越南语不复用 Qwen SFT 的语言能力结论。下一轮 adapter bake-off 固定英文源句、越南语译文、Eric 授权参考音频、随机种子、输出响度、ASR 模型和母语盲听表，只更换 TTS adapter。候选优先级为：越南语专项 voice-clone adapter、Gwen-TTS 基线，以及许可证允许当前用途的高质量多语言 challenger。

## 从 POC 到正式生产仍缺的门禁

1. Layer 2 每个 locale 的人工翻译批准及 reviewer evidence。
2. Layer 3 母语人耳完整试听，包括发音、韵律、音色相似度、神学专名和数字。
3. 用真实合成音频完成逐句对齐，替换估算 cue。
4. 生成 canonical `sermon-target-language-release-package-v1`，而不是 demo schema。
5. Dev Web、iOS 设备、Firebase HTTP/Range 和现场播放分别验收。
6. 只有上述证据都绑定到同一组输入 hash，才允许从 `dev` PR 晋升到 `main`；任何 POC 状态都不能自动触发 Production Firebase 发布。
