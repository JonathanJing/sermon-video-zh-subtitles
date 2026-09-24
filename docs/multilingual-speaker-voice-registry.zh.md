# 多语言每周调度与 Speaker Voice Registry

状态：本文冻结 Layer 1 扇出到多语言 Layer 2/3 的周调度方式，并定义长期讲员声音资产与每周内容生产之间的边界。它不把 demo、机器筛查或既有中文样片认可升级为新语言的生产批准。

## 调度模型

四层合同在运行时是 DAG，不是要求所有语言同时跨过同一个全局阶段：

```text
English Source Package（Layer 1，只生成一次）
  ├─ Layer 2 zh-Hans ──通过本语言文字门禁──> Layer 3 zh-Hans
  ├─ Layer 2 ko      ──通过本语言文字门禁──> Layer 3 ko
  ├─ Layer 2 es      ──通过本语言文字门禁──> Layer 3 es
  └─ Layer 2 vi      ──通过本语言文字门禁──> Layer 3 vi

Speaker Voice Registry（长期缓存依赖）───────────────┘
```

- Layer 1 完成后，同时派发全部请求 locale 的 Layer 2；不存在“等所有翻译结束”的 barrier。
- 某个 locale 的 Layer 2 通过后，立即派发同 locale 的 Layer 3；不得等待或借用另一语言的状态。
- 中文、韩语、西班牙语和越南语在逻辑上可并行。单机只有一个可用 TTS GPU worker 时，物理执行按 checkpoint affinity 排队；这不改变 lane 的独立身份。
- 讲员训练是低频资产准备，不是每周生产层。翻译可以在 checkpoint resolve／训练进行时继续；实际 Layer 3 合成同时等待本语言文字门禁和 voice capability。
- Layer 1 identity 改变使所有 locale 失效；Layer 2 改变只使同 locale 的 Layer 3/4 失效；checkpoint 改变只使依赖它的 Layer 3/4 失效。

可执行的计划编译器是 [`prepare_multilingual_weekly_plan.py`](../scripts/prepare_multilingual_weekly_plan.py)，输出 [`sermon-multilingual-weekly-plan-v1`](../schemas/sermon-multilingual-weekly-plan-v1.schema.json)。每个 lane 有独立 lease key；生产模式 fail closed，要求正式 Layer 1、对应用途授权和本语言人工认可。Shadow 模式允许 `unverified_poc`，但输出不能用于发布。

## 独立声音注册表

[`speaker-voice-registry.json`](../config/speaker-voice-registry.json) 是按讲员管理声音身份的规范入口，schema 为 [`sermon-speaker-voice-registry-v1`](../schemas/sermon-speaker-voice-registry-v1.schema.json)。每个条目保存：

- 稳定 `speakerId` 与 checkpoint 内的 `speakerKey`；
- 不依赖某台机器绝对路径的 `checkpointRef`，以及实际 `model.safetensors` SHA-256；
- base model 和 revision；
- 授权用途与证据；
- `zh-Hans`、`ko`、`es`、`vi` 各自独立的 model language、能力状态、demo 状态和听审证据。

注册表不保存私有样本、checkpoint 权重、凭据或 DGX 路径。运行环境通过不进 Git 的 `sermon-speaker-checkpoint-map-v1` 将逻辑 ref 解析到真实目录；renderer 在模型加载前重算权重 hash，并验证 checkpoint 包含目标 `speakerKey`。

### 固定音色与每周审核

周更按实际讲员的 `speakerId` 解析固定的 `speakerKey`、adapter、模型 revision 和 checkpoint；同一讲员的中、韩、西语不在每周重新选声或训练。9 月 20 日片段已使用 Eric 的同一 Qwen SFT checkpoint，韩／西语短样、长句探针及正式片段音轨均有当次人工听审结果。只要这些声音身份和适用授权范围不变，周更不重复要求短样／长句能力试听。每周仍检查新译文产生的整轨发音、完整性和同步，因为这些随内容变化。

**固定选用**与**跨周生产资格**分别记录。当前提交的 Registry 对 Eric 韩／西语仍为 `unverified_poc`，用途为 `multilingual_voice_demo`；现有正式放行凭证明确限于 9 月 20 日片段。准备后续整篇正式 Layer 3 时，需先把跨周用途与能力证据按真实授权范围登记并绑定同一 checkpoint，不能靠“音色已选定”或复用片段收据自动改写状态。待审译文的 `preview_only` 单元配音可先使用已登记的试听用途，不等待该正式资格登记。

