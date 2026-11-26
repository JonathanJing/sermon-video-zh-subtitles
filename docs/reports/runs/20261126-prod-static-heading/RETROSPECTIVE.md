# 复盘：20261126-prod-static-heading

数据见同目录 INDEX.md 和 manifest.json。

## 结论先行

- 交付类型：已发布页面的原地替换（`published_page_replace`），只换静态页 `/pages/<pageId>/<locale>/index.html` 的标题区，不是新发布。状态：两页都 `deployed`，门禁 `pass`。
- 范围：用户选了「只发最新一周」：`if-i-had-more-time-jesus-will-return`（播客）和 `revelation-jesus-will-return-20261122`（证道），各三语。其余 15 个有静态页的页面没动，仍是旧标题区。
- 标题区按 #1627 的规则重出：系列 / 标题 / 日期 · 讲员 / 经文；标题已以「系列 · 」开头时不再单列系列。页面其余字节不变。
- 版本：`dd44249861e76679` → 播客 A `c0f6fce65b54cfaf` → 播客 B `31a7d57c0f2b49d9` → 证道 A `d8144f86a27c9769` → 证道 B `2fe2f08796f3149c`。
- 证据边界：HTTP 字节核对、`sfa_publish_gate`、无头浏览器冒烟通过；没有 iOS 真机、微信内或会场验收。

## 总时间

- 约 70 分钟墙钟，大部分是摸清哪些文件绑着 release 哈希和找 Layer 1 来源；四次部署各约 1.5 分钟。
- 中间窗口（A 已上线、目录仍指向旧 release）：播客约 3 分钟（16:02:26–16:05:36 UTC，其中 B 两次因英文来源路径失败重跑），证道约 2 分钟（16:09:42–16:11:50 UTC）。
- 上一次同类：20261108-wechat-banner（单页、四次部署）。

## 各层模型、耗时与速度

| 层／阶段 | 模型或后端 | 推理强度／tier | 调用次数 | 计算耗时 | token 或音频秒数 | 速度 | 费用 | 证据 |
|---|---|---|---|---|---|---|---|---|
| L1–L3 | not_run | | | | | | | |
| L4 原地替换 | `published_page_replace` + `guarded_hosting_publish.py` | — | 4 次部署 | 每次约 1.5 分钟 | — | — | 0 | `*/snapshot-*/deployment-attempt-v2.json` |

## 每页改了什么

- 播客（B 相对替换前 10 个文件）：三语静态页、三语 release（页面哈希 + 核验证据）、v3/v4/v5 目录（只改三个 release 哈希）、英文对照（用 Layer 1 来源重出）。
- 证道（16 个文件）：同上，另有对齐 sidecar 的三个 release 哈希与目录对齐绑定、`weekly-announcements-v1.json` 三条公告的 `releaseSHA256`（`publishedAt`、海报、标题不变）、三份公告绑定收据（`metadataRebound: true`，海报收据来自 `docs/reports/runs/20261121-jesus-will-return-r4/`）、研读手册 manifest 条目。
- 证道的 Layer 1 英文来源不在本机，英文对照改为只替换三个 release 哈希。依据：播客页用来源重出的对照与「旧对照只替换 release 哈希」逐字节相同。
- 证道先离线演练 A+B（B 读快照 A 而不是线上），演练快照 B 严格校验通过后才部署；正式快照 B 与演练逐字节相同。
- 驱动脚本存于忽略目录 `artifacts/web-header-align-20261126/replace_heading.py`（仿 20261108 的 `finish_b.py`／`stage_c.py`）。

## 错误

| 层／阶段 | 现象 | 原因 | 发现时机 | 处理 | 回归测试 | 提交或 PR |
|---|---|---|---|---|---|---|
| 播客 B | 重出英文对照找不到 `english-source.json`，随后找不到 `window-approval.json` | 页面配置的来源路径相对于产出它的 worktree（`week12-podcast`），证据路径相对于当前目录 | 占用资源后（A 已上线） | 在该 worktree 内运行 B；证道改为先离线演练 | 无 | — |

## 可以改进的地方

| 类别 | 改进 | 依据（本报告的数值或错误） | 预期收益 | 负责人 | 跟踪 |
|---|---|---|---|---|---|
| 预检 | 原地替换在部署 A 之前先离线跑一遍 B（演练模式），并检查 Layer 1 来源可读 | 播客窗口因来源路径多开了约 1.5 分钟 | 中间窗口只剩部署时间 | 待定 | 待开 |
| 流程 | 把「列出所有绑定 release 哈希的文件并一起重绑」（公告、收据、对齐、手册、英文对照）收进 `published_page_replace` | 证道页 16 个文件靠手写驱动重绑 | 下次不必再摸索 | 待定 | 待开 |
| 质量 | 查明播客页 `/api/session` 400 | 20261126-prod-web-header-align 冒烟 | 播客页反馈可用 | 待定 | 待开 |

## 实际覆盖范围

- L1–L3：not_run。L4：两页三语静态页与其派生绑定。
- 门禁：证道 `--require-alignment --require-guide` 共 103+ 项 pass；播客 71 项 pass；两页各三语的 `page.heading` 与 `page.heading.http` 全部 pass。
- 冒烟（`--no-session`）：两页三语全部 pass。默认页仍是 `revelation-jesus-will-return-20261122`。
- 浏览器：证道 zh-Hans 静态页显示系列、标题、日期 · 讲员、经文。

## 遗留状态

- 其余 15 个页面的静态页仍是旧标题区，过不了新的 `page.heading` 门禁；只在重发这些页面时才会更新。
- 播客页 `/api/session` 400 未处理（反馈服务端）。
- iOS 新版本未发。
- 本地产物在忽略目录 `artifacts/web-header-align-20261126/`。

## 外部可见的变化

- 生产站版本 `2fe2f08796f3149c`：两页三语静态页的新标题区、对应 release 与目录哈希、证道的公告、对齐、手册绑定。
- 微信内／真机：not_run。TestFlight：not_run。
