# 周六生产流程的中文配音扩展

目标：周六取得视频后，使用讲员自己的训练音色生成中文；周日播放**同一份视频**，用中文 MP3、字幕和证道同行帮助会众跟随。声音准备长期积累；每周复用已训练的讲员检查点。

这是现有周六生产流程的可选扩展。现有证道范围确认、中文审校、双 PDF QA 和发布完成检查继续有效。配音候选可以提前生成供审核；周日版本另需声音和视频同步验收。它仍处于 Discovery，完整现场同步尚未验收。

本页是当前中文 Layer 2／3 的 legacy adapter 操作说明，不是四层接口本身。今后的预制生产必须先消费 `ready_for_translation` 的 `English Source Package`；在通用 producer 尚未生成并校验 `Target-Language Candidate` 与 `Target-Language Audio Package` 前，只能报告 legacy 候选状态，不能宣称对应规范层已经完成。统一接口见[多语言生产四层接口](../../docs/multilingual-production-interfaces.zh.md)。

![从周六生产到中文配音、审核与周日播放](../../docs/diagrams/saturday-chinese-voice-workflow.svg)

系统架构、模型分工及选择依据见[系统设计与模型选择](../../docs/sermon-dubbing-system-design.zh.md)。

## 两路来源与周六定时衔接

两路并行推进：

- **同版本纯证道视频主路（接入器已实现，待实际来源）**：`prepare_same_video.py` 校验周次、来源 ID／canonicalURL、文件 SHA-256、完整片长、音视频流和同版／纯证道确认依据；独立归档后使用 `0 → 完整片长`。该路记录 `humanWindow=not_applicable`，不生成旧式人工窗口批准。实际视频尚未收到，当前证据为软件测试和合成视频初始化，不能宣称真实来源全流程已通过。
- **直播归档 fallback（当前可用，半自动）**：继续现有直播归档与 PDF 流程，复用已确认的证道窗口。当前 v1 只消费真实人工窗口；将来自动探测和审核边界要另建模型证据契约，不能写成 v1 人工批准。主路缺少来源不会阻挡 fallback。

桥接器默认只读检查；`--execute` 会在来源和 QA 齐备后准备或恢复配音候选，使用按周、来源隔离的锁。文字修订和审核在本对话使用 GPT-6 Astra；桥接器本身不调用另一个文本审核服务。

