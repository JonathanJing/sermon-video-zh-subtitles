# Omni 隐形辅助标注 POC（Discovery）

本实验比较 Gemini 3.8 Live Extended Thinking、NVIDIA Nemotron 3 Nano Omni 和 Qwen3-Omni Thinking 对同一段讲道音频、视频及机器英文字幕的联合理解。输出只作为 sidecar 候选，不能自动改写英文字幕、中文翻译、配音或正式时间轴。

## 固定输入与任务

- 视频、16 kHz 单声道 PCM、精确静音负例和英文 ASR 候选全部绑定 SHA-256。
- 三个模型使用同一份 `prompt.txt`，识别 `transition`、`scripture_reading`、`sermon_explanation` 和至少 250 ms 的可听停顿。
- 模型必须区分音频、画面和机器字幕证据。画面出现经文不能单独证明讲员正在读经；字幕中的标点或措辞不能单独证明有停顿。
- 结果通过 `schema.py` 做结构检查；结构通过不等于内容正确。人工参考区间和逐字完整性另行审核。

本轮真实样本取自用户确认的 2026-09-20 完整礼拜视频，完整视频时间 2068–2100 秒，对应讲道相对时间 279–311 秒。样本包括讲员过渡、屏幕显示 `REVELATION 2:1`、朗读经文及返回解释。源媒体和所有完整模型输出只保存在忽略目录 `artifacts/omni-annotation-poc/`。

## 准备

```sh
python3 experiments/omni-annotation-poc/prepare.py \
  --source-video artifacts/resi-live-20260919/mariners-20260919-service-1080p.mp4 \
  --source-id 7c193fd4-bc90-4f3b-aa00-37dfe8423aa0 \
  --start 2068 --duration 32 \
  --transcript-report artifacts/omni-annotation-poc/20260920-scripture-01/transcript/report.json \
  --out artifacts/omni-annotation-poc/20260920-scripture-01
```

英文字幕来自现有 transcript-first POC。其 `invalid_alignment` 或 `transcriptCompletenessProven=false` 状态必须原样进入 manifest，不能因 Omni 能生成标签就升级为逐字完整。

## OpenAI-compatible 本地模型调用

Nemotron 和 Qwen 的 vLLM 服务均从 Spark loopback 端口调用，媒体目录以只读方式挂载。每次调用先写 attempt，再保存 raw response 和校验结果；状态不明的请求不自动重试。

```sh
python3 experiments/omni-annotation-poc/run_openai_compatible.py \
  --base-url http://127.0.0.1:8910/v1 \
  --model MODEL_ID \
  --prompt /data/prompt.txt \
  --video /data/input/real-av.mp4 \
  --audio /data/input/real-audio.wav \
  --server-video-uri file:///data/input/real-av.mp4 \
  --server-audio-uri file:///data/input/real-audio.wav \
  --duration 32 --case-id real-av --expected-audio-status matched \
  --out /data/results/MODEL
```

静音负例把 `--audio` 和 `--server-audio-uri` 指向 `silence-audio.wav`，视频和字幕保持相同，并传入 `--expected-audio-status no_speech`。这个预期来自测试夹具而不是模型自报，用于检查模型是否仅凭画面或字幕虚构读经、音频证据或可听停顿。

## Gemini Live

Gemini 使用独立的忽略目录虚拟环境，按 100 ms 发送 16 kHz PCM，并按最高 1 FPS 发送 JPEG 帧。API key 只从已有进程环境或显式 `--env-file` 临时读入内存，不写入 request、response 或 Git。

```sh
uv venv artifacts/omni-annotation-poc/runtime-gemini
uv pip install --python artifacts/omni-annotation-poc/runtime-gemini/bin/python google-genai
artifacts/omni-annotation-poc/runtime-gemini/bin/python \
  experiments/omni-annotation-poc/run_gemini_live.py \
  --env-file ../Grace-Irvine-Ministry-UI/.env.local \
  --prompt artifacts/omni-annotation-poc/20260920-scripture-01/prompt.txt \
  --video artifacts/omni-annotation-poc/20260920-scripture-01/input/real-av.mp4 \
  --audio artifacts/omni-annotation-poc/20260920-scripture-01/input/real-audio.wav \
  --duration 32 --case-id real-av \
  --out artifacts/omni-annotation-poc/20260920-scripture-01/results/gemini
```

## 验证

```sh
python3 -m unittest discover -s experiments/omni-annotation-poc -p 'test_*.py' -v
git diff --check -- experiments/omni-annotation-poc
```

最终比较至少报告：模型及 revision、实际输入哈希、真实／静音条件的结构状态、读经区间、经文引用、停顿候选、误报和延迟。没有人工听审时只报告模型间差异，不能报告准确率。

Qwen 官方 BF16 Thinking checkpoint 对 15 秒视频的理论最低显存约 68.74 GB。Spark 上已有 `llama-server.service` 时，`spark_start_qwen.sh` 会拒绝启动，避免擅自中断现有服务；只有获得操作员明确批准、停止该服务并核验可用内存后，才运行 15 秒冻结样本。测试结束必须停止 POC 容器、恢复原服务并再次检查其 `/health`。

## 第二轮定向消融

第二轮冻结 12 个各 15 秒的片段，覆盖经文朗读、经文仍在屏幕但讲员已进入解释、短引用、多经文幻灯片和重复句／语气停顿。每段生成以下五个条件：

