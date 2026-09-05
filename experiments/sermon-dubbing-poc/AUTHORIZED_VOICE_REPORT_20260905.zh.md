# 授权后的讲员中文声音与训练 POC

2026-09-05，Discovery，分支 `codex/saturday-sunday-chinese-voice-plan`。

用户确认声音可用于训练和配音后，已生成 **77.44 秒的 Eric 原声参考中文 MP3**，并完成 **21 条英文片段、168.48 秒、1 epoch** 的单讲员训练工程试跑。保存了真实更新的 checkpoint。当前没有人工听感通过结论、独立证道验证或整篇视频同步结论。

## 授权、参考与数据

本地授权记录为 `artifacts/sermon-dubbing/authorizations/2026-09-05-user-confirmation.json`，绑定 8 份已盘点素材的 ID/hash，包含声音训练与中文配音用途。本次选 `ZDQwL3K-A44`，保留 5 份已有保护测试集及可能重复的 8 月 9 日证道；没有用更换 URL 的方式把保护数据放入训练。

讲员标签来自这篇原音中“Eric / senior pastor”的自述，真实对齐位置约为片内 4.56–6.88 秒。当前仅建立这位讲员的候选组；尚未运行整篇自动 diarization，也没有把 8 月 30 日未确认讲员的素材混入本轮。

声音参考取自同一原音的 **11.20–24.16 秒**，24 kHz 单声道 WAV，12.96 秒；对应英文由真实音频 ASR 与 ForcedAligner 定位。单独回转写参考音频后，英文在忽略大小写和标点时与参考文本一致。参考材料已记录 hash，但干净程度与讲员相似度仍需人听。

训练候选从原片前 5 分钟提取：Qwen3-ASR 0.6B 重新转写 → Qwen3-ForcedAligner 0.6B 真实定位 → 完整句子分组 → 与现有英文原稿作内容一致性检查 → 4–15 秒预算及信号检查。保留 21 个候选和排除记录。60 秒处理窗口的边界、引用时的声音变化、音乐/混响与人物归属仍需逐段复核。

这次训练输入标记为 `engineering_training_smoke`，`productionTrainingAdmission=false`。正式审核准入数仍为 0；实际执行的工程训练样本数另记为 21。没有将候选、机器审核或这次训练结果标为人工 Gold。

## 已完成的原声参考配音

| 项目 | 实测 |
|---|---|
| 中文内容 | 8 月 23 日阅读稿 blocks 9–10，398 字符，与预设对照完全一致 |
| 模型 | `mlx-community/Qwen3-TTS-12Hz-1.7B-Base-8bit` |
| revision | `e7dd0585652209fa0d7783659aad4e8a324de11c` |
| 生成方式 | 英文原声参考＋准确英文文本，生成普通话；未微调基线 |
| 输出 | 5 组，77.44 秒，MP3 48 kHz / 单声道 / 192 kbps |
| 响度与真峰值 | 编码后 -18.22 LUFS / -1.75 dBTP |
| 回转写 | 全部中文内容得到覆盖，仅“作／做、世／事”两处同音字差异候选 |
| SHA-256 | `de3b1017a4204f1ae519e1aa7f3668767372d5f127994d378ad738429be5aafc` |

生成包在 `artifacts/sermon-dubbing/2026-09-05-authorized-voice-poc/`。`eric_clone.mp3`、`experiment.json`、`speaker-profile.json`、`reference-asr-check.json`、`asr-screening.json` 保存完整输入与证据。

原声参考版比 107.20 秒的 Uncle_Fu 预设版快。两者同时改变了模型入口和声音条件，不能把差异归因于训练；这里的 Eric 参考版本身没有训练权重。机器回转写不能证明中文自然度、人物音色相似度或没有细微发音问题。

## 真实训练回执

| 项目 | 实测配置 / 结果 |
|---|---|
| 机器 | DGX Spark，GB10；新建隔离容器与 venv，保留已有服务 |
| 基座 | `Qwen/Qwen3-TTS-12Hz-1.7B-Base`，revision `fd4b254389122332181a7c3db7f27e918eec64e3` |
| Speech tokenizer | `Qwen/Qwen3-TTS-Tokenizer-12Hz`，revision `7dd38ad4e9bad454aae9cd937d0cd577604fe229` |
| 官方训练代码 | Qwen3-TTS commit `022e286b98fbec7e1e916cb940cdf532cd9f488e` |
| 输入 | 21 条英文原音＋对应英文标签，168.48 秒；同一篇证道，无独立验证集 |
| 参数 | batch 1，梯度累积 4，学习率 `2e-6`，1 epoch，seed 42，bf16 / SDPA |
| 资源边界 | 容器 32 GiB 内存上限、6 CPU；不停止其他任务 |
| 耗时 | speech token 编码约 11.7 秒；训练与保存约 70.0 秒，均不含安装和模型下载 |
| Loss | 21 个 batch 均为有限值；首个 13.9633，末个 11.7765，不能据不同 batch 的数值比较推断质量提升 |
| 权重变化检查 | `talker.model.layers.0.self_attn.q_proj.weight` 有 201,126 个元素改变，最大绝对差约 `2.29e-5`；排除了仅写入 speaker slot 的假阳性 |
| checkpoint SHA-256 | `75d28ce6022b3df3a72df3dd6dbc01e53f584d685770d60ea04b341920968c9a` |

