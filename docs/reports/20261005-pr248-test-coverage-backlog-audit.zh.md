# PR #248：多轮测试与既有 backlog 对照复盘

2026-10-05；审计代码 `b854992858a0adae7ede326c004eb31f205eb954`，PR [#248](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/248)，目标 `dev`。本次核对历史收据、当前代码、远端 CI 和既有 backlog；未重新调用 CLI/API 模型、本地模型或发布。本文的缺项清单是下一轮验收顺序，不是已执行结果。结构化范围与来源 hash 见[审计收据](20261005-pr248-test-coverage-backlog-audit-receipt.json)。

**结论：已验证 CLI 组件调用、host-local 准入、确定性接续和同身份恢复；最新 P0 代码主要完成离线正确性。尚未验证新规则的在线候选链、同步修复、真实 474 句性能或正式四层交付。** 不能把早期页面读回、后期真实译审/TTS、最近的 fake 规则测试拼成同一次完整生产成功。

## 各轮实际做了什么

| 轮次／证据 | 实际执行 | 已测时间／结果 | 这一轮未覆盖 |
|---|---|---|---|
| [合并 dev 后页面复测](20261005-dev-merged-180s-rerun.zh.md) | 复用内容，模拟人审；Dev Hosting、Web HTTPS 和 native repository HTTPS 读回；Luna 监督 | 9 步 157.074 s；恢复复用成功阶段，只重新 live readback | 新 ASR/译审/TTS；实际音频播放、TestFlight/真机/现场。HTTPS reader 不是设备播放 |
| [CLI 三分钟译审](20261005-codex-cli-layer2-180s.zh.md) | 同源 39 英文单元／13 组，26 次真实 Astra→Sol CLI | CLI 合计 333.839 s | TTS/ASR、正式 controller/plugin/candidate、人审及发布 |
| [24 路并发](20261005-codex-cli-concurrency-24.zh.md) | 总计 80 次真实独立 CLI 调用；最高 24 个在途进程 | 16→24：同为 24 项，31.54→30.15 s，仅少 4.39%；最大单任务 22.03→30.15 s | 输入为四组的八种任务及副本；审核使用旧 draft，未验证新翻译→审核 DAG、长队列或账号上限 |
| [Astra 译审＋本地模型](20261005-fixed-180s-mock-codex-local-rerun.zh.md) | 26 次真实 CLI，Spark TTS batch2／ASR batch4，同身份零推理恢复 | CLI 315.516 s；所记阶段区间约 481.566 s；音频 185.92 s | 正式 candidate/audio admission、人听审、发布；同步未过 |
| [Sol 6.1 high fast 复测](20261005-sol61-high-fast-fixed-180s-retest.zh.md) | 26 次真实 CLI；13 WAV，TTS 7 批／ASR 4 批；busy、release、resume | 已测阶段 512.707 s；CLI 348.374 s；交接 0.511 s；恢复 CLI 0.572 s、本地 11.054 s，0 新调用 | 未运行 language plugin/canonical candidate；未启模型 session；同步 4 组 lag 失败、尾部超 5.797 s，`publicationEligible=false` |
| [Credit 记录开发](20261005-codex-cli-credit-logging.zh.md) | 历史 26 次真实响应的只读投影，79 来源 hash 核验；178 tests＋69 subtests | 26.040180 purchased-credit equivalent；0 新请求 | 新 writer 的 fresh 在线对账、完整交互监督用量、实际额度扣减及 credit 预算准入 |
| [最近 P0 开发](20261005-production-recovery-p0-development.zh.md) | 230 项不重复 fake／本地文件 tests；历史 13 组／26 响应 mock；13 真实旧 WAV 只读复算 | 8 个实现 SHA 与审计代码一致；15 原文件 hash 不变；测量约 0.395 s | 新 modelRules 在线译审→plugin→candidate；真正异常停止/修复后的恢复；同步修复；真实规模性能 |

多轮测试覆盖互补，但执行身份、模型策略与收据版本不同。历史成功不能替代变更后重验；未变且仍满足绑定的缓存／批准可继续复用。

## 速度、credit 和质量如何比

同一 13 组样本，Astra＋Sol 的估算为 **52.47544**，Sol 6.1 high fast＋Sol 为 **26.04018**，少 **26.43526（50.38%）**。按同一冻结价卡重新核对 52 个响应及比较所用 80 份来源 hash；不包含交互监督／开发会话，不代表实际订阅扣减。P0 的零 worker 请求也不等于整个开发会话零消耗。

CLI 墙钟 315.516→348.374 s，增加约 10.4%；所记流水阶段约 8:02→8:33，但前轮区间与后轮阶段和的边界略有差异，不能作严格端到端基准。两轮 TTS/ASR 调度约 165.369／163.111 s，差异很小；模型/文字和运行时也变了，无法归因于某一修复。已证实的改进是恢复零重复调用、准入和释放可对账、交接低于 1 秒，以及诊断能准确定位同步阻塞；尚无“P0 让整篇快多少”的实测。

[机器盲评 A/B](20261005-sol61-high-fast-translation-ab.zh.md)和最终 13 组只读比对支持“小样本整体接近”，不能证明 Sol 6.1 整体更好。两轮均 13/13 机器通过，审核均修改 12 组，这个数量不是错误率。g012 初译差异经复核后都变成“统管”，不能算最终稿优势。样本只有中文、无直接经文；未进行本次独立人工盲评或听审，g012 的机器严重性判断还存在分歧。经文、韩语／西语、长篇上下文和音频质量仍待实证。

## 缺项、开发前置与既有 ID

下表 T 编号只用于本文的测试追踪；优先级与任务归属仍在[统一 backlog](../backlog.zh.md#pr248-test-audit)，不另建排期。P0 表示下一次完整周产或正式 CLI 切换前必须满足的条件，不表示本 PR 所有实验必须一次做完。

| 测试 | 已有证据／当前边界 | 尚未做的验收与前置 | 归属／顺序 |
|---|---|---|---|
| T01 新规则在线链 | canonical runner/controller/plugin 的 fake 回归；旧片段 simulation 明记 `not_run_legacy_simulation` | 隔离、版本化入口运行 fresh CLI→同份 modelRules→实际 plugin→candidate；保存 payload/规则/角色/receipt，恢复 0 请求。目前测试入口无 plugin，先接线 | P0；R242-001/005/011 |
| T02 同步局部修复 | 留存、声学测量和 recovery planner 已实现；当前 WAV 仍 fail | 听审/校对 g003/g004 等早期延迟；先判断 L3 或 L2。只修受影响依赖/批窗，成功邻句不覆盖；整轨重新排程、cue、听审，保持原 8 s 门槛 | P0；R242-004/012/018 |
| T03 474 句 receipt 快路径 | `ValidatedJobContext` 已接 formal renderer；小 fake 验证及旧 474 真实缓存存在 | 隔离同 job 旧/快路径，新增推理 0；比较 CPU/I/O/墙钟和所有保护 hash，单列 admission、解码、留存 fsync、组装；坏音频/错 receipt/漂移仍拒绝 | P0 性能验收；R242-003/017/020 |
| T04 实际 recovery plan 对账 | 21 项 planner tests，完整批窗求值与缺项提交分列 | producer 尚未输出 planner 所需完整 expected-intents/settings 快照；先接快照/owner，才可计划→实际批次对账；unknown 不重发/释槽 | P0；R242-004/010/012 |
| T05 经文／多语质量 | 中文 13 组 CLI/机器 A/B；当前无直接经文 | 新增 source-bound 完整/部分引文、释义、未口述编号、数字否定、跨组语境；zh/ko/es 具名盲评与固定 rubric/非劣阈值。缺政策/Gold 保持待决 | P0 周产质量；R242-005/018/023；STE-001/002/006 |
| T06 正式 CLI 及 strict/RQC | 默认正式 Astra→Sol API，Sol 6.1 是 simulation override；strict D1–D5 已有显式模块 | canonical wrapper 保留 CLI 身份/resource/decoder；strict prompt、`response_observer`、只读 reviewer schema 需适配。做无 API fallback、unknown/预算、D6/D7 真实分级及人审，再 rollout | P0 正式切换前；R242-011/020；SPD-006 |
| T07 8×8 与故障规模 | 周日旧 474 生产采用 8×8；本轮真片段 batch2；CI root-0 执行 7 项 Spark fake tests，包括 419 单元 | 当前新增 anomaly 留存 I/O 下实际 8×8 大规模、已确认失败后 full-window replay、成功邻句 hash、24 GiB guard 瞬时内存与 plan 对账；不能用 batch2 代替 | P1 放大前；R242-012/017/021；SPD-OPT-03 |
| T08 驻留与冷暖 | fake session load1/reuse1；真实片段未启 session | session 生命周期 GPU permit 未实现，且代码拒绝与 per-job permit 同开；先补许可，再测冷暖/切模型/cleanup/unknown/显存与听审 | P1；R242-017/021；SPD-OPT-01 |
| T09 跨版本缓存 | 同 job 真实 CLI/TTS/ASR 恢复 0 调用；部分迁移接口已有 | CLI 跨 run 仍禁用；L1/ASR 总 hash 变更的精确迁移证明、坏证据负例和实际修改单句对照未完成。ASR cache 仍绑整 speechJob hash | P1；R242-002/010/012 |
| T10 长队列／跨主机 DAG | 24 路短独立任务成功；host-local broker；100 步真实进程＋mock provider | 共享 CLI 账号容量/跨主机 lease、公平队列与分区对账未接完；再比较同工作量 16/24 路新译→复核、尾延迟/限流/unknown/质量和总交付。保留单 run 单 locale owner | P1，合同先行；R242-009/011/021 |
| T11 计量完整性 | 逐调用 token/时间/估算 credit 日志与历史投影已实现；实际用量缺失保留 null | fresh v2 response→ledger→CSV 对账；接监督原始时间/usage，区分等待与生成；真实 debit 另证。美元 BudgetStore 不能直接当 credit 准入；归档 `/tmp` 测试日志、生成 run 索引 | P1；R242-016/017/022；COST-001/002 |
| T12 四层与交付 | 早期 Dev 页面读回，近期组件生成；不是同一 canonical chain | 新 L2/音频 package、独立文字/听审/大纲/默想收据、release plan join、L4 环境/attempt/资产闭合；再 Dev/Beta HTTP、Web/真机播放/字幕、正式晋级与设备/现场分列 | P0 完整周产；R242-006/007/013/014/015/020 |

T01/T06、T04、T08–T10 包含尚缺工程接线；不能直接“再运行一次测试”解决。T02/T05 的人工裁定也不能由 fake 收据或机器 pass 补齐。T03 和当前 419 fixture 可以先做零推理验证，但必须保护旧生产身份，不能伪造旧 intent 或清除 unknown marker。

## PR 与文档一致性

审计时 PR 描述先写 P0 三项“尚未实现”，后又追加已实现，存在矛盾；本次统一为当前实现、历史实测和未来验收三部分。`generation-review-gate-backlog` 的“全部 pending”、L2-004 插件“从零实现”、速度 backlog 的旧 missing-only 和规划的“receipt 快路径待开发”均不能当作当前代码状态；本次加日期核查说明，不关闭未经合并/实际验收的条目，也不改写历史运行证据。

截至 19:08 UTC，审计代码的 native-client、contract-validation、local/source/full mock 通过；Python root-0 **失败**：2023 tests、1 failure、10 skipped，唯一失败为 `test_captured_prompts_match_actual_production_and_keep_full_context`，旧测试直构 prompt 漏传 frozen modelRules。CI 也真实执行了 `test_spark_tts_production` 7 tests；这补齐该模块在本次代码上的离线执行证据，不构成 GPU 性能验收。[root-0 日志](https://github.com/JonathanJing/sermon-video-zh-subtitles/actions/runs/37357997551/job/111925507837)。root-1 也失败：2136 tests、2 errors、12 skipped，均来自 `test_migrate_target_language_model_cache`，迁移 helper 尚未与冻结 modelRules 对齐，原缓存 payload 无法匹配。[root-1 日志](https://github.com/JonathanJing/sermon-video-zh-subtitles/actions/runs/37357997551/job/111925507652)。这是真实接线遗漏，不归为生产提速结果；必须保留旧规则未证明时零调用拒绝和 CLI 跨 run 禁用。ios-validation 按路由 skipped，不能宣称全绿或已安装新 Beta。修复与定向结果见下方补记；新提交 CI 另记。

### 审计中修复的 CI 遗漏

benchmark 的对比侧补同一 pinned plugin，保持 translator/reviewer 完整 payload 相等，并核验 modelRules 实际输入。migration fixture 补真实规则入口；实际 helper 在创建新目录前核验旧规则、preview、parsed/raw 和当前 modelRules/config，一致才零调用复用，再向 plugin/candidate 传当前 receipt。缺证据、规则/模型变化、重哈希伪造输入、unknown 和 CLI 跨 run 身份均拒绝；不补写旧消费证明。plugin implementation-only 且模型实际规则/payload 不变的情况仍可复用，不复制人审。

定向 5 模块 **88 tests / 4.492 s 通过**：benchmark 12、migration 10、rule preflight 25、runner 32、candidate 9；新增 5 个迁移负例。与历史 230 项部分重叠，不累加成独立总数。原始日志归档 `artifacts/pr248-test-audit-20261005/l2-cache-migration.log`（ignored），SHA 见审计收据；`git diff --check` 与 195 个本地文档链接检查通过。没有在线模型/API/GPU 调用。修复提交的新远端 CI 等待独立结果，原失败收据保留。

## 下一轮执行建议

1. 先完成当前 CI prompt 一致性修复，运行定向测试；利用已有 419 fixture 和隔离 474 cache 做零推理快路径/plan 对账，取得可靠规模基线。
2. 将新规则实际送进固定片段的隔离 CLI→plugin→candidate，逐项核对 payload/receipt 与 fresh credit 日志；原片段继续作性能基线。
3. 对同步问题作具名听审，按裁定执行最小 L3／L2 修复及下游重建；加入经文/多语盲评样本，明确质量门槛。
4. 补正式/strict adapter、ASR 迁移证明、session GPU 许可和跨主机容量合同，再分别测冷暖与真实依赖并发；避免同时更换模型、批次和规则而无法归因。
5. 通过短片后做 10 分钟、实际整篇、重复恢复和完整四层交付。最终比较同质量完整 scope 的耗时/credit/人工等待/按时交付，HTTP、设备与现场各留独立证据。

本次未重跑收费阶段，也未变更正式模型策略、资源容量、质量容差或发布状态。既有 `.env.openai` dev/prod launcher 和两 project/key 配置继续沿用，不因 CLI credit 日志创建新 key；CLI ChatGPT 登录用量与 worker API project 费用分别记账。
