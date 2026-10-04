# 统一 CLI 跨层接线追加审核

日期：2026-10-04。用户指定审阅基线 `f16007a53932eb5cce9673b1bad084ac76201f7d`；代码基线为其中的 dev `ecbc92151587c187ebe25cc78a221591cc042842`。本轮开始时 PR #242 已有他人提交 `f58f879ea7798b1133be011ace9fca1d7e8d7d6f`，本次 fast-forward 保留了两份新增审核，未覆盖其修改。原[完整设计](../unified-cli-pipeline-design.zh.md)仍逐字节保留，不改变原稿 SHA。

## 证据范围

阅读原设计、已有设计审核、周产改进分析、10/3 播客复盘、App bundle/inspection、canonical controller 和 Temporal activity 的对应实现，并检查 checkout 的 AGENTS 与 .agents/skills。唯一技能 live-caption-zh-fallback 属于离线字幕，不适用于本轮设计审核；没有执行其生产步骤。

已实际读取两份**已提交历史事件文件**：

| 文件 | 字节 SHA-256 / 范围 | 证据性质 |
|---|---|---|
| [L2 cache replay events](20260930-observability/l2-cache-replay/events.jsonl) | `9816fb285b22572560327f477b1a450f1425dc5f2fe6f1ea7e2ee168b5675e89`；262 行；首尾 2026-09-30 14:38:45.379177–14:38:48.193871 UTC | 历史有限缓存复跑，不是全生产新调用 |
| [bounded source diagnostic events](20260930-bounded-source-diagnostic/events.jsonl) | `ec7f1b5e08b3dc9aadc5f32ea9d8e16308565606447fb6f3611060a6cbccb358`；54 行、4 个 runId | 历史诊断导出，不是播客端到端原始账本 |

10/3 播客复盘第 5 行说明原件位于 ignored `artifacts/podcasts/if-i-had-more-time-jesus-is-worthy/`。本 checkout 没有该目录；已定位的本机旧副本相同路径也不存在。没有以广搜秘密或远程机器来弥补。该复盘中的 API、token、时长、批准和部署统计均作为**报告陈述**引用，未在本轮由原始播客日志重算。没有新模型、生成、媒体解码、资源性能测量或线上验收。

## 新发现与具体验收补充

### N1 / P0：首轮 canary 缩范围不能变成更改已决定的最终交付范围

证据：已有[设计审核](20261004-unified-cli-design-review.zh.md)原 F4 第 51–55 行建议每周默认 scope 改为 Firebase reader 单独完成，并使大纲、默想、iOS 等不阻断。基线 [backlog](../backlog.zh.md)第 947、953、956–960 行明确用户目标为 App 页面及翻译、配音、大纲、默想，双测试端人工批准后正式 iOS/Firebase 双端验收。原设计第 250–266、418–424 行已保留完整目标及首轮缩小 canary 的决策。

这是**新增审核建议与已批准产品目标的冲突**，不是生产故障。设备/现场/PDF 的独立验收，以及为初次验证显式选小 scope 可以保留；不能把 canary 成功扩大成最终成功，也不能由技术审核自行降低最终范围。内容晋级也不等于每周提交商店二进制。

步骤：把 F4 标为未获批的范围建议；manifest 显式区分 canary scope 与 final scope，由授权者决定首轮范围。保留四项产品缺失/不适用的实际状态与既有例外，不虚造完成。

验收：Firebase-only canary 可在其约定 scope 达成，但 `dual_production_verified` 仍拒绝缺产品、缺任一测试端批准或正式端失败；设备/现场未测分别 not_run。无需模型测试这个聚合门禁。需决定：首个 canary 范围，而非重新默认改产品目标。落点：2.4、4.8–4.10、8.2。

### N2 / P0：App adapter 的代码身份闭包不能直接沿用四文件列表

证据：`scripts/sermon_app_delivery_workflow.py:92–96` 的 implementation_identity 仅哈希 workflow、app 两个 Python 及两个 App schema；`155–160` 把该值纳入 job identity。实际 `scripts/sermon_app_delivery.py:21–26,95–98,175–198,201–228,232–310` 还使用 stage/source builder 和现有 Source/Text/Audio/review schemas。例如 stage 的声音/ASR 准入或被读取的旧 schema 变化，不在上述四文件列表中。

这是**现有静态依赖绑定缺口**；未证明任何实际工作在漂移代码下通过，也未声称 current bundle 不做验证。原设计 1.3 已要求完整闭包，但接入 App 时需要一项具体负例，不能只援引 L2 的宽闭包证明全部 adapter 已覆盖。

步骤：逐 adapter 冻结可达验证/执行依赖、schema 与必要工具版本；将“内容身份”和“执行准入代码身份”分列。审核/音频字节可保留，但新代码准入必须重新校验；兼容迁移要版本化。不能将所有 adapter 字节哈希一概降为 provenance，也不把任意代码变更都解释成内容变更。

验收：只改被调用的 stage/source validator/外部 schema，旧实现身份不得继续派发新工作；历史产物保留，身份不兼容时 blocked 而新增付费为零。无关 doc 修改不触发模型重跑；dependency-scan 与拒绝夹具先离线验证。落点：1.3、4.9、5.4。已有审核 F1 的 provenance 建议据此限缩，未知依赖继续拒绝。

### N3 / P1：生产 observation 是输入声明，不是 publisher 验收证明