同一个按讲员 SFT checkpoint 可以作为中文、韩语和西班牙语的候选，但能力状态不能跨语言继承。Qwen3-TTS 官方与本地 runtime 支持的十种语言不包含越南语，因此越南语不得伪装成同一 adapter 已支持；本轮 Registry 为 `vi` 显式选择基于 Qwen3-TTS 0.6B 的 Gwen-TTS 零样本 reference-clone adapter，并固定模型 revision。中文样片已认可只证明绑定的中文样片；韩语、西班牙语、越南语从 `unverified_poc` 开始，各自经过完整解码、ASR 机器筛查和母语人耳审核后才可晋升。[Qwen3-TTS 官方语言列表](https://github.com/QwenLM/Qwen3-TTS#released-models-description-and-download)、[Gwen-TTS 官方用法](https://github.com/ggroup-ai-lab/gwen-tts#quick-start)

## Demo 生成

统一试听文稿位于 [`multilingual-voice-demo-script-v1.json`](../experiments/sermon-dubbing-poc/multilingual-voice-demo-script-v1.json)。四种文字表达相同短段落的意思，scope 固定为 `voice_capability_audition_not_sermon_translation`；它们不是讲员原话、某周证道译文或正式字幕。

[`render_multilingual_voice_demos.py`](../scripts/render_multilingual_voice_demos.py) 以讲员为单位加载现有 SFT checkpoint，再顺序生成本讲员的中文、韩语和西班牙语，避免每种语言重复加载模型。[`render_vietnamese_voice_demos.py`](../scripts/render_vietnamese_voice_demos.py) 只消费 Registry 的越南语 adapter override，以同一讲员已授权原声参考进行零样本克隆。两个 renderer 的输出不能互换审核状态。每条输出绑定：

- registry、统一文稿和 renderer hash；
- speaker、checkpoint ref/hash、locale 和 Qwen language 参数；
- seed、温度、重复惩罚、实测时长和音频 hash；
- 完整解码、机器筛查和人工听审状态。

示例：

```bash
python scripts/render_multilingual_voice_demos.py \
  --registry config/speaker-voice-registry.json \
  --script experiments/sermon-dubbing-poc/multilingual-voice-demo-script-v1.json \
  --checkpoint-map /private/path/speaker-checkpoints.json \
  --out artifacts/sermon-dubbing/2026-09-21-multilingual-voice-demos

python scripts/render_vietnamese_voice_demos.py \
  --registry config/speaker-voice-registry.json \
  --script experiments/sermon-dubbing-poc/multilingual-voice-demo-script-v1.json \
  --references experiments/sermon-dubbing-poc/multilingual-voice-demo-references-v1.json \
  --reference-root /private/path/authorized-reference-audio \
  --out artifacts/sermon-dubbing/2026-09-21-multilingual-voice-demos
```

输出目录已由根 `.gitignore` 排除。已有单条 WAV 只有在其 receipt 完整匹配当前输入时才能恢复；不匹配时停止，不覆盖旧试听。

两种 adapter 完成后，先用 [`screen_multilingual_voice_demos.py`](../scripts/screen_multilingual_voice_demos.py) 对完整矩阵做 Qwen3-ASR 回转写；相似度只用于安排复核优先级，不是发音或自然度裁判。再用 [`package_multilingual_voice_demos.py`](../scripts/package_multilingual_voice_demos.py) 核对 Registry 的完整讲员 × locale 矩阵，将 WAV 编码为 128 kbps、44.1 kHz、mono MP3，并逐个完整解码。交付 manifest 保持 `humanListeningStatus=pending`，不能因文件可播放或 ASR 相似度高就升级能力状态。

## 本轮 demo 授权与限制

2026-09-21，用户明确要求复用当前已授权讲员样本／checkpoint，制作各讲员中文、韩语、西班牙语和越南语声音克隆 demo。该指示记录为 `multilingual_voice_demo` 用途，不自动授予新语言整篇生产或发布权限，也不把任何机器生成音频变成训练 Gold。

目前登记 Eric Geiger、Jared Kirkwood、Christine Caine、Doug Fields、Kenton Beshore 和 Steve Bang Lee 六位讲员。中文能力状态沿用已绑定样片的现有人工认可；其他三种语言在完成本轮生成后仍保持 `unverified_poc`，直至各语言听审完成。越南语 POC 当前是 reference clone，不等于已经完成与中文相同的 per-speaker SFT；是否为 Gwen-TTS 建立长期训练 checkpoint 要在试听和母语发音审核后另行决定。

本轮实跑已生成 6 位讲员 × 4 个 locale 共 24 条 WAV，并编码为 24 条 MP3；源 WAV 与交付 MP3 均完成全文件解码。Qwen3-ASR 完整覆盖筛查中，韩语和西班牙语为 1.00，中文约为 0.97；6 条越南语全部低于 0.85，已标为人工复核优先项。这个结果只证明文件可解码并给出文本一致性风险信号：所有新语言仍等待母语人耳审核，越南语不得进入正式生产。

统一试听页可从 v2 交付目录离线重建：`python scripts/build_multilingual_voice_preview.py --root artifacts/sermon-dubbing/2026-09-21-multilingual-voice-demos-v2`。生成器逐条验证注册表、文稿、源清单、WAV／MP3 哈希并完整解码 24 条 MP3，随后写入同目录的 `index.html` 与 `preview-verification.json`。页面按讲员／语言筛选和播放，明确区分固定选用的音色与现有语言能力听审状态；它本身不修改 Registry、正式音轨或发布资格。

2026-09-20 证道六句片段的 Eric 单讲员实跑得到同样方向：中文 `0.961905`、韩语 `0.878505`、西班牙语 `1.0` 通过机器筛查门线，越南语 `0.195652` 进入人工复核优先。该结果足以冻结“筛查失败时停止晋升”的调度规则，但不足以断言前三种语言已通过发音、自然度或讲员相似度审核。越南语下一步保留 Gwen-TTS 为基线，同时对支持越南语声音克隆的候选 adapter 做相同文本、相同参考音频、相同 ASR 与母语盲听条件的对照；在对照完成前不把任何新 adapter 写成 Registry 的生产能力。具体固化步骤见[多语言片段 POC 固化流程](multilingual-fragment-poc-solidification.zh.md)。
