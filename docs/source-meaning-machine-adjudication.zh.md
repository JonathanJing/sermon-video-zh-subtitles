# 机器源文裁定（源文语义疑点不再需要人）

2026-10-08 按 Jony 的决定"u076 这种用 AI 判定"加入。工具：[source_meaning_machine_adjudication.py](../scripts/source_meaning_machine_adjudication.py)，测试 [test_source_meaning_machine_adjudication.py](../tests/test_source_meaning_machine_adjudication.py)。

## 解决什么

Sol 复核有时对一个冻结英文单元本身存疑（605 的 `0-u076` "You're filled in the middle of a trial"）：疑点在讲员说了什么，不在译文措辞，重译多少轮都修不好。PR #295 的有界自动修复循环（`scripts/layer2_auto_repair.py`）遇到这种情况会以 `request_source_review` 或 `request_human_review` 停下。过去这一步要人听音频。现在由机器听：

1. 从绑定媒体切出该单元和前后各一个单元的音频（媒体哈希、批准窗口、词时间就是绑定；单元时间相对批准窗口，切片位置是窗口起点加单元时间）；
2. 独立复听：`gpt-transcribe`（走 OpenAI API，不给冻结文本和提示词里的任何原句）和 Spark 上的 Qwen3-ASR（`--listener qwen`），各自转写这段音频；
3. 在每份复听里找到与冻结单元最接近的一段，逐词比对；
4. 所有复听都听到冻结原词时，直接判 `transcript_confirmed`，不调用模型；否则 `gpt-6.1-sol` medium 读冻结文本、每份复听和前后五个单元，在"冻结文本"和"某个复听的措辞"之间选一个，或答 `undetermined`。模型答案里不是任何复听听到的措辞一律拒收（`corrected_text_not_heard`）。

三种结果：

| 结果 | 对 L1 | 对 L2 |
|---|---|---|
| `transcript_confirmed` | 不变 | `meaningNote` 进入译者和复核者的修复说明：按原话直译，不补义 |
| `transcript_corrected` | 生成 `sermon-source-text-review-v1`（`authority: machine_audio_adjudication`），由 `sermon_pipeline.py --source-text-review` 原路应用并重新对齐；L1 身份改变，所有 locale 下游失效（契约要求） | 用新 L1 重跑 |
| `undetermined` | 不变 | 按冻结英文直译，`meaningNote` 说明复听不一致；按 10-08 规则修几轮后放行 |

收据 `receipt.json`（`sermon-source-meaning-machine-adjudication-v1`）记录 source/anchor 规范哈希、媒体哈希、每个单元的切片哈希与媒体时间、每位听者的转写与比对、决定、依据和模型请求缓存。`humanApproval` 固定为 `false`；人工审核仍是独立收据。

## 怎么跑（Mac，媒体在本机）

```sh
python3 scripts/run_with_openai_environment.py --environment dev -- \
  python3 scripts/source_meaning_machine_adjudication.py <含 source.json、anchor.json 的目录> \
    --media <source.json 绑定的媒体文件> --unit 0-u076 \
    --out-dir <新目录> \
    --listener openai [--listener qwen --asr-model-path <Qwen3-ASR 权重>] \
    [--aligned-segments <aligned-segments.json> --source-audio <窗口切片> --asr-reference <asr_reference.json>]
```

- 正式内容用 `--environment prod`。Sol 调用和英文机器裁判一样走 Spark 独占会话准入，要在会话内启动。
- 媒体先按 `source.json` 的 sha256 和大小校验，不符则拒绝。
- 后三个参数一起给时，`transcript_corrected` 会在输出目录写 `source-text-review.json`；`--aligned-segments` 须与 `source.json` 的 transcript 工件哈希一致。随后用 `--source-text-review` 重跑 L1，再重新冻结 605 或当周输入。
- 输出目录不能已存在；付费转写请求有 `--max-api-calls` 上限，结果按音频哈希缓存，未知结果不会自动重发。

## 顺序提醒

对 605 和周六生产：先跑源文裁定，再绑定预算批准收据和 L2 输入。若裁定改了 L1，所有按旧 source/anchor 哈希绑定的收据都要重做；先裁定可以避免返工。