证据：`scripts/sermon_app_delivery.py:455–470` 检查 productionObservation schema、环境/client/candidate 绑定和 evidence 字节；`465` 按 opaque artifact 读取，未解析其内部是否真的有远端资产读回/reader 结果。`schemas/sermon-app-delivery-v1.schema.json:912–969` 允许 publication/deviceAcceptance 的 pass/fail/not_run 和一个 evidence 引用。`sermon_app_delivery_workflow.py:99–102` 有意从冻结 readiness 核心剔除 productionRuns，bundle 返回 prepared_not_published。**这些是现有 read-only readiness 的合理边界，不是已实现发布器的安全漏洞。**

尚未明确的是：统一 CLI 的正式 publisher 要用哪些可信收据推导 4.10 状态，不能把传入 observation 的 pass 直接复制成 http_verified 或 dual_production_verified。

步骤：发布 adapter 定义验证后的 deployment/version、origin/environment、catalog/各产物 SHA、readback、reader 与必要设备证据合同；绑定实际操作身份及受信 verifier。原观察只作显示，非法/缺证据保持 unknown/not_run 并给固定原因；PDF 和 readiness 不因此失效。

验收：给任意 opaque blob 配 publication=pass 不可满足正式 scope；错环境、旧 catalog、部分双端成功、回滚后的旧 observation 均不提升。readiness 和实际发布验收独立。publisher 的离线拒绝例先运行，真实双端验收需另行授权。落点：2.4、4.10、7.1。

### N4 / P1：通用内容 manifest 与 Sunday-only App workflow 要有明确适配

证据：`schemas/sermon-app-delivery-workflow-v1.schema.json:7–10` 强制 sunday；`scripts/sermon_app_delivery_workflow.py:66–73` 要求 weekday==6，并在 `53–57,154–160` 纳入 route/job 身份。L2 config 使用 productionRunId（canonical_layer2_controller.py:112–113），App plan/source/page 又有自己的身份。播客复盘第 3–13 行证明该业务与周次证道不是同一内容类别，但没有证明本次运行调用了该 Sunday-only workflow。

这是**通用入口集成范围缺口**，不是本次播客已发生 Sunday 失败。不能默默选最近周日或伪改源 serviceDate 来满足旧 adapter。

步骤：manifest 区分 content identity/page/category/source date 与 optional weekly schedule date；为 legacy Sunday adapter 明确 mapping 或版本化新 config。业务日期/内容类别如何决定需冻结合同。legacy Sunday run 和既有 route protection 保留。

验收：非周日来源可得到准确的 unsupported/mapping-required preflight，在任何付费前退出；版本化支持后能绑定原真实日期进入 App。两条不同内容/相同日程及同内容不同入口不碰撞、不改源审批、不换 jobRoot 掩盖未知 owner。落点：1.1–1.2、2.2、4.9；canary 先覆盖内容类别矩阵。

### N5 / P1：同一 JSONL 中多个 run 的负例要进入日志聚合验收

原始事件证据：bounded source diagnostic 文件第 1/13 行为 run `7241d345…`，23:27:21.389440–23:27:28.754820 UTC；第 14/24 行为 `7b972e2f…`，23:28:26.151204–23:28:59.345839；第 25/39 行为 `ed9497cb…`，23:30:57.160023–23:31:32.928925；第 40/54 行为 `7142b185…`，23:34:58.873445–23:34:59.651893。四个 traceId 不同，productionRunId 相同，属于同一文件的多个历史诊断运行。

这是**新增具体日志验收夹具**，不新增“日志已错误聚合”的事故。原设计 7.1–7.3 已覆盖因果与跨 run，此处补精确选择/分组条件：文件路径及共同 productionRunId 都不能唯一指定一个 execution attempt；单 run completed 不等于整生产完成。

步骤：查询显式限定 production revision + run/attempt/trace，跨运行只按有证据的 lineage/因果边关联；导出声明选中与排除范围、evidenceMode 和缺测。不得拼首行开始/末行结束充当一个模型或 job span，不补虚构跨进程边。

验收：该 54 行夹具保持 4 个独立运行；汇总保留原事件时间、不把 4 段计成一段执行/排队或一次付费，也不根据四个 completed 提升生产状态。历史缓存复跑与新调用计费分开。落点：7.1–7.4、8.1。仅解析历史文件，没有执行诊断重跑。

## 已记录、历史修复与本轮不重复申报

- f58f879 的 F2 cache 计数、F3 生产会话停止、F5 审核队列、F6 先 canary 后并行均已记录，本次不新增编号冒充新发现。
- 播客错源、prompt/quote policy、双讲员/插件、ASR 疑点等已在 10/3 复盘及 backlog 记录；无原始目录不能重新裁定其修复完成或重算收益。
- 9/30 observability README 记录有限日志复跑修复；缓存事件 completed 只说明该历史验证 run，不能反推完整周产或新 provider 调用成功。
- 不改变 Astra→Sol、整 locale/整轨人审、声音授权、preview/formal、PDF ad hoc 与双端发布目标；原稿性能目标仍是待测。

本轮只新增报告并澄清两处审核建议，原稿正文不动。以上步骤与验收均未实现/运行；后续依赖签字范围、代码闭包合同、内容日期 mapping 与可信发布收据设计。没有运行模型、生产、功能测试、部署或合并。
