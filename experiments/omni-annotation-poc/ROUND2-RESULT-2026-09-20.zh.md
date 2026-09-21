# Omni 隐形辅助标注第二轮 POC（2026-09-20）

状态：**机器消融完成，12 段人工听审 Gold 待补；Discovery，不可进入生产时间轴。**

## 冻结范围

- 12 个各 15 秒片段，来源仍为同一份 SHA-256 `728f864e92ea08dbce249249369016e0fee47950ec4e6dcb60cd6d83185e8caf` 的完整礼拜视频。
- 选样覆盖实际经文朗读、经文画面仍在但已经解释、回到讲解、短引用、多经文幻灯片，以及没有经文画面的重复句／语气停顿。
- 每段五个条件：完整输入、无 transcript、无画面、错配音频、精确静音，共 60 个 Gemini case。
- Qwen 复测三个辨识度最高的样本：`Revelation 2:1` 朗读、`Revelation 2:4` 画面保持但处于解释、重复句／停顿，共 15 个 case。
- transcript 来自现有阅读版候选，不是逐字人工 Gold。每段 `human-gold.json` 仍为 `pending_operator_listening_review`。

语料 manifest、媒体哈希、模型原始响应和汇总保存在忽略目录 `artifacts/omni-annotation-poc/20260920-round2/`；可复现实验定义在 `round2-corpus.json`。

## 夹具级结果

这里的“通过”只表示输出可解析，并且没有违反该 case 由夹具固定的模态事实；不表示读经边界或 pause 已经人工判为正确。

| 模型／条件 | 通过 | 失败 | 延迟中位数 |
|---|---:|---:|---:|
| Gemini：真实音视频＋transcript | 12/12 | 0/12 | 18.890 秒 |
| Gemini：真实音视频，无 transcript | 5/12 | 7/12 | 18.938 秒 |
| Gemini：真实音频＋transcript，黑屏 | 3/12 | 9/12 | 19.423 秒 |
| Gemini：错配音频 | **0/12** | 12/12 | 19.916 秒 |
| Gemini：精确静音 | **2/12** | 10/12 | 18.770 秒 |
| Qwen 子集：真实音视频＋transcript | 3/3 | 0/3 | 106.177 秒 |
| Qwen 子集：真实音视频，无 transcript | 3/3 | 0/3 | 102.132 秒 |
| Qwen 子集：真实音频＋transcript，黑屏 | 2/3 | 1/3 | 145.401 秒 |
| Qwen 子集：错配音频 | **0/3** | 3/3 | 55.588 秒 |
| Qwen 子集：精确静音 | **0/3** | 3/3 | 100.598 秒 |

Gemini 60 个请求的实测推理时间合计 1,243.963 秒，中位数 19.186 秒。Qwen 15 个请求的实测推理时间合计 1,412.767 秒，中位数 102.132 秒；冷启动另计，不包含在单条延迟。Qwen 响应共记录 173,693 prompt tokens、34,357 completion tokens，合计 208,050 tokens。

## 语义观察

### 正面信号

- `s05-revelation-2-1-quote`：Gemini 给出 0–5 秒讲解、5–15 秒读经；Qwen 给出 0–4 秒过渡、4–14.5 秒读经。两者均识别 `Revelation 2:1`，但仍只是候选边界。
- `s08-revelation-2-4-visible-explanation`：Qwen 在有 transcript 和无 transcript 两种真实输入下，都把整段标为 `sermon_explanation`，没有仅因屏幕仍显示经文就判为读经。
- `s12-rhetorical-repeat`：两者都识别为讲解而非经文；Qwen 给出停顿候选，Gemini 没给。没有听审 Gold，不能据此选择哪一个正确。

### 失败与不稳定

- Gemini 在 `s08` 的完整输入中把约 2.4–11 秒标为 `scripture_reading`，而冻结 transcript candidate 表明该段是在解释“离弃起初的爱”。这是 transcript／画面与音频关系仍不稳的候选错误，需人工听审最终确认。
- Gemini 在 `s01-peter-quote` 返回 0.05–0.12 秒的读经区间，明显暴露出时间单位或边界输出失常；结构 schema 原先仍会接受这种极短区间，因此“可解析”不能代替语义 QA。
- Gemini 无 transcript 时只有 5/12 能正确承认 transcript 未提供；黑屏时只有 3/12 能正确承认无视觉。
- Qwen 在完整输入和无 transcript 子集上证据字段较规整，但有一个黑屏 case 因重复推理达到 4,096 completion-token 上限而截断。
- Qwen 的 `s05` 错配 case 同样达到 token 上限；截断前已经错误声称音频匹配，并准备输出 `audio=true` 的读经区间。
- 两个模型在错配音频下都是 0 个 case 通过。Gemini 静音只通过 2/12；Qwen 静音 0/3。二者都不能充当“我是否真的听到了这段声音”的权威。

## 当前决策

1. 不再横向增加 Omni 模型。第二轮已把主要限制定位为**模态真实性和证据归因**，不是模型列表不够长。
2. 英文逐字稿和词级时间仍由独立 ASR／forced alignment 管线负责；语音存在性、静音和 pause 由独立声学门控负责。
3. Gemini 可保留为经文引用、朗读／解释状态和人工导航的快速 sidecar，但只有在独立声学门控确认存在匹配语音后才运行或采纳候选。
4. Qwen 对 `s08` 困难负例表现优于 Gemini，但速度、长思维截断和负例失败使其不适合实时或时间权威；最多作为离线争议片段复核候选。
5. 下一门槛不是继续调用模型，而是完成 12 段 `human-gold.json`：逐字英文、读经／解释区间和可听停顿。完成前不报告准确率、召回率或边界误差。

## 运行与恢复证据

- Gemini 使用 Google GenAI SDK `2.24.0`；API key 只从既有环境文件临时读取，未写入 request、response、result 或 Git。
- Qwen 复用上一轮冻结的官方 BF16 checkpoint 和 vLLM `0.20.0`；实际 served model ID 为 `qwen3-omni-30b-a3b-thinking`。
- Qwen 前原 `llama-server.service` 健康；实验结束后恢复为 `active`，`/health` 返回 `{"status":"ok"}`，模型 ID 回到 `Qwen3.8-27B-UD-Q4_K_XL-Unsloth`，`omni-poc-qwen` 容器已停止。
- `python3 -m unittest discover -s experiments/omni-annotation-poc -p 'test_*.py' -v`：15 项通过。
