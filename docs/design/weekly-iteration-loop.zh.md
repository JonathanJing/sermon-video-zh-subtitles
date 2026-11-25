# 每周迭代链路：运行报告、私有证据、周汇总、审核与验证

状态：**设计稿；第三至第六节的工具已实施并用真实数据跑过，第七节的云端定时 agent 已创建但依赖本页的代码合入 `dev`，第九节列出没做的部分。** 校准日期 2026-11-15。本页不改变任何层的完成状态、门限、豁免或发布流程；周汇总是机器生成，合并它只批准写在里面的改进决定。

## 一、为什么要加这一层

单次运行的链路已经有了：导出器生成脱敏报告，`publish_run_report.sh` 开 docs-only PR，复盘按八项骨架填写（[运行报告与复盘](../test-run-retrospective.zh.md)）。断在下面四处：

| # | 断点 | 证据 |
|---|---|---|
| 1 | 周更没有自动导出，报告不可比 | [20261115-jesus-is-better](../reports/runs/20261115-jesus-is-better/INDEX.md) 是手写的，没有 `manifest.json` 和 journal；11-08 那份只导出了中文 run，journal 记 1h27m，实际约 2h57m |
| 2 | 改进项没进 backlog | [backlog](../backlog.zh.md) 最新日期小节停在 10-25；11-08 复盘有 3 条改进写着「待开 backlog」 |
| 3 | 没人核对改进是否生效 | 11-08 的「发布意图清单」和「带两个开关的 gate」在 11-15 起了作用，但只靠 runbook 文字传递，没有登记，也没有比较；上一份周对周比较是 [10-04](../reports/20261004-week-over-week-retrospective.zh.md) |
| 4 | 私有证据绑在某台机器上 | 10-23 至 11-08 的运行目录在一台 MacBook 上，11-15 播客在另一台，11-15 主日证道的运行目录两台机器上都没找到 |

## 二、链路总览

| 步骤 | 谁做 | 产物 | 放在哪里 |
|---|---|---|---|
| 1 采集 | 发布驱动自动；失败的运行由 agent 手动 | 脱敏运行报告；私有证据包 | 报告走 PR 进 `docs/reports/runs/`；证据包进私有证据库 |
| 2 周汇总 | 周一的云端定时 agent | `weekly.json`（数值）和 `WEEKLY.md`（叙述） | 草稿 PR，`docs/reports/weekly/<周日日期>/` |
| 3 人工审核 | 维护者 | 改进项的决定、重做的归类 | 写在 `WEEKLY.md`，`finalize` 存进 `weekly.json`，合并 PR |
| 4 迭代 | agent，周一到周四 | 每条接受项一个 backlog ID 和一个修复 PR | 修复 PR 引用周汇总里的编号 |
| 5 验证 | 下一周的周汇总自动做 | 每条改进项的结果：生效、无效、退步、本周没走到 | 下一周的 `WEEKLY.md` |

一周用它的周日（礼拜日期）命名，覆盖到该周日为止的七天。报告按名字里的日期归周。

## 三、两个存放处

仓库是公开的，所以证据分两处。判断标准只有一条：**含讲道原文、译文、审核意见、听众反馈或小样本使用数据的，进私有证据库；只有状态、时间、计数和哈希的，进仓库。**

| 内容 | 公开仓库 | 私有证据库 |
|---|---|---|
| outcome、timings、journal、决定记录、收据、发布门禁与部署记录 | 脱敏后进运行报告 | 原样（去掉凭据） |
| 译文、句表、审核表、听审结论、`run.md`、完整日志 | 不进 | 进 |
| 媒体、托管快照（`public/`）、逐句音频 | 不进 | 不进，只在清单里计数 |
| 前端三份报表（使用、收听、听声定位） | 不进 | 进 `frontend/<周>/` |
| 带前端数值的周汇总 | 不进 | 进 `weekly/<周>/` |
| 私有库里有什么 | [索引](../reports/weekly/private-evidence-index.json)：运行名、文件数、清单哈希 | — |

私有证据库是现有的 `gs://sermon-zh-artifacts-ai-for-god/run-evidence/v1/`。该桶已开统一桶级访问并强制禁止公开访问；工具每次上传前都会复查这两项，不满足就拒绝。布局：

```text
run-evidence/v1/runs/<运行目录名>/<相对路径>      文本证据
run-evidence/v1/runs/<运行目录名>/_manifest.json  来源机器与路径、每个文件的原始 SHA-256、省略与跳过的统计
run-evidence/v1/frontend/<周>/<报表>/summary.json
run-evidence/v1/weekly/<周>/...
```

