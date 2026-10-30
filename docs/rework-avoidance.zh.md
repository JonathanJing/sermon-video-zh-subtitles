# 少返工：口径、原因与开工前检查

状态：**手册；规则全部来自已发生的运行，不是新政策。** 校准日期 2026-10-30，依据 2026-10-22 至 10-26 的复盘、运行报告与本轮返工分析。适用两条线：逐句优先（[runbook](../experiments/sentence-first-agent/AGENTS.md)）与正式四层周更（[本地生产 Runbook](codex-local-production-runbook.zh.md)）。本页不改变任何门限、schema、豁免或发布流程。

## 一、口径：返工、变更、等待要分开

`tools/development/run_journal.py summary` 的口径是全仓唯一可比较的口径：

| 类别 | 定义 | 例子 | 怎么记 |
|---|---|---|---|
| **计算** | 本轮真正干活的时间 | TTS、翻译、合并、部署 | `started` → `finished` 之间的计算 |
| **等待** | 等人、等凭据、等外部服务 | 听审、授权、登记别人的会话 | `waiting` 带 `--waiting-on`，`resumed` 收尾 |
| **返工** | 同一阶段**重复轮次**里扣掉等待后的计算 | 重配一句、重出整轨、第二次部署 | 同阶段再次 `started` 会自动计入 `reworkSeconds` |

**变更是第四类，不是返工。** 用户改主意、窗口重批、口径变化（例如决定跟视频同步）产生的重做是变更；把它算成返工，会得出"少问用户、少验证"的错误结论。变更要单列，返工才值得优化。

一条可直接引用的例子：`20261024-sat400-clip-zh` 的 `l3.finish` 计算 231 秒、其中返工 150 秒，导出器自动算出来，不用手记（见 [运行报告](reports/runs/20261024-sat400-sermon-zh-ko-es/INDEX.md)）。

## 二、成本公式

> **返工成本 ≈ 已投入的下游层数 × 发现延迟。**

第 1 类"在真客户端才暴露"贵，不是错得离谱，而是发现时资产已绑好哈希、部署过、被目录引用。2026-10-22 那轮 13 小时 50 分里，可指认的返工约 2–2.5 小时（15–18%），其中约一半是工具与环境，一半是口径晚定。

推论：把手上的检查往上游挪一层，比把下游修得更快更值钱。下游每多一层，同一个错误的修复成本大约翻一倍。

## 三、六类原因（按代价排序）

| # | 原因 | 已发生的实例 | 代价 | 现在靠什么挡 |
|---|---|---|---|---|
| 1 | **契约只有真客户端校验** | 文稿 `durationSeconds` 2400.5 小于末句 2406.0，iOS `validateCues` 拒整份 | 约 25 分钟 + 一次额外部署 | 发布前逐句跑与 iOS 相同的规则；`validate_v2_asset_paths` |
| 2 | **修复时绕过了合同**（最贵） | 修文稿时写到 `content/<pageId>/<locale>-r2.json`，正式版 App 只认固定路径，整页消失；随后又发现英文对照漏发 | 3 轮部署、1 小时以上 | 修正字节只写原路径；`published_page_replace`（#1367）；快照校验在部署前拒绝非法路径 |
| 3 | **决策晚于它约束的下游** | 讲员映射到配音阶段才做（23 句重配）；标题不查表（海报返工）；同步与否开工后才定（整轨长 25%）；`preflight --english-package` 在 Spark 跑完后才跑 | 每次 10–40 分钟，不可回收 | 开工前问清三件事；`preflight.py`；标题表 |
| 4 | **身份漂移** | `speakerId=eric_geiger` 与 checkpoint 内 key `eric_pilot` 不一致（33 秒失败、重建 speech）；收据被覆盖（绑定链断）；目录音频哈希 50 分钟后失效（丢约 1.5 小时上报）；run 目录被清理（只能从 Spark 拉回） | 数十秒到永久性证据损失 | `preflight` 查映射；收据发布后不改写；保留小表 |
| 5 | **工具与环境脆弱** | 带 `--rm` 的容器让会话检查失败（40 分钟）；SSH 启动超时（5 分钟）；内存第 41 窗跌破保留线；测试容器打断别人会话（约 1 小时） | 累计约 1 小时/轮 | 多数已在脚本层修掉；内存预算由 `spark_run.sh` 开工前检查 |
| 6 | **并发的副作用** | 12 个翻译子代理跨份不一致（`당신/여러분`、世纪写法），复核修订 120/93/102 句；术语没走变体替换，13 处错、3 处进配音；三语落后 >1 秒各重出一次 | 合并期统一 + 重出 | 同一份 brief、合并后 `consistency_check.py`、独立审计、`--gap 0.05` |

第 6 类会随并行度上升。并行换来的时间，有固定的一部分要在合并期还回去——预算里要留，不是意外。

## 四、三个机制

