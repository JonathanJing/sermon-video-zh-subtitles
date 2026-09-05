# 周六生产流程的中文配音扩展

目标：周六取得视频后，使用讲员自己的训练音色生成中文；周日播放**同一份视频**，用中文 MP3、字幕和证道同行帮助会众跟随。声音准备长期积累；每周复用已训练的讲员检查点。

这是现有周六生产流程的可选扩展。现有证道范围确认、中文审校、双 PDF QA 和发布完成检查继续有效。配音候选可以提前生成供审核；周日版本另需声音和视频同步验收。它仍处于 Discovery，完整现场同步尚未验收。

![从周六生产到中文配音、审核与周日播放](../../docs/diagrams/saturday-chinese-voice-workflow.svg)

## 节点、模型与产物

| 节点 | 当前实现 | 产物与检查 |
|---|---|---|
| 授权来源、完整音频、证道窗口 | 当前周六流程、FFmpeg、GPT-Transcribe、人工 | 复用 `operator-window-approval.json`，调用现有 `validate_window_approval`，保留其 canonical JSON 哈希规则 |
| 英文参考、中文翻译、两轮审校、双 PDF | 当前周六默认 `gpt-6-astra / medium`；英文沿用已有字幕或 GPT-Transcribe | 读取 `reading_blocks.final.json`、阅读 QA 和两份 PDF QA；证道同行只用于大纲，不作为配音稿 |
| 声音候选准备 | Qwen3-ASR 0.6B 8-bit + Qwen3-ForcedAligner 0.6B 8-bit | 原声音频、英文一致性、实际句子边界；按讲员、来源、train split 隔离 |
| 讲员训练 | Qwen3-TTS 12Hz 1.7B Base，Spark BF16 / SDPA | 每人独立 SFT 检查点；本轮每人三篇证道、1 epoch、batch 1、lr 2e-6；音频候选不改称人工 Gold |
| 每周中文生成 | 对应讲员的训练检查点，Chinese | 自然句群、段间停顿；显示文字与发音输入分开；WAV 分段缓存、MP3、实测字幕时间 |
| 声音检查 | Qwen3-ASR 0.6B 8-bit 逐段回听转写 + FFmpeg + 人工 | 全段覆盖、漏读/重复候选、发音、响度、完整解码；ASR 差异可以是同音字，不能直接当 TTS 错误率 |
| 视频同步 | Qwen3-ASR / ForcedAligner 提供声学定位，确定性时长检查 | 原声段落时间与中文时长分开测量；弱边界和超时段进入复核，禁止使用阅读排版时间戳 |
| 发放与播放 | 独立 Firebase Hosting 站点 + 静态 App | 按周选择、主题/讲员、播放/暂停、时间轴、微调、中文字幕、大纲弹窗、讲员音色对照 |

