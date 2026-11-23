# 周汇总：20261122

服务周 2026-11-16 至 2026-11-22。本页由 `tools/development/weekly_rollup.py` 从本周已入库的运行报告生成，数值来自 `weekly.json`；**机器生成，`humanApproval=false`**。审核人在本页写结论和决定，合并本 PR 即批准这些决定，不批准任何内容产物。

## 结论

- **本页由机器生成，尚未经人审核。**
- 交付：`20261121-jesus-will-return-r4` 复盘称第 11 周三语（zh-Hans / ko / es）正式页已上线，发布门禁通过，交付类型 `four_layer_release`；人工听审为 `flagged_only`，收据没有写成整轨。`20261121-mbp14-sermon-zh` 是第 10 周 zh 的本机重渲诊断，不是发布，`humanApproval=false`，没有人耳听审。`20261116-ios-builtin-mic-route` 是 iOS 定向测试：模拟器通过，真机整轮 179 项中 8 项失败（复盘称均与本改动无关）。
- 最贵的重做：`20261121-jesus-will-return-r4` 第一次追落后把 82 句压成残句，整轮作废重渲，复盘记约 22 分钟；ko 译文比预算长 29%，该报告记 13 分钟整语重渲。本页表里重复轮次计算为 7m51s，只覆盖有 journal 的阶段，与复盘的人工估计不同口径。
- 上周改进项：上周没有待验证的改进项，无结果可报。本周复盘登记错误 11 条，晚发现占比 9.1%（上周 81.8%）；两周来源长度和运行数不同，不比较速度。
- 采集缺口：缺 journal 2 份、未上传私有证据 2 份、无 manifest 1 份（`20261121-mbp14-sermon-zh`）；`20261121-jesus-will-return-r4` 的 l3.lag-loop.zh-Hans、l4.stage2 未收尾，部署次数和门禁两列为空，所以部署数据不完整；前端数值未生成。

## 本周运行

| 报告 | 类型 | 墙钟 | 计算 | 等待 | 重复轮次 | 部署 | 门禁 | 复盘 | 私有证据 |
|---|---|---|---|---|---|---|---|---|---|
| [20261116-ios-builtin-mic-route](../../runs/20261116-ios-builtin-mic-route/INDEX.md) | 其他 | — | — | — | — | — | — | 已填 | 未上传 |
| [20261121-jesus-will-return-r4](../../runs/20261121-jesus-will-return-r4/INDEX.md) | 生产 | 2h23m | 1h17m | 0m00s | 7m51s | — | — | 已填 | 已上传 6 |
| [20261121-mbp14-sermon-zh](../../runs/20261121-mbp14-sermon-zh/INDEX.md) | 其他 | — | — | — | — | — | — | 已填 | 未上传 |

墙钟取该报告所有 journal 的最早到最晚事件；没有 journal 的报告显示「—」，不是零。「重复轮次」是同一阶段再次启动后的计算时间，包含返工和变更，下面由审核人区分。

## 对比上周

| 指标 | 本周 20261122 | 上周 20261108 | 变化 |
|---|---|---|---|
| 运行报告数 | 3 | 3 | 持平 |
| 其中生产运行 | 1 | 2 | -1 |
| 生产墙钟 | 2h23m | 5h03m | -2h40m |
| 生产计算 | 1h17m | 49m30s | +28m01s |
| 生产等待 | 0m00s | 0m00s | 持平 |
| 重复轮次计算 | 7m51s | 3m40s | +4m11s |
| 重复轮次占计算比 | 10.1% | 7.4% | +2.7 个百分点 |
| 发布阶段失败事件 | 5 | 4 | +1 |
| 复盘登记的错误 | 11 | 11 | 持平 |
| 预检发现 | 0 | 2 | -2 |
| 占用资源后发现 | 1 | 2 | -1 |
| 发布后发现 | 0 | 7 | -7 |
| 晚发现占比 | 9.1% | 81.8% | -72.7 个百分点 |
| 无 manifest 的报告 | 1 | 1 | 持平 |
| 缺 journal 的报告 | 2 | 1 | +1 |
| 复盘未填完 | 0 | 1 | -1 |
| 未上传私有证据 | 2 | 1 | +1 |

两周的来源长度和运行数不同时，时间类指标不能直接算提速比。

## 上周改进项结果

没有待验证的改进项。

## 错误与发现时机

