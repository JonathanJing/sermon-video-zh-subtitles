# PR #229 本地开发入口

本分支基于 PR #229，交付 STE 澄清、Dev 期次导航、App 产物的只读准入检查及费用离线对账。后两项消费已有产物和收据，不生成内容、人审、客户端证据或发布。真实账号配置、模型实验及其他明天事项仍属独立 PR #230。

## App 产物与 PDF

在仓库根目录运行：

```bash
python -m scripts.sermon_app_delivery inspect --plan /path/to/frozen-inputs/plan.json
```

输入合同为 [sermon-app-delivery-v1.schema.json](../schemas/sermon-app-delivery-v1.schema.json) 的 `plan`；输出为 `inspection`。输入文件和引用文件放在 plan 所在目录内，可保留其子目录结构；逐项核验字节 SHA 和提供的 JSON SHA，拒绝路径逃逸和符号链接。原产物不改写。缺少依赖时使用仓库 requirements 配置的 Python 环境；音频验证另需 `ffprobe` 和 `ffmpeg`，available 的按需 PDF 单独使用 `pdfinfo` 验证可读页数。

| 面向操作员的产物 | 当前机器合同 | 准入证据 |
| --- | --- | --- |
| 共享英文来源与锚点 | `sermon-english-source-package-v1` | ready 来源、媒体与锚点哈希、独立来源审核及全源覆盖 |
| 翻译 | `sermon-target-language-candidate-v2` | 同一来源、locale、policy、全部源单元及独立逐组人审 |
| 配音与同步 | `sermon-target-language-audio-package-v1` | 同 locale 的翻译或独立获批口播稿、授权声音、机器筛查、全文听审、实际音频及同步数据 |
| 大纲／默想 | 新增 `sermon-app-study-product-v1` | 同一来源、翻译、locale、内容 revision，逐条来源引用及独立产品人审 |
| 页面交付 | 既有 release package v1／v2 | 分别保留开发／正式历史 scope；不能直接用新大纲／默想合同推断旧客户端已支持 |

每个 locale 明列四项产物，状态为 `available`、`missing`、`failed` 或 `pending`。只有配音可声明 `audio_unavailable`，且须提供该 Layer 3 包、release plan 的 text-only 例外和两端客户端支持证据。没有相关授权时不能用这一例外补零、补声音或跳过来源／翻译审批。

先用 `content_hash(plan)` 冻结产品引用的 `contentHash`，再收集双端能力收据，最后用 `candidate_identity(plan)` 计算候选身份并提供独立 App 审批。产品、审核、来源、环境及客户端版本变化会改变绑定。能力收据逐 locale 绑定 iOS Beta／Firebase Dev 的版本、产物 schema 与字节 hash；这使新产品协议不会被自动认为兼容旧客户端。缺失能力收据时保留 `planned`，不授予正式提升资格。

正式内容路径仍是：同一候选在 iOS Beta 与 Firebase Dev 均可见 → 两端人工查看并记录批准 → iOS 正式内容源与 Firebase 正式 App 分别发布和验收。检查器核验两端批准的来源、候选、内容版本、locale×四项产品 hash、客户端身份与审核范围；旧批准无法覆盖变化后的候选。返回 `eligible_not_published` 只表示输入具备提升资格。正式环境的 `productionRuns` 仅记录另行提供的观察，缺失时显示 `not_run`；检查器不会执行发布或凭 HTTP 状态生成设备／现场验收。

`pdfAdHoc` 不参与 App 候选 hash 或提升阻断：没有 PDF、按需 PDF 失败，均不阻止其他已获批 App 产物通过检查。声明 available 的 PDF 仍单独核验文件与批准，证据缺失转为 PDF failed，不伪报成功。

这是新的 `app_delivery_readiness` scope。旧 Supervisor、`sermon_end_to_end.py` 的 `dual_pdf` completion latch，以及 `weekly_dubbing.py` 的 `deferred_until_release` 历史任务保留原 PDF 门禁。后者只是延后 PDF，不能当成已解耦。迁移 producer／客户端／通知时须显式接入新 scope，并保存旧收据；本次没有自动改路由或将旧任务标为 App 发布完成。

## Dev 期次目录

Web 根据显式环境和 catalog 的 `diagnosticOnly`／`simulationOnly` 标记分组；正式与旧期次、开发诊断、开发演练各用一组。同名不同 ID 保留全部条目，标签附完整稳定 ID；重复 ID 仍拒绝。Production 隐藏开发条目，默认项和深链被过滤后回退到可见期次。ID、locale、音频与来源路由保留。

