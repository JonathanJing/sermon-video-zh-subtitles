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
| `transcript_corrected`（L1 应用时要给 `--source-text-review-package <被裁定的包目录>`，`apply_review` 用校验器把收据绑到该 source/anchor 和正在处理的母媒体哈希，且收据里每条更正都必须有对应补丁，少一条就拒绝） | 生成 `sermon-source-text-review-v2`（`authority: machine_audio_adjudication`，同一 ASR 段里的多处修正合成一个 patch；v1 仍是既有对话式复核的合同，只认 `user_directed_conversation_review`，标成 v1 的机器复核拒收 "requires the sermon-source-text-review-v2 contract"，对话式复核在 v1、v2 下都有效，来源记录里的 `schemaVersion` 照抄复核文件），由 `sermon_pipeline.py --source-text-review` 原路应用并重新对齐；应用前 `apply_review` 要求证据里恰有这份收据，且每个 patch 正是收据里对应单元的修正，署名、模型、媒体和包绑定都对得上；L1 身份改变，所有 locale 下游失效（契约要求） | 用新 L1 重跑 |
| `undetermined` | 不变 | 同上进入 `meaning-notes.json`，说明复听不一致、按冻结英文直译；按 10-08 规则修几轮后放行 |

收据 `receipt.json`（`sermon-source-meaning-machine-adjudication-v2`）记录 source/anchor 规范哈希、媒体哈希、每个单元的切片哈希与媒体时间、每位听者的转写与比对、独立性判断、决定、依据、模型请求缓存和本次花费所依据的预算授权（`budget`：授权文件哈希、批准收据哈希、账本根目录、总上限、请求限额；只回放缓存、没有新付费调用的运行记 `null`；v2 收据必须有这个字段，字段存在则逐项核对：两个文件哈希是 64 位十六进制、账本根目录是以 `budget` 结尾的绝对路径、总上限是账本接受的三项正整数、请求限额是受支持的档，缺字段、任何一项为空或走样都拒收 `receipt_budget`）。v1（`sermon-source-meaning-machine-adjudication-v1`）是此前的合同：那时模型裁决还不从请求缓存重新推导，也没有预算记录。v1 收据照旧可读，按它写出时的规则校验：模型决定的行只要求带 `request`，不要求也不读 `cache/`；它不能带 `budget` 字段（带了拒收 `receipt_budget`）；下文的缓存核对、完整问题核对、切片和派生听者字段的逐项核对只适用于 v2。写出的收据一律是 v2，L1 复核路径和 `load_meaning_notes` 两种版本都认。`humanApproval` 固定为 `false`；人工审核仍是独立收据。复核文件和 `meaning-notes.json` 先生成、先写盘（fsync），`receipt.json` 最后写；每个文件都先写到同目录的 `.<名字>.partial`、fsync 后再以硬链接取得正式名字（已存在即拒绝、不覆盖），中途被杀不会留下半截 `receipt.json` 冒充完成，续跑时丢弃残留的 partial 文件：收据是完成标记，中途失败的目录仍可续跑，上次未完成尝试留下的副产物在续跑时丢弃、按新收据重新生成。`validate_receipt(receipt, source=, anchor=, media_sha256=, cache=)` 是收据校验器：只认本模块写出的收据（版本与实现哈希签名、听者身份、每个单元的复听记录、更正文本必须是某位有界听者听到的，`transcript_confirmed` 的 `heardBy` 必须是 `frozen` 或一位与冻结文本一致的听者；收据里存的布尔值不作数：`agreesWithFrozen` 由 `unitTokens` 与冻结文本重新比较，给了 anchor 时每位听者的 `unitTokens` 和 `bounded` 从该听者自己的转写和相邻单元重新定位得出，`listenerIndependence` 由听者模型和收据记的源 ASR 模型重新推导，给了 source 时源 ASR 模型还要与 source 一致，手改这些字段的收据拒收（`receipt_unit_hearings` / `receipt_listeners` / `receipt_source_binding_changed`），"按某位听者确认" 而那位听者听到的不是冻结原词的收据拒收 `receipt_decision_evidence`，写收据时同样拒绝 `confirmed_by_disagreeing_listener`），并核对与所给 source/anchor 规范哈希、媒体哈希和单元冻结文本/时间的绑定。v2 收据里由模型决定的单元还要带 `cache`（输出目录下的 `cache/`，收据每行 `request` 指名其中的请求缓存文件）：校验器按文件哈希和 `requestSha256` / `responseSha256` 核对那份缓存，核对请求里的模型、推理档、系统提示哈希、问题的单元与冻结文本和各听者的转写与收据一致；给了 anchor 时再从 anchor 和收据重建完整的问题（前后各 5 个单元的上下文、听者独立性、切片的单元范围和时长、每位听者听到的整段、落在该单元的那段、相似度、是否一致、是否被相邻单元夹住和边界），要求与缓存里的问题完全相同，别的夹具或别的上下文问出来的缓存即使原始转写相同也拒收 `receipt_model_question_changed`；同时每行的切片必须是 anchor 里该单元连同前后各 1 个单元的范围和时间（否则 `receipt_unit_not_in_anchor`），每位听者落在该单元的那段文字、相似度和边界也从转写重新定位并逐项比较（`receipt_unit_hearings`）。然后用缓存里的响应重走 `_checked_answer` 得到裁决，决定、`heardBy`、更正文本、说明和依据五项必须与收据逐字相同；把 `undetermined` 改成"按某位有界听者更正"、改一句说明、改一份缓存响应或缺少缓存都拒收（`receipt_verdict_not_from_model` / `receipt_model_response_changed` / `receipt_model_response_missing` / `receipt_model_question_changed`）；`load_meaning_notes` 和 L1 复核路径都先过它，并传入收据旁的 `cache/`，所以搬运收据要连同整个输出目录。