| 报告 | 层／阶段 | 现象 | 发现时机 | 提交或 PR |
|---|---|---|---|---|
| 20261116-ios-builtin-mic-route | 真机整轮（7 项单测） | `NSCocoaErrorDomain Code=260`，读不到 fixture | 未标明 | 建议加 `XCTSkip`（见改进） |
| 20261116-ios-builtin-mic-route | 真机整轮（1 项 UI） | `TongxingUITests-Runner (10788)` 初始化失败，`Timed out while enabling automation mode` | 未标明 | 操作员设备设置 |
| 20261116-ios-builtin-mic-route | 真机调试 | `xcode_lldb attach` 三次都在约 35 s 报「process never stopped」 | 未标明 | 记在本报告 |
| 20261121-jesus-will-return-r4 | — | 2000 年前后的年份读成「一千九百八十」「二千二十四」 | 未标明 | — |
| 20261121-jesus-will-return-r4 | — | `lag_loop` 在重建 speech 时崩：`spokenForms keys not found` | 未标明 | — |
| 20261121-jesus-will-return-r4 | — | 第一次追落后把 82 句压成残句（「可后靠，我不因失礼。」） | 未标明 | — |
| 20261121-jesus-will-return-r4 | — | 对齐 sidecar 绑不上目录（schemaVersion / release 哈希口径 / 窗口末值 0.0003 s 偏差） | 未标明 | — |
| 20261121-jesus-will-return-r4 | — | 目录重绑后 `publish` 报 `Baseline catalog differs` / `Baseline snapshot is incomplete` | 未标明 | — |
| 20261121-jesus-will-return-r4 | — | `stage1` 拒绝覆盖已发布 content（想补 `sourceWindow`） | 未标明 | — |
| 20261121-mbp14-sermon-zh | 预检／内存门槛 | 20 GiB 默认门槛在本机不可达（桌面常开时 11.6–18.8 GiB） | 未标明 | 本 PR |
| 20261121-mbp14-sermon-zh | 报告／导出器 | 导出器把整段墙钟算成 0m03s | 占用资源后 | 本 PR |

## 重复轮次：返工还是变更

<!-- 审核人在「归类」填 返工 或 变更。用户改主意、口径变化造成的重做是变更，不算返工。 -->
| 报告 | 阶段 | 重跑次数 | 重复轮次计算 | 归类 |
|---|---|---|---|---|
| 20261121-jesus-will-return-r4 | l4.publish | 5 | 3m36s | — |
| 20261121-jesus-will-return-r4 | l4.baseline | 4 | 3m20s | — |
| 20261121-jesus-will-return-r4 | l3.finish | 3 | 0m19s | — |
| 20261121-jesus-will-return-r4 | l3.finish | 2 | 0m17s | — |
| 20261121-jesus-will-return-r4 | l4.assets | 1 | 0m13s | — |
| 20261121-jesus-will-return-r4 | l3.finish | 1 | 0m05s | — |
| 20261121-jesus-will-return-r4 | l4.readback | 2 | 0m02s | — |
| 20261121-jesus-will-return-r4 | l4.publish-check | 3 | 0m00s | — |
| 20261121-jesus-will-return-r4 | l4.stage1 | 1 | 0m00s | — |
| 20261121-jesus-will-return-r4 | l4.validate | 2 | 0m00s | — |
| 20261121-jesus-will-return-r4 | l2.consistency | 1 | 0m00s | — |
| 20261121-jesus-will-return-r4 | l1.preflight | 1 | 0m00s | — |
| 20261121-jesus-will-return-r4 | l2.consistency | 1 | 0m00s | — |
| 20261121-jesus-will-return-r4 | l2.consistency | 1 | 0m00s | — |
| 20261121-jesus-will-return-r4 | l4.stage2 | 1 | 0m00s | — |

## 候选改进

