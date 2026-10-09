# 机器源文裁定（源文语义疑点不再需要人）

2026-10-08 按 Jony 的决定"u076 这种用 AI 判定"加入。工具：[source_meaning_machine_adjudication.py](../scripts/source_meaning_machine_adjudication.py)，测试 [test_source_meaning_machine_adjudication.py](../tests/test_source_meaning_machine_adjudication.py)。

## 解决什么

Sol 复核有时对一个冻结英文单元本身存疑（605 的 `0-u076` "You're filled in the middle of a trial"）：疑点在讲员说了什么，不在译文措辞，重译多少轮都修不好。PR #295 的有界自动修复循环（`scripts/layer2_auto_repair.py`）遇到这种情况会以 `request_source_review` 或 `request_human_review` 停下。过去这一步要人听音频。现在由机器听：

1. 先校验 `anchor.json` 就是 `source.json` 指名的锚点（规范哈希等于 `anchors.artifact.jsonSha256`，且锚点建立在同一份转写上），再从绑定媒体切出该单元和前后各一个单元的音频（媒体哈希、批准窗口、词时间就是绑定；单元时间相对批准窗口，切片位置是窗口起点加单元时间）；
2. 独立复听：`gpt-transcribe`（走 OpenAI API，不给冻结文本和提示词里的任何原句）和 Spark 上的 Qwen3-ASR（`--listener qwen`，身份包含权重、模型元数据、包版本和推理设置），各自转写这段音频。Qwen 权重只在绑定的 Spark 独占会话内加载（`require_bound_model_session`，收据记会话和作业号），所以带 `--listener qwen` 的命令要在 Spark 上、会话内跑，媒体也要在 Spark 上；在 Mac 上选它会以 `qwen_requires_bound_spark_exclusive_session` 拒绝，没有跨主机适配器，缓存里的复听可以不在会话内复用：缓存条目记下生成它的会话，续跑进程没有会话时从条目恢复，收据的 `listeners[].session` 不会变成 null，`sessions` 列出本次用到的全部会话（缓存的和现场的）；
3. 把整段复听与三个单元的冻结词对齐，疑点单元听到的就是前一单元最后一个听到的词与后一单元第一个听到的词之间那一段；相邻单元大半没听到、或疑点词句在片段里别处也出现时，这一段没有边界；
4. 复听者独立于 L1 转写（两种不同的模型，或唯一的模型与 `source.json` 记录的 ASR 模型不同；605 记录的 ASR 模型是 `unknown`，单独一个 `gpt-transcribe` 不算独立），且都在有边界的一段里听到冻结原词时，直接判 `transcript_confirmed`，不调用模型；否则 `gpt-6.1-sol` medium 读冻结文本、每份复听、独立性判断和前后五个单元，在"冻结文本"和"某个复听的措辞"之间选一个，或答 `undetermined`。模型答案里不是任何复听听到的措辞一律拒收（`corrected_text_not_heard`）；选的措辞来自没有边界的复听也拒收（`corrected_text_unbounded`），因为那一段可能夹着前后单元的词。

三种结果：

| 结果 | 对 L1 | 对 L2 |
|---|---|---|
| `transcript_confirmed` | 不变 | `meaning-notes.json`（`sermon-source-meaning-notes-v1`，绑定同一 source/anchor 和收据，记冻结文本哈希）给 L2 修复循环：`load_meaning_notes` 要求同目录的 `receipt.json`（或显式 `receipt_path`）存在、文件哈希等于 `receiptSha256`、绑定一致、逐单元的决定/说明/冻结文本哈希与收据重新投影的结果完全相同（`meaning_notes_receipt_missing` / `meaning_notes_receipt_changed` / `meaning_notes_unit_changed`），再校验冻结文本；手改或过期的 notes 文件不能冒充机器裁定；`repair_instruction` 生成含该单元的组要追加的说明"按原话直译，不补义"；接入修复循环：执行配置 `layer2AutoRepair.sourceMeaningNotes` 指向这份 notes 文件（相对执行配置所在目录，算作输入路径），controller 用本运行的 source/anchor 调 `load_meaning_notes` 后传给 `layer2_auto_repair.drive`；含备注单元的组每次重译简报都附上备注，`quotation_attribution_error` 同一指纹重现时先带备注多修一轮（账本决定 `source_meaning_noted`），再重现才转源文复核 |
| `transcript_corrected`（L1 应用时要给 `--source-text-review-package <被裁定的包目录>`，`apply_review` 用校验器把收据绑到该 source/anchor 和正在处理的母媒体哈希，且收据里每条更正都必须有对应补丁，少一条就拒绝） | 生成 `sermon-source-text-review-v1`（`authority: machine_audio_adjudication`，同一 ASR 段里的多处修正合成一个 patch），由 `sermon_pipeline.py --source-text-review` 原路应用并重新对齐；应用前 `apply_review` 要求证据里恰有这份收据，且每个 patch 正是收据里对应单元的修正，署名、模型、媒体和包绑定都对得上；L1 身份改变，所有 locale 下游失效（契约要求） | 用新 L1 重跑 |
| `undetermined` | 不变 | 同上进入 `meaning-notes.json`，说明复听不一致、按冻结英文直译；按 10-08 规则修几轮后放行 |