规则（[`tools/ops/evidence_store.py`](../../tools/ops/evidence_store.py)）：

- 只收文本：JSON、JSONL、NDJSON、TSV、CSV、Markdown、日志、SRT 和 2 MB 以内的 HTML；单个文件上限 16 MB。
- 凭据在私有库里也不留：API key、token、Bearer、私钥和环境里名字带 KEY/TOKEN/SECRET 的变量值会被替换；凭据文件、锁文件和 journal 的主机盐不读取。讲道文字、姓名和路径保留。
- 同名运行目录来自另一台机器时拒绝覆盖，除非显式 `--replace-source`。
- 未变的文件不重传；每次上传另存一份带时间的清单。
- `collect` 只用标准库，可以经 SSH 从标准输入运行，所以没有检出本分支的机器也能回填。

访问：本机用 Application Default Credentials。云端 agent 要读私有库，需要一个只读服务账号（见第七节），目前没有配置。

2026-11-15 已回填 32 个运行目录、141 MB 文本：一台机器上 25 个（10-23 至 11-08，经 SSH 采集），另一台 7 个（11-15 播客与海报）。省略的 67 个文件全部是锁文件和主机盐，没有因大小被省略的。另有本周三份前端报表。

## 四、采集（已实施）

1. **整次生产一份报告。** [`export_production_report.py`](../../tools/development/export_production_report.py) 从任意一个运行目录找出同一次生产的全部目录（各语言、`-source`、`-review`、`-publish` 等同词干目录，加上 `--also` 指定的共享目录），调用导出器写一份摘要，再把这些目录的私有证据传到私有库，并在摘要里写 `private-evidence.json`（库地址、文件数、清单哈希）。合并摘要超过 2 MB 上限时自动拆成 `<名>` 和 `<名>-publish`，仍超过就逐目录导出。
2. **自动触发。** `sfa_publish.py readback` 通过后自动执行上面这一步。它只是观察：失败时打印原因和手动命令，不改变发布结果和退出码；`SFA_RUN_REPORT=0` 可以关掉。公开报告仍是单独一步 `publish_run_report.sh`。失败或中止的生产由 agent 手动运行同一个命令。
3. **发布证据进摘要。** 导出器现在也复制 `publish-gate.json`、`http-verification.json`、`deployment-attempt*.json`、`deployment-reconciliation.json` 和 `smoke-*.json`。它们只含检查名、状态和哈希，周汇总据此数部署次数和门禁结果。发布子命令的 journal（`l4.<子命令>`）在 `dev` 上已经有了。
4. **前端报表。** [`weekly_frontend.py export --week <周日>`](../../tools/development/weekly_frontend.py) 调用 `services/feedback/admin.mjs` 导出该周的三份私有报表，存进私有库，再生成一份聚合结果。

## 五、周汇总（已实施）

[`weekly_rollup.py build --week <周日>`](../../tools/development/weekly_rollup.py) 只读仓库里已入库的运行报告，只用标准库，所以云端会话不需要任何凭据就能生成公开版。它产出：

- `weekly.json`：固定指标、每份报告的明细、上周改进项的检查结果、候选改进。`humanApproval` 恒为 `false`，直到审核过的 PR 合并。
- `WEEKLY.md`：结论（待写）、本周运行、对比上周、上周改进项结果、错误与发现时机、重复轮次、候选改进、前端、采集缺口、证据边界。已存在时不覆盖，避免冲掉审核人写的内容。

数值全部由脚本算，agent 只写叙述和分类。指标：

| 指标键 | 含义 | 来源 |
|---|---|---|
| `time.wallSeconds`、`computeSeconds`、`waitingSeconds`、`reworkSeconds` | 生产运行的墙钟、计算、等待、重复轮次计算 | 报告里的 `journal.ndjson`，口径同 `run_journal.py summary` |
| `publish.deployAttempts`、`maxDeployAttemptsPerReport` | 托管部署次数 | `deployment-attempt*.json` |
| `publish.failedGateEvents`、`gateFail` | 发布阶段的失败事件数；门禁未通过的份数 | journal 里 `l4.*` 的 `failed`；`publish-gate.json` |
| `errors.total`、`preflight`、`afterResources`、`afterPublish`、`lateShare` | 复盘登记的错误和发现时机 | 各报告 `RETROSPECTIVE.md` 的「错误」表 |
| `collection.*` | 无 manifest、缺 journal、复盘未填、私有证据未上传的报告数 | 报告目录与私有库索引 |
| `cost.estimatedMicrousd` | 估算费用 | 预算结算摘要 |
| `frontend.*` | 会话、播放比例、收听设备日、完成率、听声定位成功率 | 前端聚合结果，只在私有周汇总里出现 |

