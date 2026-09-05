# 每周听译应用、后训练语料复用与 Firebase 发布

2026-09-05。已在分支 `codex/saturday-sunday-chinese-voice-plan` 实现并部署[每周中文听译应用](https://ai-for-god-sermon-audio.web.app)。用户认可上一轮训练样片，确认可以基于更多证道训练。当前发布的是带真实中文样片的应用，整篇配音与英文视频同步尚未完成。

## 后训练数据可以怎样复用

声音训练使用原始英文录音和同一段实际英文措辞。既有中英对照用于翻译质量、口播稿和中文评估；不能把英文录音与中文译文作为同一 TTS 训练标签。

本次只读核验独立 `sermon-video-zh-subtitles-ios-design` 工作区的数据：

- `data/reports/sermon-parallel-corpus-splits-v1/split-manifest.json`：180 篇，train 141、dev 18、test 18、POC 3。
- `data/reports/mariners-sermon-training-audio-v1/manifest.jsonl`：133 份整篇音频，133 份文件存在且 SHA-256 与清单一致。
- `data/benchmarks/milmmt-sermon-v4/corpus-split.json`：额外冻结的最终评估证道同样排除。
- 118 篇约 66.27 小时满足本次素材筛选前提：train 分区、原音 hash 一致、有英文来源、没有保留证道或同日期冲突。

| 元数据讲员 | 可进入声音素材筛选的证道数 |
|---|---:|
| Eric Geiger | 86 |
| Jared Kirkwood | 9 |
| Christine Caine | 6 |
| Doug Fields | 5 |
| Kenton Beshore | 6 |
| Steve Bang Lee | 6 |

这些数字是**整篇素材候选**，不是已审核的干净讲话小时数。按人物元数据分组尚不等于逐段说话人分离。完整训练前仍需检测换人、重叠、音乐、掌声和句首句尾截断；人工音文核对与 speaker-turn review 保持独立。

保留原有 train/dev/test/POC 及 untouched-final 划分，同一礼拜完整录像和剪辑版不得当作不同证道。本次没有修改原语料、历史权利字段、翻译准入记录或 Gold。新的声音授权依据当前对话，按所选来源 ID/hash 写入独立派生记录；旧翻译数据的 `blocked` 不被误当作本次声音授权仍未获得，也不被批量改写。

复现只读盘点：

```bash
python3 experiments/sermon-dubbing-poc/audit_voice_corpus.py \
  --corpus /path/to/sermon-video-zh-subtitles-ios-design \
  --out artifacts/sermon-dubbing/a-new-corpus-audit
```

## 实际扩充训练

从现有已下载原音选择 Eric 的三篇不同证道，避开已经用于首轮样片的 8 月 23 日完整录像及其剪辑版：

| 来源 | 日期 | 新候选片段 |
|---|---|---:|
| `V6OKiwbjDZE` | 2026-06-21 | 26 |
| `KgBFtTCCS9s` | 2026-06-14 | 15 |
| `2YIcu7033uw` | 2026-06-07 | 22 |

每篇检查第 5–10 分钟，合计 15 分钟原音窗口。Qwen3-ASR 0.6B MLX 转写，Qwen3-ForcedAligner 0.6B MLX 对齐，使用已有英文语料核对措辞；跳过窗口首尾句，筛除不一致、时间预算不符或信号异常的片段。得到 **63 段、487.40 秒**。这是独立工程试跑数据，未改为人工批准的生产训练数据。

DGX Spark 使用与上一轮相同的官方 Qwen3-TTS 12Hz 1.7B Base 起点，重新训练 1 epoch；没有覆盖上一轮 checkpoint，也没有在上一轮权重上继续累加训练。

- Base revision：`fd4b254389122332181a7c3db7f27e918eec64e3`。
- 上游训练代码：`022e286b98fbec7e1e916cb940cdf532cd9f488e`。
- bf16、SDPA、batch 1、gradient accumulation 4、学习率 `2e-6`、seed 42。
- 音频编码 16.94 秒，训练及保存 75.35 秒；63 个 batch，loss 全部有限。
- 非手工 speaker slot 的注意力权重有 202,078 个元素变化，最大绝对差 `4.1961669921875e-05`。
- 新 checkpoint SHA-256：`3b46fc0f5268c3bf14c55c0b11833125fbacc31c6a7ae8b7f1328a227ef8a4d0`。
- 原有隔离 venv 只读挂载复用；新结果写独立目录。没有停止其他 Spark 服务。

Spark checkpoint：`/home/achillesjing/dgx-spark-benchmark/results/sermon-voice-expansion-20260905/checkpoints/checkpoint-epoch-0/`。

同一份 398 字符中文、5 个完整语音组，生成扩充训练样片 **75.20 秒**；两遍响度处理后为 mono 48 kHz / 192 kbps MP3。完整解码通过，实测 -18.34 LUFS / -1.75 dBTP。自动回转写只出现 `作/做` 同音字候选差异；这不能证明自然度或音色相似度优于旧版。

新 MP3 SHA-256：`8c83cca82f89987b9432cc68b7795dd4f92c308bc298b153e0926be795e9d6c7`。

对照保留已经试听的 78.64 秒训练版及 77.44 秒原声参考版。新版本没有再次运行未训练 Torch Base；原始 probe report 中通用的 paired-control 描述不代表本次重新生成了 Base，对照范围以 `chinese-audio/import-report.json` 为准。脚本已修正单 checkpoint 运行的报告语义。

## 应用与发布范围

- 周次下拉和「听译／字幕全文」选项卡。
- 每周主题、讲员、经文与英文原视频链接。
- 播放、暂停、重新播放、MP3 下载、连续时间轴、±5 秒、±1 秒、±0.25 秒与输入时间跳转。
- 点击字幕段落定位；高亮当前中文，显示下一段提示。字幕时间来自真实生成音频组，未冒用阅读稿估算时间。
- 「证道同行大纲」弹窗显示既有整篇摘要、大纲和默想问题；打开大纲不打断音频。
- 切换周次或音色会暂停并重置进度、字幕和微调累计值；没有配音的周次清空旧音频并禁用控件。
- 2026-08-23 提供三种音色样片，默认「已试听版」；2026-08-30 展示真实大纲，配音待生成。

讲员与主题日期依据既有英文原稿及 [Mariners 官方证道页面](https://www.marinerschurch.org/message/when-i-am-angered/) 核对；中文摘要与大纲仍标明为 AI 整理。

Firebase 项目为 `ai-for-god-caption-dev`，新建独立 Hosting site `ai-for-god-sermon-audio`。本次只部署 `hosting:sermonDubbing`。原实时字幕站点、数据库规则和其他服务不在部署范围。

当前 9 个公开文件共 5,604,948 字节：5 个 UI 文件、周次清单与 3 个中文 MP3。为这个小规模静态样片直接使用 Firebase Hosting 发放音频；整篇及长期归档可再迁移至 Cloud Storage，保留周次清单接口。没有把训练集、英文原音、参考声音或 checkpoint 上传到 Firebase。部署器在上传前核对完整文件名单、类型和 SHA-256。

[Firebase 多站点与部署目标说明](https://firebase.google.com/docs/hosting/multisites)、[Hosting 配置说明](https://firebase.google.com/docs/hosting/full-config)。

## 验证与剩余事项

20 个 Python 测试、8 个 Node 测试通过，覆盖原音绑定、保留数据拦截、候选约束、周次清单、缺失媒体、时间输入/边界、字幕重叠、HTTP Range 与发布目录隔离。JS 语法检查通过；此应用无外部运行依赖，构建步骤是带哈希核验的静态发布包导出。

真实浏览器验证了播放、大纲弹窗、字幕跳转到 72 秒、输入 30 秒后微调为 29.75 秒、周次切换清空旧音频；小屏布局另以浏览器视口检查。线上文件哈希、媒体 Range 及私有路径隔离的详细结果保存在发布目录，浏览器在线播放另记回执。

当前不宣称整篇英文视频同步、会场就绪、手机锁屏后台播放或真实蜂窝网络效果已通过。多篇训练版仍待人试听；全量训练前还需逐段讲员、干净音频和英文标签准入。

本地详细证据位于忽略目录：

- `artifacts/sermon-dubbing/2026-09-05-corpus-expansion/`：只读语料盘点、三篇扩充清单、源音/切片哈希、ASR/对齐、训练日志、权重证据、中文 MP3 与回转写。
- `artifacts/sermon-dubbing/2026-09-05-weekly-app-v2/`：公开包、构建文件哈希、Firebase 发布日志、HTTP 与浏览器验证回执。

本次未提交或推送 Git。