本地验证使用合成 catalog，覆盖诊断受阻状态和同名条目选择；不是远程部署或 iOS 验收。真实发布后的环境核对仍需按实际 catalog、客户端与页面版本另记收据。

## 费用隔离与离线对账

```bash
python -m scripts.sermon_cost_isolation validate-config --config /path/to/routes.json
python -m scripts.sermon_cost_isolation reconcile \
  --config /path/to/routes.json \
  --attempts /path/to/attempts.json \
  --daily-costs /path/to/normalized-daily-costs.json
```

[sermon-cost-isolation-v1.schema.json](../schemas/sermon-cost-isolation-v1.schema.json) 定义 `config`、`config_validation`、`attempts`、`daily_costs` 和 `reconciliation`。这里只接收本地归一化 JSON，不是 provider 原生 Costs API adapter；不读取环境变量、key 原值或调用 provider。配置必须含不同 dev／prod Project ID 和全局不重复的 transcription／translation／reviewer 安全别名。非 OpenAI ASR 独立记录，不需要 OpenAI transcription 别名。

两个证据输入必须使用相同 `queryWindow`（UTC 日、起点包含、终点不包含）。每次 attempt 独立保留日期、状态、观察到的项目／key ID、usage 与估算；估算必须带 `pricingVersion`。未知 token、金额或结果保留 null／unknown，不记零。缓存输入是输入子集，不重复相加；非 OpenAI 费用不并入 OpenAI 估算。

每日费用页绑定 page 链和日／Project／key 分区；拒绝重复请求 ID、重复 key 分区、错误环境映射及父 Project 聚合与 key 子项重叠。null 项目保留 unattributed，不按 key 猜测环境。实际日费用与估算用 Decimal 分开汇总，`dailyComparisons` 的差异为“已知估算减观察实际”。缺少任一侧时差异为 null；分页未完、未结算、未知结果／费用、归因缺口或范围不完整时标 `partial`。按 key 分区对账须匹配覆盖集合，未知或不同 key 不标完整。`complete` 仅代表声明的离线范围和输入齐全，不证明价格、provider 账单或逐请求真实费用；`requestActualCostsAvailable` 和 `invoiceVerified` 固定 false。

本次没有创建 Project、key、service account，设置权限／限额，验证真实账单或接入 producer。实际映射、secrets、最小权限与 hard limit 配置仍由 `DEV-COST-002` 的独立范围处理。

## 验证与交接

```bash
python -m unittest tests.test_sermon_app_delivery tests.test_sermon_cost_isolation
python -m unittest tests.test_sermon_end_to_end tests.test_run_codex_local_sermon_production tests.test_stage_formal_multilingual_dev
node --test experiments/sermon-dubbing-poc/web/*.test.mjs
git diff --check
```

测试使用临时文件、现有合同 fixture 和本地音频；不调用模型或发布。STE 首批有 69 项相关回归，审核后定向验证旧 scalar／batch 缓存路径，并恢复 renderer 与 PR #229 完全相同的字节，避免 CLI 说明导致缓存失效。操作员输入说明保留在 [renderer 文档](formal-layer3-renderer.zh.md)，不扩大兼容名单。

2026-10-03 本批验证：新增 App 24 项／费用 29 项合计 53 项通过；旧端到端、local completion 和正式 Dev staging 44 项通过；恢复 renderer 后 3 项缓存定向回归通过；Web 458 项通过。两份新增 JSON Schema 通过 `check_schema`，两个 CLI help 退出 0，158 个相对文档链接目标存在。旧流程回归使用项目已有完整 venv；仅安装 jsonschema 的临时环境缺 requests，不能运行旧 Supervisor 的导入链，未为此改项目代码。

软件验证与真实内容生成、双端人工批准、生产发布、设备和现场验收分别记录。相关 backlog 在合并和完整验收前保留 `in_progress`，不以本地通过关闭生产任务。

后续真实产物、Dev 目录、Core decoder、恢复与费用证据的并行检查，以及完整远程 CI 结果见 [PR #231 并行检查回执](reports/20261003-pr231-parallel-checks.zh.md)。检查确认新 App producer 接线、候选协议兼容、默想／双端证据和真实费用归因仍有缺口。