## 怎么跑（Mac 只带 openai 复听；加 qwen 复听要在 Spark 会话内）

```sh
python3 scripts/run_with_openai_environment.py --environment dev -- \
  python3 scripts/source_meaning_machine_adjudication.py <含 source.json、anchor.json 的目录> \
    --media <source.json 绑定的媒体文件> --unit 0-u076 \
    --out-dir <新目录> \
    --listener openai [--listener qwen --asr-model-path <Qwen3-ASR 权重>] \
    --budget-authorization <sermon-source-meaning-budget-authorization-v1 文件> \
    [--aligned-segments <aligned-segments.json> --source-audio <窗口切片> --asr-reference <asr_reference.json>]
```

先在同一个 launcher 环境下用同样的参数加 `--print-budget-binding` 打印这次运行的预算绑定（不动输出目录；绑定含所选 OpenAI Project，没有 launcher 以 `openai_environment_launcher_required` 拒绝），把它原样写进授权文件和批准收据。

- 正式内容用 `--environment prod`。没有绑定的 API 请求在派发前拒绝（AGENTS.md 的运行时模型策略）：付费的复听和 Sol 调用只能经 `--budget-authorization` 指定的预算授权派发，没有它的运行只能回放缓存，第一个缓存未命中就以 `budget_authorization_required` 停下，不留下任何待对账的半截记录。授权文件 `sermon-source-meaning-budget-authorization-v1` 的形状和 L1 源文预算（`sermon-source-budget-authorization-v1`）一样：`binding`（source/anchor 规范哈希、排序后的疑点单元、代码闭包哈希 `codeIdentitySha256`、所选 OpenAI Project `route`（environment / projectId / credentialAlias，不含密钥）、账本根目录 `<out-dir>/budget`）、`authority`（`approvalSha256`、`globalBounds` 的请求数/墙钟/费用总上限、`requestLimits`）和相对路径 `approvalReceipt`；批准收据 `sermon-source-meaning-budget-approval-v1` 重复绑定、总上限和请求限额，并带 `humanApproval: true`、`decision: approved`、`operatorEvidence`、`reviewedBy`、`reviewedAt`。绑定对不上（换了单元、换了代码、换了输出目录、换了 dev/prod 路由）拒收 `budget_authorization_binding_changed`，批准收据哈希或内容对不上拒收 `budget_approval_not_bound`；为 dev 批准的授权在 prod 下装不进来，也回放不了。授权通过后，两种付费调用都经 `sermon_source_budget.SourceBudget` 的一本账本（`<out-dir>/budget/source-budget.json`）派发，账本在每次预留、派发和记录返回之前都重读授权文件、批准收据和当前代码闭包：装入后被换掉的文件拒收 `budget_authorization_changed`，代码变了拒收 `budget_authorization_binding_changed`，账本都不动。派发规则：复听按时长计费的分钟数和 300 秒墙钟预留（`asr.NNNN`，按首次听到的顺序编号并记在 `cache/openai/operations.json`，续跑时同一段音频同一编号），Sol 调用按输入上界加 `max_completion_tokens` 的最坏费用预留（`judge.<请求哈希>`，账本行的身份是模型、路由加请求（顶层 `model` 是传输层计费要读的字段），dev 下付费的答案不会回放给 prod 的运行：`source_operation_identity_changed`），超出总上限在派发前以 `source_budget_exhausted` 拒绝，已返回的响应按请求身份回放，结果未知的请求不自动重发；进程在账本记下已返回响应之后、请求缓存文件写出之前死掉会留下缓存的 `.started.json` 标记，续跑时裁定器不把它当未知结果：有预算就从账本回放那条已核验的响应（账本没见过的标记说明从未发出，照常派发并计一次调用；账本里仍是未确认的拒绝 `source_provider_outcome_unknown`），用 `reconcile_returned_response` 绑进缓存再继续，没有预算的运行则照常停在"Unknown L1 request outcome"；复听同理：进程在账本记下返回文本之后、`cache/openai/<key>/` 写出 response/outcome 之前死掉留下的 `started.json`，续跑时先经账本回放再用 `CallCache.reconcile` 绑回标记（标记里的请求或已记录的响应不一致则拒绝），没有预算的运行在碰到标记之前就以 `budget_authorization_required` 停下；账本本身要求 Spark 独占会话准入，和英文机器裁判（`judge_english_source_for_translation.py`）一样要在会话内启动。请求限额取授权里批准的档（`requestLimits`，默认档最多 4096 个输出 token），新调用数仍按 `--max-api-calls` / `--max-adjudicator-calls` 封顶（后者默认每个疑点单元一次）；上限只数新的付费请求：账本里已返回的响应回放不计数，所以 `--max-api-calls 0` 的续跑也能收回已付费的结果，而账本没见过的片段或问题在编号、预留之前就以 `listener_call_cap_reached` / `adjudicator_call_cap_reached` 拒绝。收据记录每次调用的费用上界和是否来自缓存。它不走 L2 的 canonical 预算合约（那份合约按 lane 和译者/复核者角色绑定，没有 L1 裁定这一类）。`--model` 只接受 L1 复核路径也接受的模型。
- 媒体先按 `source.json` 的 sha256 和大小校验，不符则拒绝。
- 复听和 Sol 的身份与缓存键都带所选的 OpenAI 项目（环境、项目 ID、凭据别名，不含密钥）：dev 目录下的缓存不会被 prod 复用，收据里能看出是哪个项目付的费。
- 后三个参数一起给时，`transcript_corrected` 会在输出目录写 `source-text-review.json`；`--aligned-segments` 须与 `source.json` 的 transcript 工件哈希一致。随后用 `--source-text-review` 重跑 L1，再重新冻结 605 或当周输入。
- 输出目录可以是上次失败的目录：已付费的复听和模型答案从缓存复用，不再付费；已有 `receipt.json` 的目录拒绝覆盖。付费转写请求有 `--max-api-calls` 上限，结果按音频哈希缓存，未知结果不会自动重发。续跑用同一份授权（绑定含输出目录）；`cache/` 和 `budget/` 是收据的证据，复制收据时整个目录一起复制。

## 顺序提醒

对 605 和周六生产：先跑源文裁定，再绑定预算批准收据和 L2 输入。若裁定改了 L1，所有按旧 source/anchor 哈希绑定的收据都要重做；先裁定可以避免返工。