完整 checkpoint 保留在 Spark 的 `~/dgx-spark-benchmark/results/sermon-voice-poc-20260905/checkpoints/checkpoint-epoch-0/`。本地 `spark-training-smoke/` 中已复制训练报告、日志、输入清单与兼容性补丁。权重和声音媒体不进入 Git。

实现沿用 [Qwen 官方单讲员训练流程](https://github.com/QwenLM/Qwen3-TTS/blob/022e286b98fbec7e1e916cb940cdf532cd9f488e/finetuning/README.md)：先编码音频，再训练并导出 `eric_pilot` speaker。工程脚本为 [run_qwen_training_smoke.py](./run_qwen_training_smoke.py)，输入验证不更改上游候选的审核状态。

## 运行环境适配与证据边界

Spark 使用已有 `nvcr.io/nvidia/pytorch:26.06-py3` 镜像，PyTorch 2.13 开发版 / CUDA 13.3，transformers 4.57.3、accelerate 1.12.0、qwen-tts 0.1.1。只在本次工作目录的 venv 增加依赖。

首轮启动遇到可选 25Hz 模块提前导入缺少的 torchaudio；在隔离副本中将导入移到真正使用该模块的方法内，本次 12Hz 编码/模型逻辑保持原样。后续因未配置 TensorBoard 目录启动失败，训练脚本改为 stdout 记录每个 batch。还显式采用 SDPA、固定 seed、拒绝非有限 loss。原始官方文件、hash、补丁和失败日志均保留。

MLX 的模型类型/tokenizer 警告，以及 Spark 的可选 ONNX 设备发现/弃用提示也已记录。此次实际 CUDA 编码与训练通过，不据这些工程成绩宣布整个依赖组合可直接生产。

## 中文训练后验证

`probe_qwen_training.py` 在相同 Torch 环境中，用同一中文、相同分组与采样参数比较 Base 原声参考和训练后的 speaker。除了权重，条件输入也会从参考音频变为导出的 speaker slot，因此不能把所有变化简单归因于某个训练参数。

第一次使用 repetition penalty 1.5 时，Base 对照的第 5 句触发输出异常检查，未形成通过的完整对照包；已保留日志和前 4 句。第二轮使用 1.05、最多 512 个新 token，两版均生成完整 WAV 并编码、完整解码和回转写。

| 第二轮 Torch 输出 | 时长 | 回转写筛查 | 本次处置 |
|---|---:|---|---|
| 未微调 Base | 94.88 秒 | 首段有重复、漏读与中英文混杂；部分后续专名也出现问题 | 保留为诊断材料，不放入普通试听列表 |
| 训练后的 `eric_pilot` | 78.64 秒 | 仅“仍／人、作／做”两处差异候选；没有前者的大段重复和混杂 | 加入待人工听审的试听列表 |

两版编码后响度均为 -18.28 LUFS，true peak 均为 -1.75 dBTP。训练版 MP3 SHA-256 为 `2561c15cbb4f76fa6206bf3cc2439ebb333de429ab89b3c5867b3cc249bae8ad`。完整文件与筛查见本地 `spark-chinese-audio/`；原始 WAV、cue 与运行记录见 `spark-training-smoke/chinese-probe-v2/`。

**本轮训练输出在这一固定稿上的机器内容筛查更稳定。** 这不证明跨证道泛化、自然度或讲员相似度已达标。尤其 Base 的参考条件与训练后 speaker slot 不同，未微调 MLX 路径本身也已得到内容完整的输出，仍需匿名试听后决定保留哪条声音路径。

## 播放与下一步

本地播放器展示训练试跑、原声参考与预设音色三版，切换时暂停、回到开头并更新音色标签。实际浏览器已播放原声参考 MP3 超过 60 秒；切换预设后确认暂停、位置 0、偏移 0、标签正确。

训练版也在浏览器实际播放并暂停于 26.367843 秒，后退 0.25 秒到 26.117843 秒。三份试听 MP3 的 HTTP 完整下载 hash 和 Range 读取均通过；320 像素布局的三个选择按钮均在视口内。15 项 Python 测试、4 项 Node 测试、浏览器脚本语法和文档检查通过。没有运行未修改的根业务或实时字幕 POC 全量测试。

下一步是试听中文与参考原音，补逐段讲员/声音质量审核，增加独立证道后再扩大训练。现场视频的真实时间轴、绝对定位与全长同步尚未实现；Firebase 也尚未上传或部署。微调按钮只修正当前播放位置，不替代时长适配。