收据 `receipt.json`（`sermon-source-meaning-machine-adjudication-v1`）记录 source/anchor 规范哈希、媒体哈希、每个单元的切片哈希与媒体时间、每位听者的转写与比对、独立性判断、决定、依据和模型请求缓存。`humanApproval` 固定为 `false`；人工审核仍是独立收据。复核文件和 `meaning-notes.json` 先生成、先写盘（fsync），`receipt.json` 最后写；每个文件都先写到同目录的 `.<名字>.partial`、fsync 后再以硬链接取得正式名字（已存在即拒绝、不覆盖），中途被杀不会留下半截 `receipt.json` 冒充完成，续跑时丢弃残留的 partial 文件：收据是完成标记，中途失败的目录仍可续跑，上次未完成尝试留下的副产物在续跑时丢弃、按新收据重新生成。`validate_receipt(receipt, source=, anchor=, media_sha256=)` 是收据校验器：只认本模块写出的收据（版本与实现哈希签名、听者身份、每个单元的复听记录、更正文本必须是某位有界听者听到的，`transcript_confirmed` 的 `heardBy` 必须是 `frozen` 或一位与冻结文本一致的听者；收据里存的布尔值不作数：`agreesWithFrozen` 由 `unitTokens` 与冻结文本重新比较，给了 anchor 时每位听者的 `unitTokens` 和 `bounded` 从该听者自己的转写和相邻单元重新定位得出，`listenerIndependence` 由听者模型和收据记的源 ASR 模型重新推导，给了 source 时源 ASR 模型还要与 source 一致，手改这些字段的收据拒收（`receipt_unit_hearings` / `receipt_listeners` / `receipt_source_binding_changed`），"按某位听者确认" 而那位听者听到的不是冻结原词的收据拒收 `receipt_decision_evidence`，写收据时同样拒绝 `confirmed_by_disagreeing_listener`），并核对与所给 source/anchor 规范哈希、媒体哈希和单元冻结文本/时间的绑定；`load_meaning_notes` 和 L1 复核路径都先过它。

## 怎么跑（Mac 只带 openai 复听；加 qwen 复听要在 Spark 会话内）

```sh
python3 scripts/run_with_openai_environment.py --environment dev -- \
  python3 scripts/source_meaning_machine_adjudication.py <含 source.json、anchor.json 的目录> \
    --media <source.json 绑定的媒体文件> --unit 0-u076 \
    --out-dir <新目录> \
    --listener openai [--listener qwen --asr-model-path <Qwen3-ASR 权重>] \
    [--aligned-segments <aligned-segments.json> --source-audio <窗口切片> --asr-reference <asr_reference.json>]
```

- 正式内容用 `--environment prod`。Sol 调用和英文机器裁判（`judge_english_source_for_translation.py`）一样走 Spark 独占会话准入，要在会话内启动。它不走 L2 的 canonical 预算合约（那份合约按 lane 和译者/复核者角色绑定，没有 L1 裁定这一类）；支出在发出前就有界：每个请求带默认请求限额（最多 4096 个输出 token、默认档），新调用数按 `--max-adjudicator-calls` 封顶（默认每个疑点单元一次），收据记录每次调用的费用上界和是否来自缓存。`--model` 只接受 L1 复核路径也接受的模型。
- 媒体先按 `source.json` 的 sha256 和大小校验，不符则拒绝。
- 复听和 Sol 的身份与缓存键都带所选的 OpenAI 项目（环境、项目 ID、凭据别名，不含密钥）：dev 目录下的缓存不会被 prod 复用，收据里能看出是哪个项目付的费。
- 后三个参数一起给时，`transcript_corrected` 会在输出目录写 `source-text-review.json`；`--aligned-segments` 须与 `source.json` 的 transcript 工件哈希一致。随后用 `--source-text-review` 重跑 L1，再重新冻结 605 或当周输入。
- 输出目录可以是上次失败的目录：已付费的复听和模型答案从缓存复用，不再付费；已有 `receipt.json` 的目录拒绝覆盖。付费转写请求有 `--max-api-calls` 上限，结果按音频哈希缓存，未知结果不会自动重发。

## 顺序提醒

对 605 和周六生产：先跑源文裁定，再绑定预算批准收据和 L2 输入。若裁定改了 L1，所有按旧 source/anchor 哈希绑定的收据都要重做；先裁定可以避免返工。