候选改进直接取自各报告复盘的「可以改进的地方」表。没按八项骨架写的复盘不会产生候选，会被列进「采集缺口」。

**前端数值默认不进公开仓库。** [使用统计](../sermon-app-usage.zh.md)规定报表是私有运营资料。带前端数值的周汇总另外生成到 `artifacts/weekly-private/`，再存进私有库的 `weekly/<周>/`；公开的 `WEEKLY.md` 前端一节只写结论。聚合时用小样本规则：1 到 4 写成 `<5`，分母不足 5 不算比例，会话时间线不离开私有报表。即便如此，是否公开聚合数值仍由维护者决定。

## 六、审核、迭代、验证

审核人在 `WEEKLY.md` 里做四件事：

1. 改错事实，写三句话的结论。
2. 在「重复轮次」表里把每条标成「返工」或「变更」。用户改主意或口径变化造成的重做是变更，只有审核人知道（口径见[少返工](../rework-avoidance.zh.md)）。
3. 在「候选改进」表里对每条写「接受」「拒绝」或「推迟」。接受的必须写 backlog ID 和验证信号，每周最多 3 条。可以自己加行。
4. 运行 `weekly_rollup.py finalize --week <周日>`，把决定存进 `weekly.json`，然后合并 PR。

验证信号写成 `指标键 比较符 数值`，例如 `publish.maxDeployAttemptsPerReport <= 3` 或 `errors.lateShare <= 0.3`。接受时记下该指标当周的数值作为基线。下一周的 `build` 对每条开放的改进项给出结果：

| 结果 | 条件 |
|---|---|
| 生效 | 本周数值满足信号 |
| 无效 | 不满足，但不比基线差 |
| 退步 | 不满足，且比基线差 |
| 本周没走到 | 本周没有产生该指标 |

「生效」只说明一周的数值满足信号。关闭 backlog 条目仍按 backlog 的规则，由人决定。生效的规则优先变成 preflight 或 gate 检查，其次才写进 runbook。

迭代节奏：周一审核，周一到周四修，周五用彩排验证（先例：[11-14 彩排](../reports/runs/20261114-sfa-preproduction-rehearsal/INDEX.md)），之后进当周的锁定标签。

## 七、云端定时 agent

例程名 `Weekly rollup PR (sermon-video-zh-subtitles)`，2026-11-15 创建，在维护者的 Claude 账号下管理。每周一 16:00 UTC（太平洋标准时间 08:00，夏令时为 09:00）在 Claude 云端运行一次，从 `dev` 检出，模型 `claude-sonnet-5-5`。第一次触发是 2026-11-16；`dev` 上还没有 `weekly_rollup.py` 时它在第一步停下并说明原因，该周已有周汇总分支或目录时也不覆盖。它做的事：

1. 运行 `weekly_rollup.py build`，周次取最近一个周日。
2. 读本周各报告的 `INDEX.md` 和 `RETROSPECTIVE.md`，写 `WEEKLY.md` 的「结论」，只引用表里的数值和报告里的错误行。
3. 把没按骨架写、因而没进表的复盘里的改进，补成候选行（编号 `N1` 起）。
4. 推送 `weekly/<周>` 分支，开只含 `docs/reports/weekly/<周>/` 的草稿 PR。

它不做的事：不合并，不改 backlog 状态，不替审核人填「决定」和「归类」，不把任何讲道文字、译文或反馈正文写进 PR，不写前端数值。

云端会话读不到本机文件，也没有 GCS 凭据。要让它读私有库（核对译文修正的类别、生成私有周汇总），需要维护者做两件事，agent 不能代做：

1. 建一个只读服务账号，对证据桶授 `roles/storage.objectViewer`；要导出前端报表的话，再对反馈数据库所在项目授只读的 Firestore 角色。
2. 把它的密钥放进 Claude 云端环境的环境变量。没有配置时，定时 agent 只生成公开版，并在 PR 里写明私有部分没做。

## 八、可用于每周迭代的内容

后端：

