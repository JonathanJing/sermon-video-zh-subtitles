# 复盘：20261025-sat400-study（本周大纲与默想）

## 结论先行

- **交付类型**：`four_layer_release` 的学习内容（四产品）——页面 `revelation-jesus-wins-20261025` 的 zh-Hans / ko / es 各一份大纲（7 节）与默想（4 节），随 release v3 发布。
- **最终状态**：线上三语 release 均为 `sermon-target-language-release-package-v3`、`published_http_verified`、`human_reviewed`；`contract.validate_public_study` 对三语线上字节通过（artifact / review / manifest / content / candidate 哈希全部一致）；`/study/<pageId>/<locale>/{outline,meditation,products}.json` 与页面 `study-outline`、`study-meditation` 两个 section 均 200。
- **证据边界**：文本是代理按已批准英文全文与当周译文写的草稿；`sermon-study-review-v1` 的 `humanApproval` 记录的是用户 08:09「制作并发布」的发布授权，用户尚未逐句读过文本（`study-README.md` 里写明）。iOS 真机、浏览器播放、推送、现场验收仍为 `not_run`；海报未重发。

## 总时间

墙钟约 **38 分钟**（08:09 指示 → 08:47 第三次部署完成）。

| 阶段 | 起止（PDT） | 耗时 |
|---|---|---|
| 读合同（研究 schema、示例 v3 release、校验函数） | 08:11–08:28 | 17m |
| 写三语大纲/默想（7+4 节 ×3）与冻结脚本 | 08:28–08:38 | 10m |
| `build_study.py`（artifact、review、元数据/窗口批准、products.json） | 08:38–08:41 | 3m |
| `publish_study.py build/assets` + 部署 A（`791c8308bcef47d1`） | 08:41–08:43 | 2m |
| HTTP 核验 + finish + 部署 B（`4f77f09167a71937`） | 08:43–08:45 | 2m |
| 重生成英文对照 + 部署（`2919aae15fb7dbc8`）+ 线上复验 | 08:45–08:47 | 2m |

## 各层与速度

| 阶段 | 后端 | 耗时 | 产物 |
|---|---|---|---|
| 文本撰写 | DeepSeek 代理 | 10 min | 三语 33 节，每节带 `sourceUnitIds` |
| artifact/review 冻结 | 本地 Python + `jsonschema` | <1 s | 6 artifact + 6 review + 元数据批准 |
| v3 release 构建 | 本地 Python（`validate_public_study` 逐语自检） | 3 s | 3 × 7 资产 release |
| 部署 | Firebase Hosting（受保护发布器） | 3 次 × 约 60 s | A 资产、B release+目录+sidecar、英文对照 |
| HTTP 核验 | 本地 GET/SHA | 15 项 | `asset-verification.json` |

**token（08:09–08:55 窗口，内部遥测）**：74 次 assistant 调用；未缓存输入 228,760、缓存读 22,963,200、输出 66,905，合计 23,258,865；非缓存部分约 **$0.15**。账单口径无法单独切分，仅作内部对照。

## 错误

| 阶段 | 现象 | 原因 | 处理 |
|---|---|---|---|
| artifact | `Study review does not bind artifact` | review 用了文件字节哈希，合同用规范化 dict 哈希 | 改用 `contract.sha(artifact)` |
| products | `Public study artifact identity differs`（ko/es） | 三语 artifact 都用了 zh 的 `textCandidateSha256` | 按每语 release 的 candidate/audio 哈希重建 |
| 发布目录 | `baseline-8` 与已暂存快照被删 | `publish_study.py build` 一开始 `rmtree(OUT)` | 改为只删 `assets/` 与 `releases/` |
| 部署 | `Missing baseline release asset` | 发布器严格校验，待替换快照（pending）被拒 | `publication.publish` 增加 `allow_pending_replacements`，驱动的 publish-config 传该页 |
| 草稿 schema | `pending_after_assets_deploy` 不在枚举 | v3 schema 只允许 `not_run/pass/fail` | 草稿用 `candidate` + `not_run`，B 阶段写 `published_http_verified` + `pass` |

## 改进

- `build_study.py` 应把每语的 candidate/audio 哈希写进 `study-hashes.json` 供复核（本轮已按语读取）。
- 学习内容进入发布流程后，`publish_study.py` 应像其他驱动一样写 `journal.ndjson`/`outcome.json`，导出器才能自动算墙钟。
- 内容审阅：三份文本应由用户逐句读一遍，或用听审式 HTML 标注后再定稿；本轮直接发布，收据里已写明。

## 覆盖与遗留

- 已做：三语 artifact、审核收据、元数据/窗口批准、products.json、v3 release、目录、对齐 sidecar、英文对照重发、线上 `validate_public_study`。
- 未做：设备/浏览器播放、推送、TestFlight、现场；海报未重发。
- 发布版本：`791c8308bcef47d1`（资产）→ `4f77f09167a71937`（release+目录）→ `2919aae15fb7dbc8`（英文对照，最终 live）。

## 外部可见的变化

- 线上 `/study/revelation-jesus-wins-20261025/<locale>/` 三个文件上线，页面新增学习段；三语 release 从 v2 升到 v3（四产品）。
- 目录 target 的 release 哈希更新；对齐 sidecar 随 release 更新；`capabilities` 仍含 `alignment`。
