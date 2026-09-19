# 本地断句研究（Discovery）

分支：`codex/local-prosody-poc`。研究日期：2026-09-19。

后续真实声学特征与Omni听音实验见 [声学POC报告](ACOUSTIC-POC.md)。本页保留第一轮结果，不用后续结果覆盖原实验。

复用 Gemini POC 同一公开讲道的 A/B 两个60秒片段、148/154个去标点英文词。来源、媒体SHA及原时间窗口见 [Gemini实验](../gemini-prosody-poc/README.md)。既有ASR不是人工标准；不改变生产字幕、配音或源稿。

## 实验路径

1. Spark 已有 `Qwen3.8-27B-UD-Q4_K_XL-Unsloth`（llama.cpp）进行文字断句，提示词与Gemini文字条件完全相同；A重复一次。
2. Mac 缓存 `mlx-community/Qwen3-ForcedAligner-0.6B-8bit` 离线对齐词与音频，得到近似词开始/结束时间。
3. 向同一本地Qwen文字模型增加词时间和相邻词间隔，观察句界变化。没有把原始音频交给该文字模型。
4. 输入全零PCM在对齐前拒绝，避免上轮静音＋讲稿产生虚构声音描述的路径。

本轮不评估音色情绪或重音准确率。相邻词间隔是80ms量化的模型估计，不能称为VAD确认的静音。ForcedAligner即使给错稿也可能强行对齐，不验证文字是否说出；全零检测也不等于通用VAD。

## 已验证结果

- A对齐148词，推理0.9211秒；B对齐154词，0.6448秒；模型加载1.3969秒。词序、数量、时间范围与顺序检查通过。不是词时间准确率。
- 静音60秒、960000个PCM样本全为零，在模型调用前拒绝；`model_called:false`。
- Qwen纯文字A两次各14段，但句界集合Jaccard=0.8571（排除强制尾边界），同段数不代表同断句。
- Qwen纯文字B输出8段，出现词索引重叠及无效标点，被结构验证判为失败；不参与句界一致率计算。
- 加入对齐间隔后A输出15段（68.93秒），新增0-based词117、129后的句界，同时合并原词79后的边界。与文字基线Jaccard=0.8；词129边界在纯文字重复中也出现，所以不能把全部变化归因于声音信息。
- B融合输出8段（50.06秒），词覆盖合法但标点为null，仍不符合契约；保留为失败样本，没有静默修复。3个有效结构结果／5次文字模型调用，不是断句准确率。
- 原始Qwen响应虽请求JSON仍带Markdown围栏；保留raw输出，仅剥离完整外层围栏后解析，没有偷偷改写词索引。

最终机器可读比较见 `artifacts/local-prosody-poc/20260919/summary.json`，逐句回听页为同目录 `review.html`。错误结果显示为诊断样本，不可导出为生产字幕。每次请求、响应、模型返回身份及usage保存在忽略目录；没有云模型调用、安装新依赖或修改模型服务。

## 复现

```sh
# 使用既有本机离线模型，需要Metal GPU权限
PYTHONDONTWRITEBYTECODE=1 ~/.local/share/uv/tools/mlx-audio/bin/python experiments/local-prosody-poc/align.py
# 经SSH访问Spark loopback模型服务（不更改服务绑定）
python3 experiments/local-prosody-poc/run.py
python3 experiments/local-prosody-poc/fuse.py
python3 experiments/local-prosody-poc/analyze.py
python3 -m unittest discover -s experiments/local-prosody-poc -p 'test_*.py'
```

输入输出目录目前固定为这次冻结实验。新模型/新输入/新提示词应使用新实验目录，不能覆盖旧结果。已保存raw响应会离线恢复，状态不明的attempt不自动重试。Qwen温度0.2，max_tokens=8192，enable_thinking=false；本地服务仍可能对参数有自身实现，实际响应留存。没有种子控制；复用缓存会影响延迟比较。

对齐模型快照 `0e1a68e91d815300c7c9754b2a7639378b23db15`；runtime为mlx-audio0.3.1、mlx0.32.2、transformers5.0.0rc3；完整模型及输入文件哈希保存在alignment结果内。

下一步需要人工听音标注句界，并加入同一文字不同读法、错稿、噪声与句内长停顿样本。当前实验不能据“与Gemini一致”或“结构通过”宣称更准确。