Qwen 的[官方接口](https://github.com/QwenLM/Qwen3-TTS#custom-voice-generation)支持批量 `generate_custom_voice`。整篇渲染使用固定 4 段批次，记录批次、随机种子、检查点与脚本哈希；异常段使用单段重试并记录实际参数。数字（例如 `600`、`2025年`）和神称代词（`祢`、`祂`）只在口播输入中规范发音，字幕保留已审原文。

## 新视频到达后的操作顺序

先完成[当前周六 Runbook](../../docs/codex-local-production-runbook.zh.md)对应的来源、证道范围和阅读产物。下例的 `VIDEO_ID`、主题、讲员、经文需来自新视频及本周审校资料，不能提前编造。

授权凭据沿用本次已确认的训练/配音授权，并为新视频记录 `sourceId` 与 `pipeline/source_clip.m4a` 的 SHA-256；这是来源绑定，不是新增的声音质量批准。准备器会拒绝不匹配的来源凭据。新讲员需先有对应训练检查点及可试听参考。

新来源凭据的最小结构如下；`VIDEO_ID` 和 SHA-256 必须替换为本周实际来源，不能保留占位符。`statement` 记录本次已有的用户授权，只有本授权覆盖的素材才可登记：

```json
{
  "schemaVersion": "sermon-voice-authorization-v1",
  "status": "confirmed_by_user",
  "statement": "已获得授权，声音可以用于训练和配音",
  "purposes": ["voice_training", "chinese_dubbing"],
  "sources": [{"sourceId": "VIDEO_ID", "sha256": "本周 source_clip.m4a 的 SHA-256"}]
}
```

将凭据保存为下例的 `--authorization` 文件。用 `shasum -a 256` 计算来源文件哈希；它与音色质量审核是两份不同的记录。

```bash
.venv/bin/python experiments/sermon-dubbing-poc/weekly_dubbing.py prepare \
  --run artifacts/post-live-runs/2026-09-06/sermon_VIDEO_ID \
  --week 2026-09-06 --title '本周已确认主题' \
  --speaker 'Eric Geiger' --scripture '本周经文' \
  --voice-run artifacts/sermon-dubbing/2026-09-05-corpus-expansion \
  --authorization artifacts/sermon-dubbing/authorizations/2026-09-06-source.json \
  --out artifacts/sermon-dubbing/2026-09-06-weekly

.venv/bin/python experiments/sermon-dubbing-poc/run_weekly_dubbing.py \
  --work artifacts/sermon-dubbing/2026-09-06-weekly \
  --remote-checkpoint /home/achillesjing/dgx-spark-benchmark/results/sermon-voice-expansion-20260905/checkpoints/checkpoint-epoch-0
```

第二条命令连接现有 Spark 隔离运行环境，生成/续跑中文、合成 MP3、定位英文音频、逐段 ASR 回转写检查，并输出同步问题单。语料、检查点和完整原声音频不会进入 Firebase 上传目录。

`job.json` 冻结周六输入文件与声音检查点。修改来源、窗口、阅读稿或检查点后，需要新 job；不复用旧审核。缓存中未完成的单段有独立失败 WAV，最多自动处理 5 次已识别的时长/信号异常，其他错误保留现场供检查。

## 周六审核增加哪些内容

先读取同一周的 `audio/asr-screening.json` 和 `synchronization/report.json`。新步骤关注以下内容：

1. **讲员身份与原声相似度**：原声对照和中文试听交替播放，比较音色、语气、稳定性。Eric 扩充版的样片认可不自动批准其他讲员或新一周完整音轨。
2. **中文是否自然**：完整句子是否连贯，停顿是否合理，人名、经文、数字是否读对；检查回转写标出的漏读/重复。机器未发现差异仍需真人试听。
3. **同视频同步**：弱边界需对照原视频确认；超出原声时槽的段落回到同一中文审校流程修订并重新生成。脚本不会截句、叠音或自动加速来掩盖超时。
4. **冻结本周版本**：审核人、时间、检查点、MP3、job 和原始周六完成证据相互绑定。

声学边界复核记录放在 `source-alignment/anchor-review.json`，使用 schema：

```json
{
  "alignmentSha256": "待填原 alignment report 的 SHA-256",
  "humanApproval": false,
  "reviewedBy": null,
  "reviewedAt": null,
  "blocks": [{"blockId": 2, "start": 65.04, "end": 102.8}]
}
```

上面的时间只示范结构，不能复制为其他视频的审核。由实际看片者填写全部不确定边界及真实审核信息。只有边界已复核且自然中文全部放得进视频时槽，才可装配同视频 MP3：

```bash
/Users/jonathan_jing/.local/share/uv/tools/mlx-audio/bin/python \
  experiments/sermon-dubbing-poc/check_weekly_timing.py \
  --work artifacts/sermon-dubbing/2026-09-06-weekly --assemble
```

输出 `synchronization/zh-synced.mp3` 与 `audio-review-synced.json`。按已确认的证道窗口起点启动它；自然版 `audio/zh-natural.mp3` 的时间轴只对应中文。实际试听者在审核记录中填写身份、时间和六项检查结果，不能由机器代填人工批准。

```bash
.venv/bin/python experiments/sermon-dubbing-poc/weekly_dubbing.py validate-review \
  --work artifacts/sermon-dubbing/2026-09-06-weekly
```

这个验证调用现有 `local_completion_artifacts`，重新核对周六 generation、run-status、双 PDF 和 GCS 文件。不能用一个新字段绕过旧流程的失败完成记录。

## 发布按周应用

```bash
.venv/bin/python experiments/sermon-dubbing-poc/build_weekly_app.py \
  --expansion artifacts/sermon-dubbing/2026-09-05-corpus-expansion/chinese-audio \
  --voice-bank artifacts/sermon-dubbing/2026-09-05-speaker-bank/speaker-bank.json \
  --weekly-job artifacts/sermon-dubbing/2026-09-06-weekly \
  --out artifacts/sermon-dubbing/2026-09-06-release

python3 experiments/sermon-dubbing-poc/deploy_firebase.py \
  --release artifacts/sermon-dubbing/2026-09-06-release \
  --project ai-for-god-caption-dev --site ai-for-god-sermon-audio --execute
```

`--weekly-job` 可重复提供多周，不需要修改前端代码或写死日期。默认只接受正式审核通过的同步版本。专门发给审核人员试听时，可以显式加 `--review-preview`；App 会显示“整篇待审”和未完成的同步状态。预览不会生成周日批准记录。

上传前核对文件清单/哈希，上传后验证 URL、完整文件哈希、音频 Range 206、播放/跳转/字幕、大纲和手机尺寸。独立站点是 [ai-for-god-sermon-audio.web.app](https://ai-for-god-sermon-audio.web.app)，现有实时字幕站点继续使用其原地址。

## 已完成的真实流程样本

本轮用 8 月 30 日的完整现有证道运行准备、生成、恢复、回听和同步检查，并为发音规范创建独立修订：原版本 122 段、26 分 45 秒；新修订保留 96 段经哈希核对的声音，重做 26 段数字/代词发音输入。父版本、失败样本和原始审核都保留。

五位新增讲员各三篇证道，共 223 段 / 1,803 秒训练候选。五份约 27–31 秒的中文试听 MP3 已生成，完整解码通过；对应固定试听文稿的本地 ASR 未发现文字差异。这不等于已由真人确认音色相似度。

原周六历史样本仍有失败 generation / 未完成 run-status，因此只用来证明候选生成与审核扩展。现场同视频同步、实体手机后台/蓝牙播放及新视频的实际质量，还需要对应实测。SVG 展示完整流程和审核位置，不把这些未验收项标成已上线能力。