1. **左移**：每个验收标准在写产物**之前**跑一次。已有 `preflight.py`、iOS 等价校验、`validate_v2_asset_paths`、catalog 快照校验；缺的是把"标题在表里""同步与否已定"也变成 preflight 的固定项。
2. **合同唯一入口**：任何修复都走正常发布路径——修正字节写原路径、重新绑定 release、旁路文件重新生成。禁止为了"不覆盖旧文件"另开新路径。这是第 2 类返工的唯一根治办法。
3. **身份不可变**：收据、run 目录、已发布字节进去就不再改写；改结论另存新版本，把新哈希记进 `run.md`。同一 artifact 只有一个写者。

## 五、开工前 10 分钟检查单

逐句优先线开工时跑（正式四层线把第 1、2 条换成 `check_run_start` 与预算规划）：

| # | 检查 | 命令 / 证据 | 失败后果 |
|---|---|---|---|
| 1 | 代码与作业树 | `git fetch origin`；`git rev-list --left-right --count origin/main...HEAD`；落后多时建 worktree | 缺脚本、导入旧包 |
| 2 | 依赖包来源 | `PYTHONPATH=packages/production/src:. python -c "import tongxing_production; print(...__file__)"` | 发布驱动导入旧包 |
| 3 | 冻结决策 | 形态（整期/片段）、三语、同步与否、发不发布、标题、讲员、窗口 | 下游返工的最大来源 |
| 4 | 标题在表 | 查[标题表](series-sermon-titles.zh.md)，英文标题一致就用表中三语；不一致则问用户并补表 | 海报、页面返工 |
| 5 | 讲员可配 | Registry 授权用途 + 该语种 `localeCapabilities`；`speakerId → speakerKey → checkpoint` 能解析 | TTS 首跑失败 |
| 6 | checkpoint 在 Spark | `ssh` `test -d` 逐个确认；Eric 的 checkpoint 路径要单独核（`eric_geiger`/`eric_pilot` 名字不一致） | 白占 GPU |
| 7 | 英文来源已人审 | `english-review.csv` 存在，`reviewedAt` 不早于用户结论；`preflight --english-package` 通过 | 英文对照被拒、翻译重做 |
| 8 | Spark 空闲且内存够 | 会话 `inspect`；`begin` 会停掉 llama-server 等非独占服务，之后 `memAvailable` 才够 8 副本的 96 GiB | 队列中途内存中止 |
| 9 | 凭据 | 要发布时查 Firebase 登录与 ADC 各一次 | 发布前才发现要授权 |
| 10 | 同页并发 | 同一页面别的代理/任务登记进 `run.md` 并记预计时间 | 目录哈希失效、上报丢失 |

## 六、发布侧旁路清单（三件套）

每次 release、文稿或字幕的哈希变化，这三个文件都要重新生成并部署；漏一个就是页面看起来正常、App 里缺东西：

1. `/english-reference/<pageId>.json`：App 的字幕与全文靠它显示英文；必须在 release 上线后生成。
2. 统计目录 `catalog.json`：必须含本页每条音轨的当前 MP3 哈希；2026-10-24 两次漏同步，共丢约两小时上报。
3. 公告 sidecar `weekly-announcements-v1.json` 与海报收据的 release／sourceIdentity 绑定。

做法：部署前先列出所有引用旧哈希的文件，重新生成，再部署；`verify`/`readback` 里要包含这三个。

## 七、还没挡住的部分

- 第 2 类的回归测试：还没有"修过的发布包仍合法"的用例。
- 标题与同步决策仍是人工记忆，不在 `preflight.py` 里。
- 旁路三件套仍靠发布后清单，未进发布驱动自动执行。
- 逐句线的 `waiting`/`resumed` 仍靠人记；10-24 两轮都没记，复盘里等待被算成 0。
- 子代理跨份一致性只在合并后检查，没有在派发时约束（同一份 brief 是约定，不是机制）。

## 八、证据索引

- [10-22 整期复盘：从设计到播客正式发布](reports/20261022-sentence-first-production-retrospective.zh.md)：问题与耗时表、下次可以更快的地方。
- [10-22 正式发布记录](reports/20261022-podcast-production-publication.zh.md)：`durationSeconds` → `-r2` 路径 → 整页消失的连锁，以及英文对照补发。
- [10-23 整期流程复盘](reports/20261023-sentence-first-full-episode-flow-review.zh.md)：串行队列、听审工具、preflight、SRT 派生的返工。
- [10-26 Spark TTS 内存复盘](reports/20261026-spark-tts-memory-retrospective.zh.md)：内存中止与 8 副本的预算。
- [运行报告 20261024-sat400-sermon-zh-ko-es](reports/runs/20261024-sat400-sermon-zh-ko-es/INDEX.md)：`reworkSeconds` 的自动计量示例。
- [测试运行复盘](test-run-retrospective.zh.md)：本手册第一节的三分口径来自这里。