<!-- 审核人填后三列：决定写 接受／拒绝／推迟；接受的必须有 backlog ID 和验证信号，信号写成 `指标 比较符 数值`，指标名见 weekly.json 的 metrics。每周最多接受 3 条。可以自己加行。 -->
| 编号 | 来源 | 类别 | 改进 | 依据 | 决定 | backlog ID | 验证信号 |
|---|---|---|---|---|---|---|---|
| C1 | 20261116-ios-builtin-mic-route | 质量 | 把 7 个 `#filePath` fixture 测试改成 bundle resource，或先用 `FileManager.fileExists` 判断后 `XCTSkip` | 真机 7 项失败 | — | — | — |
| C2 | 20261116-ios-builtin-mic-route | 预检 | 跑真机整轮前先确认「启用 UI 自动化」和 fixture 依赖 | 真机 1 项 UI runner 失败 | — | — | — |
| C3 | 20261116-ios-builtin-mic-route | 流程 | 没有可用物理设备时先确认再准备构建 | 本次在设备接入前先做了签名与构建准备 | — | — | — |
| C4 | 20261121-jesus-will-return-r4 | 流程 | 把「目录重绑后必须重封存」写进发布 playbook | 本轮两次 publish 失败均因此 | — | — | — |
| C5 | 20261121-jesus-will-return-r4 | 质量 | 同步 run 默认「先剪静音、再逐句加速 ≤1.15」 | zh 24.79 s → 2.73 s、ko 16.94 s → 5.06 s、es 11.47 s → 7.65 s，且零删字 | — | — | — |
| C6 | 20261121-jesus-will-return-r4 | 预检 | 第 11 周手册 candidate 只能等 release 上线后跑，要预留第 4 次部署 | 本轮把手册与海报合并成第二次发布意图 | — | — | — |
| C7 | 20261121-jesus-will-return-r4 | 工具 | 反馈目录追加脚本（导出→追加→打包→部署→核验）目前是一次性脚本 | 本轮按 prep 文档手工执行 | — | — | — |
| C8 | 20261121-mbp14-sermon-zh | 预检 | 起跑门槛改用实测值 15 GiB（已改默认与 runbook） | 冷首窗峰值 16.73 GB、13.7 GiB 起跑也能完成、整期最低 9.53 GB | — | — | — |
| C9 | 20261121-mbp14-sermon-zh | 流程 | `tts_sentences.py` 写 `journal.ndjson` 的 `l3.tts` started/finished 与 TTS 墙钟，让导出器能自动汇总本机渲染 | 导出器只看到 3 秒 | — | — | — |
| C10 | 20261121-mbp14-sermon-zh | 速度 | 本机 RTF 0.337，优于 2026-11-09 组件估计（0.368），整期 zh 约 9 分钟；可据此更新 runbook §0.1 的保守估计 | 535.1 s／1,586.1 s | — | — | — |
| C11 | 20261121-mbp14-sermon-zh | 质量 | 本机整轨与发布版逐句时长平均差 0.32 s、最大 2.0 s，属于不同执行身份；若要替换线上音轨，必须人工整轨听审并另立收据 | `8167d7e4…` vs `93a031dc…` | — | — | — |
| N1 | 20261121-jesus-will-return-r4 | 预算 | ko 预算按 ×1.25 预留，或由用户决定是否把 ko 的 atempo 上限从 1.15 提到 1.20 | 复盘「下周可执行清单」第 3 条 | — | — | — |
| N2 | 20261121-jesus-will-return-r4 | 纪律 | 修复、重渲前确认 `pgrep tts_sentences.py` 为空，GPU 只允许一路 | 复盘记 ko 因此慢约 15% | — | — | — |
| N3 | 20261121-jesus-will-return-r4 | 工具 | 对齐 sidecar 用工具生成，不再手搓；海报同时上传 600×900 预览 | 复盘记 sidecar 绑定四次失败，约 15 分钟 | — | — | — |
| N4 | 20261121-jesus-will-return-r4 | 流程 | 反馈目录历史缺陷（11-01、11-08、11-15）单开热修意图 | 复盘「遗留状态」 | — | — | — |

## 前端

前端数值是私有运营资料，不进本页（[使用统计](../../../sermon-app-usage.zh.md)规定不提交 Git）。本周三份报表在私有证据库 `frontend/<周>/`，带前端数值的私有周汇总在 `weekly/<周>/`。审核人在此只写结论：

待填写。

## 采集缺口

- `20261116-ios-builtin-mic-route`：私有证据未上传。
- `20261121-jesus-will-return-r4`：journal 里未收尾的阶段：l3.lag-loop.zh-Hans、l4.stage2。
- `20261121-mbp14-sermon-zh`：不是导出器生成的（无 manifest），没有可比数值；私有证据未上传。

## 证据边界

- 本页只汇总已入库的运行报告；不在仓库里的运行不在本页。
- 代码与测试、发布与 HTTP、浏览器渲染、设备播放、场地验收是分开的状态；本页的数值不证明后两者。
- 私有证据（译文、审核表、听审结论、反馈正文）在私有证据库，本页只引用计数和哈希。