未来周运行只要配置了 `--dubbing-config`，主生产入口也会从冻结的 MFA 英文自动准备 clause-stable v2 Layer 1 shadow。它写入哈希隔离的 `anchor-manifest.json`、`english-source-package.json` 和 `receipt.json`；干净锚点在缺少 GPT machine-judge 收据时为 `waiting_machine_judge`，只有收据全量通过才成为可供 Layer 2 shadow 使用的 `candidate_ready_for_translation`。有不可裁判的对齐异常或没有安全分句点时 package 保持 `blocked`、receipt 指向 `waiting_anchor_review`，不调用翻译／TTS，也不影响本页描述的现有配音候选或双 PDF。详见[句级锚定与滚动同传设计](../../docs/sentence-aligned-interpretation.zh.md#未来周生产接线)。

需要从 PDF 一起顺序推进时，使用[周六统一入口](../../docs/saturday-harness.zh.md)。配音 runner 另按真实工作目录加锁，命令有超时，SSH 结果不明时先核对远端并隔离导入；恢复规则与收据位置见[执行保护与恢复](../../docs/sermon-execution-harness.zh.md)。固定版本比较可用[离线质量回归](../../docs/saturday-quality-harness.zh.md)，不能替代下文整篇听审。

```bash
.venv/bin/python experiments/sermon-dubbing-poc/continue_saturday_dubbing.py \
  --week 2026-09-06 --config artifacts/sermon-dubbing/saturday-bridge.json
# 实际推进已有来源的配音候选：在同一命令后加 --execute
```

同版来源首次就绪后，按桥接报告的 `nextActions` 运行 `prepare_same_video.py --initialize`，在独立 `sameVideo.run` 中归档；它给出当前对话可执行的 ASR／阅读／解读命令。完成修订后运行 `--seal-reviewed`：重验 ASR、英文、阅读稿、双 SRT 和解读切片的来源链，在独立目录重建双 PDF 并绑定输入／输出哈希，然后回到桥接器 `--execute` 准备配音候选。已存在且有效的阶段会被复用；仅封存失败时不会再次执行解读生成。来源或证据失效时保留原文件并停止该路，健康 fallback 仍可推进。完整契约与本轮验证见[开发进度核验](../../docs/saturday-development-progress-2026-09-05.zh.md)。

```bash
# RUN 使用桥接报告给出的独立来源目录；契约来自已核实视频，不照抄测试数据。
.venv/bin/python experiments/sermon-dubbing-poc/prepare_same_video.py \
  --config artifacts/sermon-dubbing/saturday-bridge.json --week YYYY-MM-DD \
  --run RUN --initialize
# 完成上述入口给出的生产和审核步骤后：
.venv/bin/python experiments/sermon-dubbing-poc/prepare_same_video.py \
  --config artifacts/sermon-dubbing/saturday-bridge.json --week YYYY-MM-DD \
  --run RUN --seal-reviewed
```

已建立的本机配置记录六位讲员训练结果、现有授权范围和周次来源。Eric 样片此前已获认可；2026-09-05 用户进一步确认 Jared Kirkwood、Christine Caine、Doug Fields、Kenton Beshore 和 Steve Bang Lee 当前五份中文音色试听均已人工认证，见[按试听音频与检查点绑定的回执](reviews/speaker-voice-acceptance-2026-09-05.json)。这不替代每周整篇审核、训练片段正式准入或现场同步验收。新周次讲员、主题、经文应从真实视频/已审产物核验后登记，不能从目录名猜测。可版本化的结构见 [saturday-bridge.example.json](saturday-bridge.example.json)。配置、音频和审核证据留在忽略目录。

接线目标沿用现有定时任务的周六 18:00、20:00、22:00 与周日 08:00（洛杉矶）的有效唤醒。PDF 已完成仍需检查配音扩展是否完成；只恢复缺失阶段。整篇模型审核候选与周日现场验收分开记录。2026-09-05 本次应用接口未返回，回读仍为原双 PDF 任务；桥接器和配置已验证，定时接线尚待应用确认。

## 本对话的口播修订与边界审核

新制作默认先完成[和合本（CUV）锁定与全篇审校](../../docs/sermon-cuv-production.zh.md)：英文冻结后、TTS 前执行 `scripts/sermon_cuv_translation.py run`，精确锁住直接引文，再翻译并独立审校旁白；桥接器不会自动补做此步骤。使用其 `blocks.json` 与哈希绑定的 `spoken-review.json` 作为新中文及派生依据，字幕、PDF、配音和大纲所引经文保持同源；讲员解释、玩笑或错引不强改为经文，机器通过不等于人工听审。重译或旁白精练后必须对新 WAV 重测时长；实测超时才按链接中的 `repair-timing` 流程修订，始终保留锁定经文和旧版本证据。

`apply_spoken_review.py` 将当前对话的两轮 Astra 审核保存为 `sermon-spoken-script-review-v1`，派生新 job，并哈希绑定父版本、英文/中文、审核材料和模型身份。未变的 WAV 与逐段 ASR 可复用；改变英文时用已有原声词证据重新匹配，不修改历史阅读稿或 PDF。

```bash
.venv/bin/python experiments/sermon-dubbing-poc/apply_spoken_review.py \
  --parent artifacts/sermon-dubbing/PARENT_JOB \
  --review artifacts/sermon-dubbing/REVIEW/script-review.json \
  --out artifacts/sermon-dubbing/NEW_JOB
```

弱边界模型审核使用独立 `source-alignment/anchor-model-review.json`，要求 Astra 身份、逐块理由、来源/任务/声学证据哈希，不冒充 `anchor-review.json` 的人工批准。可选 `synchronization/placement-model-review.json` 只调整明确审查的中文播放起点：至多提前一秒、不得早于前段英文结束，并重新计算相邻中文时槽。原英文锚保留在报告；这不是现场口型同步验收。

所有恢复步骤检查完整缓存链。输入、渲染、ASR 或对齐证据改变后保留旧记录并停止，不因存在 MP3 就跳过核验。普通定时运行不会自动删除缓存或重做付费阶段。

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

1. **讲员身份与原声相似度**：原声对照和中文试听交替播放，比较音色、语气、稳定性。Eric 及本次新增五位讲员的当前音色试听均已有用户认可；新检查点或新一周完整音轨仍按其实际内容审核，不能复用样片认可作为整篇批准。
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

上面的时间只示范结构，不能复制为其他视频的审核。由实际看片者填写全部不确定边界及真实审核信息。候选允许使用上述明确标记的 Astra 边界审核；只有边界已复核且自然中文全部放得进审核后的播放时槽，才可装配同视频 MP3：

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

`--weekly-job` 可重复提供多周，不需要修改前端代码或写死日期。默认只接受正式审核通过的同步版本。专门发给审核人员试听时，可以显式加 `--review-preview`；App 会显示“整篇待审”和未完成的同步状态。预览不会生成周日批准记录。已通过时槽检查并装配的同步候选，可同时加 `--review-preview --sync-preview`；它使用同步 MP3 与对应字幕时间轴，并在界面标明模型审核候选、现场试听未验收。传入 `--weekly-job` 时默认只构建指定周次，不依赖旧示例目录；显式 `--include-history` 可保留已存在的历史周次和试听。

上传前核对文件清单/哈希，上传后验证 URL、完整文件哈希、音频 Range 206、播放/跳转/字幕、大纲和手机尺寸。独立站点是 [ai-for-god-sermon-audio.web.app](https://ai-for-god-sermon-audio.web.app)，现有实时字幕站点继续使用其原地址。

## 已完成的真实流程样本

本轮用 8 月 30 日的完整现有证道运行准备、生成、恢复、回听和同步检查，并为发音规范创建独立修订：原版本 122 段、26 分 45 秒；新修订保留 96 段经哈希核对的声音，重做 26 段数字/代词发音输入。父版本、失败样本和原始审核都保留。

五位新增讲员各三篇证道，共 223 段 / 1,803 秒训练候选。五份约 27–31 秒的中文试听 MP3 已生成，完整解码通过；对应固定试听文稿的本地 ASR 未发现文字差异。上述机器结果与人工试听分开记录：用户于 2026-09-05 确认这五份当前音色试听已人工认证，[回执](reviews/speaker-voice-acceptance-2026-09-05.json)绑定其 MP3 与检查点。训练候选的逐段准入和整篇配音审核状态继续独立保留。

原周六历史样本仍有失败 generation / 未完成 run-status，因此只用来证明候选生成与审核扩展。现场同视频同步、实体手机后台/蓝牙播放及新视频的实际质量，还需要对应实测。SVG 展示完整流程和审核位置，不把这些未验收项标成已上线能力。

最新实测见 [2026-09-05 Astra 修订与同步候选报告](../../docs/sermon-dubbing-astra-review-2026-09-05.zh.md)。
