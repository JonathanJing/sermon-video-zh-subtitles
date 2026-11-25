# 周汇总：20261108

服务周 2026-11-02 至 2026-11-08。本页由 `tools/development/weekly_rollup.py` 从本周已入库的运行报告生成，数值来自 `weekly.json`；**机器生成，`humanApproval=false`**。审核人在本页写结论和决定，合并本 PR 即批准这些决定，不批准任何内容产物。

## 结论

<!-- 三句话：本周是否按时交付、最贵的一处重做、下周只做哪几条。只引用下面表里的数值。 -->
**基线周，机器填写，未经人工审核。** 本页是周汇总工具的第一份产物，用来给 2026-11-15 那一周提供对比基线。

- 本周 2 份生产报告（主日证道、播客）加 1 份页面热修。主日证道的 journal 只记到 1h27m／计算 3m17s，[复盘](../../runs/20261108-jesus-is-just/RETROSPECTIVE.md)写明实际墙钟约 2h57m：发布阶段当时没写 journal，所以本页的时间类数值偏低，不能当作真实耗时。
- 复盘登记 11 个错误，其中 7 个在发布后才发现，晚发现占比 81.8%。这是本周最值得改的一项。
- 下面 9 条候选改进来自主日证道的复盘，决定列留给审核人。其中「发布意图清单」「收尾只认带两个开关的 gate」两条已写进 runbook，并在 11-15 的生产里执行过，但当时没有登记验证信号。

## 本周运行

| 报告 | 类型 | 墙钟 | 计算 | 等待 | 重复轮次 | 部署 | 门禁 | 复盘 | 私有证据 |
|---|---|---|---|---|---|---|---|---|---|
| [20261108-jesus-is-just](../../runs/20261108-jesus-is-just/INDEX.md) | 生产 | 1h27m | 3m17s | 0m00s | 1m01s | — | — | 已填 | 已上传 11 |
| [20261108-jesus-is-just-podcast](../../runs/20261108-jesus-is-just-podcast/INDEX.md) | 生产 | 3h36m | 46m13s | 0m00s | 2m39s | — | — | 非骨架格式 | 已上传 6 |
| [20261108-wechat-banner](../../runs/20261108-wechat-banner/INDEX.md) | 其他 | — | — | — | — | — | — | 缺失 | 未上传 |

墙钟取该报告所有 journal 的最早到最晚事件；没有 journal 的报告显示「—」，不是零。「重复轮次」是同一阶段再次启动后的计算时间，包含返工和变更，下面由审核人区分。

## 对比上周

| 指标 | 本周 20261108 |
|---|---|
| 运行报告数 | 3 |
| 其中生产运行 | 2 |
| 生产墙钟 | 5h03m |
| 生产计算 | 49m30s |
| 生产等待 | 0m00s |
| 重复轮次计算 | 3m40s |
| 重复轮次占计算比 | 7.4% |
| 发布阶段失败事件 | 4 |
| 复盘登记的错误 | 11 |
| 预检发现 | 2 |
| 占用资源后发现 | 2 |
| 发布后发现 | 7 |
| 晚发现占比 | 81.8% |
| 无 manifest 的报告 | 1 |
| 缺 journal 的报告 | 1 |
| 复盘未填完 | 1 |
| 未上传私有证据 | 1 |

没有更早的周汇总，本周是基线。

## 上周改进项结果

没有待验证的改进项。

## 错误与发现时机

| 报告 | 层／阶段 | 现象 | 发现时机 | 提交或 PR |
|---|---|---|---|---|
| 20261108-jesus-is-just | L4 发布范围 | 首轮只发页面/英文对照，漏掉现场对齐、研读手册、统计目录 | 发布后 | — |
| 20261108-jesus-is-just | L4 完成信号 | 首次 gate 返回 pass 就当成收尾 | 发布后 | — |
| 20261108-jesus-is-just | L4 部署粒度 | 一个页面 **13 次**托管部署，远超「一次发布意图 ≤3 次」 | 发布后 | — |
| 20261108-jesus-is-just | L1 英文包 | 包缺 `approvedWindow.evidence`、`transcript.artifact`、`review.evidence`，英文对照无法构建 | 占用资源后 | — |
| 20261108-jesus-is-just | L4 目录身份 | catalog `sourceIdentitySha256` 停在首版包 | 发布后 | — |
| 20261108-jesus-is-just | L4 门禁 | `content.drift` 失败，音轨比窗口短 2.5–4.2 s | 发布后 | 已提交 `fa8f6ecc` |
| 20261108-jesus-is-just | L3 滞后 | 首版整轨滞后 zh 18.8 s／ko 214.6 s／es 117.0 s | 占用资源后 | — |
| 20261108-jesus-is-just | L3 数字读法 | 千分位被拆成裸 `000`：`삼,영년`、`tres.cero años` | 预检 | — |
| 20261108-jesus-is-just | L4 对齐 | 页面/ release 被并发代理改动后，对齐 sidecar 停在旧 release | 发布后 | `06cee2b2` |
| 20261108-jesus-is-just | 门禁 | 门禁存在缺口：对齐只查指纹不查 release 绑定 | 发布后 | `06cee2b2` |
| 20261108-jesus-is-just | 研读手册 | 工具里第 9 周标题「必使罪恶终结」与标题表「必终结罪恶」不一致，bind 会拒 | 预检 | `b1180124` |

