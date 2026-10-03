# 同行 Agent 操作说明 STE 审核（只读）

审核日期：2026-10-03。代码基线：dev `b638dc9d30cf1ade606bd2c411074d5806564bd9`。PR #228 的页面说明修订不计为本次新发现。

已安装技能：`$CODEX_HOME/skills/asd-ste100`（本机默认 ~/.codex），v0.4.0，来源 `danyuchn/asd-ste100-skill` commit `7d4a135a199a5d7447c4886bcd7ffe742a627bc9`。此前已检查 SKILL.md、参考资料及唯一 Python 脚本，并核对安装文件与来源一致。本次使用 Strict 审英文指令、STE-flavored 审英文解释；中文仅评清晰度。没有官方受控词典，不能宣称英文 STE 认证或中文 STE 合规。

## 结论与优先顺序

发现两个高影响的 L2 提示词歧义，以及三项文档/CLI 交接说明问题。它们是静态阅读发现，不代表已观测到模型错误。Sol 仍是 REVIEWER-EDITOR，可以修订 Astra 文本后作语义审核；不建议改成只读 strict-verifier，也不建议添加第三道模型门禁。

### 1．高：短口播与通用经文指令互相冲突

位置：`scripts/run_target_language_models.py:66–73, 702–718, 763–777`；规则依据 `docs/target-language-astra-sol-production.zh.md:40`。

原句（references_only 分支）：`For Bible passages, cite the book, chapter, and verse when known ...`。短口播分支禁止新增讲员未说出的经文书名、章节及引用，但随后无条件拼接上述通用经文指令。两个分支相遇时，“知道章节”与“讲员是否说出章节”的优先级不清楚。此问题在 translator 与 reviewer-editor 中都存在；仅在 references_only 与短口播模式组合时成立，不能推断所有生产策略都有该冲突。

建议方向：明确完整阅读稿和口播适配的经文引用范围。例如口播指令：`Keep only the Bible references that the speaker said. Do not add a book name, chapter, or verse.` 这只是待决措辞，不能先据此更改完整阅读稿规则。

需用户决定：未说出的经文引用是否只允许放在阅读稿/元数据，口播是否一律不得补充？确定后应给提示词/策略新版本，重算请求身份并使受影响缓存失效，不复用旧请求结果冒充新审核。回归须覆盖已知但未说出的引用、实际说出的引用、直接引文与释义，以及短口播/完整稿两模式。

### 2．高：修好一个问题后“leave issues empty”可能清掉其他问题

位置：`scripts/run_target_language_models.py:787–789`；确定性消费门禁 `826–841`。

原句：`if you correct an Astra draft issue in the final text, describe that correction in evidence and leave issues empty.` 同段又要求数组只包含未解决问题，并要求任何未解决 concern 都 fail。前句没有说明“仅当全部问题解决”，可能让修复一个问题的 reviewer-editor 清空仍未解决的问题。代码会拦截非空 issues/uncertainty，但不能识别模型遗漏的问题。

建议替换：`Describe corrected issues in evidence. Keep every unresolved concern in uncertainty or issues. Leave issues empty only when no issue remains. Mark status fail if any concern remains unresolved.` 保留修订权和原 fail 强度，不改 JSON 键、枚举或验证逻辑。

需用户决定：是否批准上述语义澄清进入下一提示词版本？这不是纯排版修改。应绑定新 payload/策略版本，在新 revision 重跑受影响组；回归至少包括两问题只修好一个、全部修好、剩余不确定性及未能修正的事实错误。不要把已有缓存直接换标签。

### 3．中：locale 独立性与运行容量上限需区分

位置：`AGENTS.md:30`、`docs/multilingual-production-interfaces.zh.md:65`；实现 `scripts/canonical_layer2_controller.py:37,198–233`；现有限制已见 `docs/canonical-layer2-controller.zh.md:39–40`。