| 内容 | 状态 | 用来改什么 |
|---|---|---|
| 计算、等待、重复轮次时长，按阶段 | 已进周汇总 | 最贵的重做 |
| 部署次数、门禁结果、发布阶段失败事件 | 已接入；11-15 之前的报告没有复制这些文件 | 发布流程 |
| 错误的发现时机 | 已进周汇总，取决于复盘按骨架填写 | 把检查往上游挪 |
| 复盘里的改进建议 | 已进候选表 | 迭代清单 |
| 费用 | 有预算账本的运行已接入；订阅内的 CLI 调用没有计费 | 成本与模型选择 |
| 人工修正的数量与类别（英文审核、译文修正、审计修订、精简、重配） | 原始文件已在私有库；分类计数未实现 | 术语表、读法表、翻译 brief |
| 来源到达至页面上线的时长，是否赶上周日 | 未实现；需要来源到达时间进 journal | 「按时」 |
| 生产期间改了多少生产代码 | 未实现；可由锁定标签与发布提交比较得出 | 「边生产边修」 |

前端：

| 内容 | 状态 | 用来改什么 |
|---|---|---|
| 打开、播放、下载的逐层会话数 | 聚合已实现，仅私有 | 入口和首屏 |
| 46 类动作的会话数 | 聚合已实现，仅私有 | 哪些功能值得做 |
| 同步微调和前后跳转集中的分钟 | 聚合已实现（达到 5 次才列出），仅私有 | 反推到句子，交回 L3 滞后或对齐 |
| 正文语言、音轨语言、平台三维收听 | 聚合已实现，仅私有 | 各语言的投入排序 |
| 听声定位触发、成功率、失败原因 | 聚合已实现，仅私有 | 指纹索引和对齐门禁 |
| 赞踩与问题反馈的分类计数 | 未实现 | 质量线索 |
| smoke、HTTP 核验 | `smoke-*.json` 与 `http-verification.json` 已进运行报告 | 前端回归 |

## 九、没做的部分和边界

- 11-15 主日证道的运行目录没找到，这份报告仍是手写的，本周的时间和部署数值缺它。
- 采集只接了逐句优先线的 `sfa_publish.py`；原地替换（`published_page_replace`）、现场对齐、研读手册、统计目录同步、海报还没有自动导出，仍按 runbook 手动。
- 11-15 之前的报告没有部署记录和门禁文件，所以 `publish.deployAttempts` 从下一次生产才有数值；第一条以它为信号的改进项在那之前会显示「本周没走到」。
- 人工修正的分类计数、来源到上线的时长、生产期间的代码改动三项指标未实现。
- 私有库目前只有本机 ADC 能读；云端 agent 的只读凭据没有配置。
- 前端数据只含开启匿名统计且成功送达的记录，统计目录没同步时会丢上报；浏览器日和设备日不是人数。
- 两周的来源长度和运行数不同，时间类指标不能直接算提速比。
- 周汇总的数值不证明设备播放或场地验收；它们是各自独立的状态。

## 十、命令

在仓库根目录：

```bash
# 生产结束（readback 通过时自动执行；失败或中止时手动）
.venv/bin/python tools/development/export_production_report.py artifacts/sentence-first-agent/<任一运行目录> [--also <共享目录>]
tools/development/publish_run_report.sh artifacts/run-reports/<报告名>

# 私有证据库
.venv/bin/python tools/ops/evidence_store.py check
.venv/bin/python tools/ops/evidence_store.py push <运行目录> [...]
ssh <主机> 'python3 - collect --tar - <运行目录> [...]' < tools/ops/evidence_store.py > bundle.tar.gz
.venv/bin/python tools/ops/evidence_store.py push-tar bundle.tar.gz
.venv/bin/python tools/ops/evidence_store.py pull runs/<运行目录名> --out artifacts/evidence-cache
.venv/bin/python tools/ops/evidence_store.py index --out docs/reports/weekly/private-evidence-index.json

# 前端报表（需要管理员凭据；先在 services/feedback 里 npm ci）
.venv/bin/python tools/development/weekly_frontend.py export --week <周日>

# 周汇总
python3 tools/development/weekly_rollup.py build --week <周日>
python3 tools/development/weekly_rollup.py finalize --week <周日>

# 带前端数值的私有周汇总
python3 tools/development/weekly_rollup.py build --week <周日> --frontend artifacts/frontend/<周日>/frontend-metrics.json --weekly-root artifacts/weekly-private
.venv/bin/python tools/ops/evidence_store.py put artifacts/weekly-private/<周日> --dest weekly/<周日>
```