## 重复轮次：返工还是变更

<!-- 审核人在「归类」填 返工 或 变更。用户改主意、口径变化造成的重做是变更，不算返工。 -->
| 报告 | 阶段 | 重跑次数 | 重复轮次计算 | 归类 |
|---|---|---|---|---|
| 20261108-jesus-is-just | l3.finish | 2 | 1m00s | — |
| 20261108-jesus-is-just | l1.start | 1 | 0m01s | — |
| 20261108-jesus-is-just | l1.preflight.setup | 1 | 0m00s | — |
| 20261108-jesus-is-just | l2.consistency | 2 | 0m00s | — |
| 20261108-jesus-is-just | l1.preflight | 1 | 0m00s | — |
| 20261108-jesus-is-just-podcast | l4.publish | 2 | 1m04s | — |
| 20261108-jesus-is-just-podcast | l4.baseline | 1 | 1m01s | — |
| 20261108-jesus-is-just-podcast | l4.assets | 2 | 0m28s | — |
| 20261108-jesus-is-just-podcast | l4.stage-english-reference | 1 | 0m04s | — |
| 20261108-jesus-is-just-podcast | l4.readback | 1 | 0m01s | — |
| 20261108-jesus-is-just-podcast | l4.preflight | 1 | 0m00s | — |
| 20261108-jesus-is-just-podcast | l4.publish-check | 2 | 0m00s | — |
| 20261108-jesus-is-just-podcast | l1.preflight | 2 | 0m00s | — |

## 候选改进

<!-- 审核人填后三列：决定写 接受／拒绝／推迟；接受的必须有 backlog ID 和验证信号，信号写成 `指标 比较符 数值`，指标名见 weekly.json 的 metrics。每周最多接受 3 条。可以自己加行。 -->
| 编号 | 来源 | 类别 | 改进 | 依据 | 决定 | backlog ID | 验证信号 |
|---|---|---|---|---|---|---|---|
| C1 | 20261108-jesus-is-just | 流程 | 开跑前先写「发布意图清单」七件套（页面/release/目录/英文对照/对齐/手册/统计目录），写进 run.md 再动手 | 首轮漏 3 件，用户追问才补 | — | — | — |
| C2 | 20261108-jesus-is-just | 流程 | 周日证道收尾只认 `--require-guide --require-alignment` 的 gate；不带开关的 pass 不算完成 | 首次 gate 的假 pass | — | — | — |
| C3 | 20261108-jesus-is-just | 预检 | 英文包在首次部署前跑一次 `published_english_reference.build_reference` 干跑（对候选快照） | 首次部署后才发现包缺证据绑定，多走 4 次 replace | — | — | — |
| C4 | 20261108-jesus-is-just | 预检 | 候选快照阶段先跑一次 gate（文档已要求三处都跑），再首次部署 | 音轨补齐问题是线上 gate 才发现的 | — | — | — |
| C5 | 20261108-jesus-is-just | 速度／成本 | 精简后先在本地用 `lag_loop --check-only` 估收敛，再一次全量重配 | 三语各做了一轮全量重渲（22m） | — | — | — |
| C6 | 20261108-jesus-is-just | 质量 | 对齐索引绑定**已发布 MP3** 的 sha，不是 `track.wav` | `Invalid fingerprint binding` 一次 | — | — | — |
| C7 | 20261108-jesus-is-just | 流程 | 研读手册标题、页面标题、海报标题统一从 `docs/series-sermon-titles.zh.md` 取；工具常量随表更新 | 手册标题不一致一次 | — | — | — |
| C8 | 20261108-jesus-is-just | 预检 | 多代理共用 checkout 时，发布前先 diff 线上版本与本地快照，列出本页 release/资产是否被别人改过 | 本次靠人眼复核才发现 | — | — | — |
| C9 | 20261108-jesus-is-just | 可观测 | 发布阶段的部署与返工也走 `run_journal`，否则 timings 只有 3m17s | journal 1h27m vs 实际 2h57m | — | — | — |

## 前端

前端数值是私有运营资料，不进本页（[使用统计](../../../sermon-app-usage.zh.md)规定不提交 Git）。本周三份报表在私有证据库 `frontend/<周>/`，带前端数值的私有周汇总在 `weekly/<周>/`。审核人在此只写结论：

基线周没有导出前端报表。

## 采集缺口

- `20261108-jesus-is-just`：journal 里未收尾的阶段：l3.review.zh-Hans。
- `20261108-jesus-is-just-podcast`：复盘不是八项骨架，错误和改进没有进表。
- `20261108-wechat-banner`：不是导出器生成的（无 manifest），没有可比数值；复盘未填写；私有证据未上传。

## 证据边界

- 本页只汇总已入库的运行报告；不在仓库里的运行不在本页。
- 代码与测试、发布与 HTTP、浏览器渲染、设备播放、场地验收是分开的状态；本页的数值不证明后两者。
- 私有证据（译文、审核表、听审结论、反馈正文）在私有证据库，本页只引用计数和哈希。