原句：`Keep each locale independent so one locale's issue does not stall the others.` 接口说明也说待审批 locale 不阻断其他 locale。当前 fixed L2 controller 同一 production run 至多一个 active locale job，uncertain owner 也占名额，因此其他 locale 不能在该名额未释放时派发。

建议英文：`Keep approval dependencies separate for each locale. The current controller permits one active locale job per production run. An uncertain job occupies that slot until reconciliation.` 中文建议说明“审批依赖独立”不等于“运行资源完全隔离”。保留 release-plan join 的既有条件。

需用户决定：目前是否接受该容量限制？若接受只澄清文档；若要求跨 locale 并行，是另一项调度实现工作，不能靠重写指令完成。本审核没有要求提高并发数。

### 4．中：renderer 文件身份与声音身份混写

位置：`docs/formal-layer3-renderer.zh.md:9,11`；实现 `scripts/render_formal_target_language_speech.py:49,249–328,494–535`。

原句：`新 renderer SHA 仍须与缓存相符，旧产物不能因为 batch=1 而忽略代码身份变化。`代码的 `rendererSha256` 使用固定 `RENDERER_SOUND_IDENTITY_SHA256`，另对 batch>1 绑定实现文件身份，并对明确列出的旧声音身份进行兼容判断。笼统说“任何代码变化均不可复用”不能准确解释当前行为。

建议中文：“缓存必须通过当前 producer 的完整身份核验。声音身份使用 rendererSha256；批处理实现身份另行绑定。仅可按代码明确列出的兼容规则复用旧身份；不得忽略、手改或跳过哈希检查。”保留 job、文字、voice、checkpoint、policy 与 WAV/commit 的全部约束。

需决定：是否只补充现有兼容边界？不建议扩大兼容名单。若未来改变声音身份或名单，需要验证不兼容拒绝、明确兼容接受及 WAV/commit 篡改拒绝，不能只测文件名一致。

### 5．中：--unit-instructions 交接信息不足

位置：`scripts/render_formal_target_language_speech.py:1148–1159`、`docs/formal-layer3-renderer.zh.md:5`；实际输入契约 `361–396,732`。

help 原句为 `Source-bound per-unit pronunciation and pause instructions`；文档解释了全局 --instruct，但未说明如何构造 --unit-instructions。真实 JSON 必须是 `sermon-unit-delivery-instructions-v1`，绑定 targetLocale 与 speechJobJsonSha256；每行需已存在且不重复的 translationGroupId、approvedTextSha256、非空 instruction 与 operatorEvidence。可选 spokenText 只支持 zh-Hans，并只允许代码确认的标点及启示录 3:16 表达等价处理，不能任意改词。单元 instruction 覆盖该单元全局 --instruct。

建议 help：`JSON instructions bound to the job, locale, and approved text. See the input schema and override rules.` 文档补完整现有字段与拒绝条件，保留 instruction 变化应使用新 job 目录的要求。此项可作说明修订；不要扩展 spokenText 等价范围或更改缓存键。

## 按要求顺序检查的结果

