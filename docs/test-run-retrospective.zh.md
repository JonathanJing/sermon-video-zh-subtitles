# 运行报告与复盘

每次正式运行或测试（每周生产、三分钟 e2e、机器质检驱动、Spark 诊断等）结束后，都生成一份脱敏的运行报告，经 PR 放进仓库，供云端会话分析和写复盘。本页只规定流程，不改变任何层的完成状态。

## 为什么需要

| 位置 | 内容 | 云端会话能否读到 |
|---|---|---|
| Mac 上的 `artifacts/` | `timings.tsv`、各阶段 `*.log`、`outcome.json`、`summary.json`、收据 | 不能。目录被 Git 忽略，只在本机 |
| Spark 上的远端 stage 和容器日志 | TTS/ASR 运行日志、job hold | 不能。需要 SSH |
| GitHub：PR、`docs/reports/`、Actions 日志 | 已提交的复盘和收据、CI 输出 | 能 |
| Firebase Dev 线上文件 | 发布后的页面和 catalog | 能（公开 HTTP） |

运行证据只在本机，以前要靠人手工把表格贴进线程。运行报告把这一步变成固定的产物和固定的 PR。

## 设计

1. **一次运行对应一份报告。** 报告名为 `YYYYMMDD-<简称>`，目录结构固定：
   - `INDEX.md`：自动生成，包括结束状态、各阶段耗时、失败阶段和错误行。
   - `manifest.json`：原文件路径、哈希、截断和脱敏次数。云端可以据此核对本机证据，不需要原文件。
   - 运行目录的副本：只含 `outcome.json`、`timings.tsv`、`summary.json`、`preflight.json`、`journal.ndjson`、`decisions.ndjson` 和 `*receipt*.json`；`source-budget.json` 只导出结算摘要（`source-budget.settlement.json`：请求数、预留与估算费用、token、成本未知的原因），不导出账本本身；`*.log` 只保留开头 40 行、结尾 200 行和中间的错误行。名字含 `evidence`、`acceptance`、`approval` 的文件不复制：Layer 2 的 `evidence.json` 和人工验收文件可能含讲道原文或译文。人工验收和批准以文件哈希的形式进入决定记录。JSON 的键和值都脱敏（2026-10-11 以 `user@内网IP` 为键的主机表曾漏出），脱敏后撞名的键加 `#2`、`#3` 保留。
   - `RETROSPECTIVE.md`：按下面的复盘清单生成的骨架，由本地或云端的 agent 填写。
2. **两步，分开生成和公开。** `export_run_digest.py` 只在被忽略的 `artifacts/run-reports/` 下生成报告，不碰 Git；`publish_run_report.sh` 先复查脱敏，再公开。生成可以无条件自动执行，公开是一个单独、可检查的动作。
3. **报告单独走 PR。** 公开脚本从 `origin/dev` 切出 `run-report/<name>` 分支，在临时 worktree 里把报告加成 `docs/reports/runs/<name>/`，推送并开草稿 PR。当前检出和分支都不动。报告 PR 只含文档，走 CI 的文档快速路径；修复另开 PR，引用报告路径。这样报告不会被代码评审卡住，修复也不会混进证据。
4. **公开仓库的保护。**
   - 脱敏：去掉 API key、GitHub/Google token、Bearer、带 key/token/secret/password/cookie 名字的字段值、私钥、邮箱、内网 IP、`.ts.net`/`.local` 主机名、home 路径，以及当前环境里名字带 KEY/TOKEN/SECRET 的变量值。
   - 复查：公开前再扫一遍，有残留就拒绝推送。
   - 大小：整份报告超过 2 MB 就拒绝生成。
   - 内容：媒体和模型输出一律不复制。
   - 规则匹配不能保证完全，合并报告 PR 前仍要看一眼 diff。