1. 真实音频＋真实画面＋transcript candidate；
2. 真实音频＋真实画面，不提供 transcript；
3. 真实音频＋transcript，画面替换为黑屏；
4. 错配音频＋真实画面＋transcript；
5. 精确静音＋真实画面＋transcript。

`round2-corpus.json` 中的类别是选样假设，不是人工 Gold。`human-gold.json` 在每个样本目录中保持 `pending_operator_listening_review`，听审前不计算语义边界或 pause 准确率。

```sh
python3 experiments/omni-annotation-poc/prepare_round2.py \
  --source-video artifacts/resi-live-20260919/mariners-20260919-service-1080p.mp4 \
  --catalog artifacts/sentence-anchor-expanded-poc/20260920-stratified-13/weekly.json \
  --selection experiments/omni-annotation-poc/round2-corpus.json \
  --out artifacts/omni-annotation-poc/20260920-round2

artifacts/omni-annotation-poc/runtime-gemini/bin/python \
  experiments/omni-annotation-poc/run_round2_matrix.py \
  --manifest artifacts/omni-annotation-poc/20260920-round2/corpus-manifest.json \
  --provider gemini --model gemini-3.8-live-extended-thinking \
  --env-file ../Grace-Irvine-Ministry-UI/.env.local \
  --out artifacts/omni-annotation-poc/20260920-round2/results/gemini

python3 experiments/omni-annotation-poc/summarize_round2.py \
  --manifest artifacts/omni-annotation-poc/20260920-round2/corpus-manifest.json \
  --provider gemini=artifacts/omni-annotation-poc/20260920-round2/results/gemini \
  --provider qwen=artifacts/omni-annotation-poc/20260920-round2/results/qwen \
  --out artifacts/omni-annotation-poc/20260920-round2/summary.json
```

Qwen 只跑三个辨识度最高的样本子集。`spark_run_qwen_round2.sh` 延续原服务预检、停止、POC 容器和退出恢复保护；它不是常规生产入口。第二轮实测见 [结果记录](ROUND2-RESULT-2026-09-20.zh.md)。

## 全篇 Gemini sidecar 与 GPT-6 裁判

全篇测试以句子为裁判单位：Gemini 在约 60 秒、重叠约 10 秒的真实音视频窗口中
提出候选；归一化时每句只选择中心点最近的一个 owner window，避免重叠窗口互相投票。
相邻同类句子随后才合并为播放事件。段落只提供上下文，不直接充当事件边界。

输入绑定本周 1,940 秒讲道、39 个窗口、完整候选词时间和 62 个阅读块。词时间及
阅读文本仍是机器候选；`weak_sentence_word_match` 必须保持 `uncertain`。全篇准备、
模型运行和句子归一化命令分别为：

```sh
python3 experiments/omni-annotation-poc/prepare_full_sermon.py \
  --source-video artifacts/resi-live-20260919/mariners-20260919-service-1080p.mp4 \
  --alignment-dir /path/to/dubbing-parent-mlx/source-alignment \
  --sermon-start 1789 --sermon-duration 1940 --source-id 2026-09-20-resi \
  --out artifacts/omni-annotation-poc/20260920-full-sermon

artifacts/omni-annotation-poc/runtime-gemini/bin/python \
  experiments/omni-annotation-poc/run_round2_matrix.py \
  --manifest artifacts/omni-annotation-poc/20260920-full-sermon/full-corpus-manifest.json \
  --provider gemini --model gemini-3.8-live-extended-thinking \
  --env-file ../Grace-Irvine-Ministry-UI/.env.local \
  --out artifacts/omni-annotation-poc/20260920-full-sermon/gemini-results

PYTHONPATH=experiments/omni-annotation-poc python3 \
  experiments/omni-annotation-poc/build_full_sidecar.py \
  --manifest artifacts/omni-annotation-poc/20260920-full-sermon/full-corpus-manifest.json \
  --results artifacts/omni-annotation-poc/20260920-full-sermon/gemini-results \
  --reading-blocks /path/to/reading_blocks.final.json \
  --source-audio /path/to/source_clip.m4a \
  --out artifacts/omni-annotation-poc/20260920-full-sermon/full-sidecar.json
```

输出异常先从保留的原始 response 无损重解析；仍不合格时才以新 attempt ID 重跑，
原始失败不删除。GPT-6 裁判读取 `gpt6-judge-input.json` 的盲化输入，不读取 Gemini
模型名、置信度、自述理由或原始响应。裁判合同见
[GPT-6 sidecar 机器裁判合同](GPT6-JUDGE-CONTRACT.zh.md)。GPT-6 Astra 没有直接音频
输入，因此只能核对英文候选、词时间、真实抽帧和独立声学摘要；`supported` 仍不是
人工 Gold 或发布许可。

手机审阅页支持人工 Gold 采集，但不把页面打开或模型裁判当作人工确认。每句可播放并
选择正式类别，也可标为 `混合／需拆分` 或 `无法判断`；每个窗口另有“已完整听过”标记。
进度只保存在当前浏览器，需用“下载审阅 JSON”或“复制 JSON”显式交回。导出绑定源、
sidecar 与裁判哈希；只有 411 句均为正式类别且 39 窗均已听才写 `humanGold=true`，同时
继续保持 `releaseEligible=false`。