1. **AGENTS / 四层交接**：已读 AGENTS.md 和 multilingual-production-interfaces.zh.md。人工来源审核、locale 文本审核、音频完整听审及 L4 验收各自独立，机器审核不能变成人工批准，preview 不得走正式产物；这些边界清楚。新问题仅见第 3 项。仓库 .agents/skills 的 live-caption-zh-fallback 范围属于现场字幕，不作为离线生产额外授权。
2. **缓存恢复**：已读 canonical-layer2-cache-recovery.zh.md 与 canonical_layer2_cache_recovery.py，并核对 controller/reconciliation 路径。expected state revision、三类锁、原请求与代码身份、全部组返回缓存、零模型调用、冲突不覆盖、恢复后独立 reconciliation 与 humanApproval=false 均与说明一致。保留 failed/unknown 原状态，不把 recovery 当成人工批准。通过本次清晰度/静态契约检查。
3. **L2 prompts**：已读 run_target_language_models.py 的 translator、reviewer-editor、repair/cache/CLI 路径及 target-language-astra-sol-production.zh.md。新发现第 1、2 项。repair 仍绑定原来源和请求身份；started marker 无响应不是自动重试许可；已返回 raw 先落盘再验证。没有建议修改状态、JSON、正则或模型职责。
4. **L3 CLI / 恢复**：已读 render_formal_target_language_speech.py 及 formal-layer3-renderer.zh.md，检查 --instruct、--unit-instructions、--reuse-from、--speculative-from、--batch-size。新发现第 4、5 项。正式人工门禁、预览不能授予正式批准、WAV/commit 完整性及单元文本匹配边界清楚；batch 默认值区分生产与 Dev profile，不据历史日期段落声称实现缺陷。
5. **DAG 日志 / 诊断**：已读 sermon_agent_diagnostics.py 与 workflow-accounting-log-contract.zh.md。诊断仅提出 hypotheses/proposals，冻结脱敏证据是数据而非授权，只有三类读取工具；本地 recommendation validation 不授予执行权。当前代码还包含显式授权的 live client 分支，不能把 offline 默认误说成永远不会联网。unknown outcome 保留 checkpoint，不自动 create/submission retry。日志合同明确是待实施规范，不当作已完成收据。UTC/monotonic、缺失用量 unknown、缓存不冒充新调用、原终态保留与后续 reconciliation 关系清楚。通过静态说明检查。
6. **L1 / L4 其他边界**：已读 sermon_source_text_review.py、build_english_source_package.py、codex-local-production-runbook.zh.md、stage_formal_multilingual_dev.py。source text correction 保留 humanApproval=false，来源人工审核独立且绑定全部单元和哈希；机器 source pass 只给 shadow 资格。Dev stage 是固定三 locale、带音频的专用入口，要求独立人工文字/音频收据和对应资产，不是通用 text-only publisher；输出新目录，不覆盖现有目录、不上传，deploymentStatus=not_deployed，HTTP/device 未运行。不得把专用能力不足当作通用契约被违反。通过这些范围的静态说明检查。此前页面审核/PR #228 已处理或报告的历史快照、seal/catalog/HTTP 问题未重复列成新缺陷。

## 本次未执行与边界

原审核调查阶段只读检查源文档和代码，当时未修改文档、代码、prompts、memories 或生产状态，也未 commit、push、创建 PR、合并或部署。随后为记录调查与实验计划，本 PR 新增本报告、修改相关 backlog／说明文档，并提交、推送及创建文档 PR；这些记录动作与只读调查分开计述。

上述调查和文档记录均未修改运行代码或生产提示词，未运行生产 CLI、模型、TTS、ASR、生成任务、音频解码、网络发布验收或功能测试，未停止运行中的任务／模型。没有执行第三方安装钩子、npm 脚本或未审查 linter。静态建议未通过模型行为回归，也未证明当前成品存在上述错误；需要用户决定的项目不能视为新增需求或执行授权。后续独立授权的软件实施和验证归 PR #231 的回执，不倒写为原调查阶段的执行。


## 与页面流程 PR 的关系

本记录独立于 [PR #228](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/228)。创建本记录前核实 #228 为 OPEN、Draft，head `a4e700030bd738a51f9954d4ddd6dbe87d026143`。该 PR 修订页面发行说明；本 PR 记录五项 Agent 指令发现及后续实验计划，不修改生产提示词、缓存或运行配置。没有运行 A/B，也没有将建议标成实施完成。

## 明天（10/4）

A/B 候选全文与实验计划移至[明天 backlog](https://github.com/JonathanJing/sermon-video-zh-subtitles/blob/codex/docs-backlog-tomorrow-20261004/docs/backlog-2026-10-04.zh.md)。本页保留五项静态审核发现，不把建议标为已实现。