5. **自动接入。** 下列入口退出时（成功或失败）自动生成报告，并打印公开命令：
   - 三分钟 e2e：`scripts/run_dev_180s_beta_e2e.sh`
   - 机器质检文字驱动：`scripts/run_machine_qc_clip_test.py`
   - 机器质检音频驱动：`scripts/run_machine_qc_audio_test.py`

   其他入口（每周正式生产、Spark 诊断等）由执行运行的 agent 在结束时手动导出，见 [AGENTS.md](../AGENTS.md) 和[本地生产 runbook](codex-local-production-runbook.zh.md#运行报告)。
6. **云端怎么用。** 云端会话读报告 PR 的文件，填写或评审 `RETROSPECTIVE.md`，问题另开修复 PR。复盘填好后合并报告 PR；跨轮比较就读 `docs/reports/runs/` 下的历次 `INDEX.md`。

7. **运行日志与决定记录（2026-10-11 复盘 D 项）。** 复盘不该靠翻派发日志重建时间线。每个驱动和派发器在起止处调用 `scripts/run_journal.py append --run-dir <运行目录> --stage <阶段> --event started|finished|failed|waiting|resumed`（`waiting` 必须带 `--waiting-on`，说明等的是人、服务还是凭据），`run_journal.py summary` 直接给出每阶段和整轮的计算／等待／返工时长与结算成本；返工只算重复轮次里扣掉等待后的计算时间。日志不写机器名，只写 `hostId`：用本轮随机盐（`.journal-host-salt`，不导出）算出的代号，同一轮里能区分 Mac 和 Spark。操作者的每个决定用 `scripts/record_decision.py --run-dir <运行目录> --question … --choice … --decided-by "Jony (chat)" --governs <决定所针对的文件> --evidence <原话或文件路径>` 记成一行，替代手写的 `*.evidence.txt`。`--governs` 的文件必须存在，按当时的 SHA-256 绑定，这一行是 `artifact_bound`，只对这些字节成立；`record_decision.py --run-dir <运行目录> --check` 列出每条决定 `applies`、`stale`（所绑文件已变或已删）还是 `unbound`。不带 `--governs` 的行是 `unbound_note`，只记录说过什么，不能当任何产物的批准。来源预算账本升为 `sermon-source-budget-ledger-v3`：每条已返回的请求带 `settlement`，即供应商报告的 token 数和按所请求模型冻结费率估算的 `costMicrousd`（`estimated_upper_bound`），缺用量或无价格时记 `unknown` 与原因，不再恒为 0；预留上限 `bounds.costMicrousd` 原样保留。崩溃后用 `reconcile_returned` 补记的请求也补上结算。新账本从 v4 开始（下述跨预算复用）；已有的 v2 账本保持 v2、不写结算，v3 账本保留 `estimated_upper_bound`／`unknown` 两种结算，冻结实现照常续跑；要补结算只能显式调用 `SourceBudget.migrate_to_v3()`，它从已保存的返回逐条结算，派发中或返回被改动时拒绝且不改账本。这三样都进摘要。

跨预算复用使用 `sermon-source-budget-ledger-v4`：顶层 `reuseBudgetRoots` 冻结批准的来源绝对路径；只有 v4 返回行可写 `settlement.costStatus=reused`、`costMicrousd=0`。v2／v3 不增加字段或枚举；旧目的账本要复用时显式调用 `SourceBudget.migrate_to_v4()`，原预留上限、已付费结算与未知结果保持，迁移不派发模型、不迁移来源账本，遇活跃派发或损坏返回则拒绝。来源账本和响应内容只读；协调时可创建／持有来源根的 `live-owners` operation 锁元数据，并按根路径排序获取全部来源与目的 operation 锁，持有到缓存判断、预留、派发及响应落盘结束，协调读取与来源派发；扫描全部批准来源，匹配的未知或损坏行仍拒绝；至少一个直接付费来源完整匹配时可复用，其他来源缺少该 operation 不妨碍复用。所有来源均缺少该 operation 或存在身份不匹配则拒绝，不能视为 cache miss 后新付费，避免锁释放后来源或另一目的根再派发而重买。新请求须另有不带复用来源的明确预算授权。只接受直接付费来源行，拒绝把中间 `reused` 行作为新的来源，须直接批准原付费根。匹配的未知派发阻止新付费；匹配的已返回行若文件缺失、不可读或摘要不符，须先对账，不能当 cache miss 重买。复用副本绑定原 operation／request digest、来源 response digest、authority digest／账本版本及原结算，目的根自身复用审批和运行环境也在调用前复核；已核实复用副本不占新的请求／时间／美元预留 cap。

## 命令

在仓库根目录：

```
# 1. 生成（可以同时传多个运行目录，例如 L2 和音频两处）
.venv/bin/python scripts/export_run_digest.py artifacts/<运行目录> [更多运行目录...] --name <YYYYMMDD-简称>

# 2. 复查脱敏、开报告 PR（Mac 上有 gh 时直接开草稿 PR，否则打印 compare 链接）
scripts/publish_run_report.sh artifacts/run-reports/<YYYYMMDD-简称>
```

不传 `--name` 时，默认用当天 UTC 日期加第一个运行目录名。只想检查一份已有报告时，用 `export_run_digest.py --verify <报告目录>`。

## 每次 dev 测试先核对报告

每次 dev 测试结束，先确认本轮按本页生成并公开了报告，再看测试结果：

1. `artifacts/run-reports/` 下有本轮的报告；自动入口不应需要手动导出。
2. `INDEX.md` 有每个运行目录的结束状态和阶段耗时，`export_run_digest.py --verify` 通过。
3. 报告 PR 已开，只含 `docs/reports/runs/<name>/`。
4. 云端会话已读过该 PR，`RETROSPECTIVE.md` 已填写。

缺任何一项，都写进该次的 `RETROSPECTIVE.md`，并更新 backlog 的 [`DEV-RUNREPORT-001`](backlog.zh.md#backlog-run-report-20261008)。

## 复盘检查清单

`RETROSPECTIVE.md` 骨架按这 8 项生成。[PR #283](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/283) 里两轮 Spark 8×8 的复盘是参照样本。

1. **实际覆盖范围**：按 L1–L4 列出本轮真正执行了什么、复用了什么、没有执行什么。模拟审核、诊断级候选、`productionEligible=false` 要原样写出，不要写成“端到端通过”。
2. **结果和结束信号**：每个运行目录的 `outcome.json` 状态。需要独占 Spark 的运行，以 `spark_session_round.sh` 输出的 `round:` 行为准，`execute succeeded` 不代表服务已经恢复。
3. **耗时**：按 `timings.tsv` 列出各阶段，与上一轮同一阶段比较；把等待（sleep、Apple 处理、人工回答）和真正的计算分开。
4. **错误**：每个错误写现象、原因、处理和是否已有回归测试。有改动的，写明提交或 PR。
5. **发生在占用资源之后的错误**：哪些错误本可以在预检阶段发现（例如独占 Spark 之后才暴露的路径或挂载问题），以及要补的预检。
6. **遗留状态**：Dev 上没有被引用的文件、未结束的 job hold、用过但没上传的构建号、需要删除的本地构建产物。
7. **外部可见的变化**：Dev 发布版本、TestFlight 构建、绕过分支保护的推送，每项分开写证据。设备播放和场地验收没做就写 `not_run`。
8. **后续**：每条写清楚由谁做、在哪个 PR 或 backlog 条目里跟踪。

复盘只引用报告里的数值，不粘贴原始日志。

## 预算结算摘要版本

新导出使用 `sermon-run-digest-budget-settlement-v2`：增加 `reused`，`reservedMicrousd` 只计算本根的新增预留，排除复用行；复用响应不再次计费用量。既有 `sermon-run-digest-budget-settlement-v1` 报告保持原字段与原预留总额语义，不就地重写。摘要呈现器显式识别 v1/v2，未知版本不按已知合同解释；导出不修改原 source-budget 账本。API judge 的无 context 复用授权版本见[独立合同](machine-qc-api-reuse-authorization.zh.md)。
