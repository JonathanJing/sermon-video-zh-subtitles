# 已发布页面的原地替换通道

状态：**已实现，有定向测试；2026-10-24 的正式页面没有用它**（那次改了页面身份，走的是"撤回后重建"）。本页只说明这条通道，不改变任何门限、披露或审核状态。

## 什么时候用

已经发布、App 正在显示的页面，需要**改正页面、文稿、字幕或音轨的字节**，而页面身份（pageId、来源、locale 集合）不变时。

不适用：

- 新增页面、新增语言、更换来源身份 —— 走正常的 assets → releases → catalogs 流程。
- 听音定位的指纹索引 —— 它由 release/content 的哈希推导，替换 release 之后要重新生成并重新绑定。

## 为什么普通流程做不了

正式发布器按"新增文件"设计：

1. `stage()` 拒绝覆盖已发布的文件；
2. 目录里的 release 用哈希绑定它发布时的字节，替换文稿/音轨后，release 与文件不再一致，`validate_catalog_snapshot` 会拒绝（`Missing baseline release asset`）；
3. release 只有在资产上线并 HTTP 核验后才能标 `published_http_verified`，而核验又要求字节先上线 —— 直接改字节会把核验声明变成假的。

## 方法：两次部署，中间状态显式

模块 `tongxing_production.delivery.published_page_replace`（入口 `tools/ops/run.py published_page_replace`）：

1. **assets**：以完整正式站快照为基线，写出替换后的字节，目录与上一份 release 保持不变。
   这个快照只在把该 page id 放进 `contract.validate_catalog_snapshot(..., allow_pending_replacements={page_id})`
   时才通过；pending 集合写进 `staged-changes.json`，其他页面仍按严格规则校验。
   部署这个快照。
2. **HTTP 核验**替换后的资产（GET/SHA，MP3 查 Range），把结果写成一个 JSON。
3. **finish**：写出新的 release（`published_http_verified` + 上面的核验证据），更新目录里该 target 的
   release 哈希，v4/v3 按 v5 重新投影；这个快照按**严格规则**校验并通过。部署它。

中间窗口内，目录仍指向旧 release，而线上字节已经是新的；App 读取该语言时可能因为哈希不一致而拒绝显示。窗口应尽量短（秒级到分钟级），且只在用户授权的内容修正时使用。

## 命令

```bash
# 1) 快照 A：只允许覆盖已存在的文件，目录不动
.venv/bin/python tools/ops/run.py published_page_replace assets \
  --baseline artifacts/<完整正式站快照> \
  --out artifacts/<替换候选-A> \
  --page-id '<pageId>' \
  --replace-dir artifacts/<按 public/ 结构的替换文件>

# 2) 部署 A、核验资产（按现有发布流程）

# 3) 快照 B：新 release + 目录
.venv/bin/python tools/ops/run.py published_page_replace finish \
  --assets artifacts/<替换候选-A> \
  --out artifacts/<替换候选-B> \
  --page-id '<pageId>' \
  --release-dir artifacts/<每语言一个 <locale>.json> \
  --evidence artifacts/<核验结果.json>
```

两个子命令都会写出 `publish-config.json`；部署仍走受保护的发布器，每次部署都需要用户授权。

页面本地新增只允许 `/study/<pageId>/` 下的文件（四产品的大纲、默想与 `products.json`），`finish` 允许重写 `/alignment/<pageId>.json`。部署待替换快照时，发布器按 `publish-config.json` 里的 `allowPendingReplacements` 只对点名的页面放宽；其他调用方不传就是严格校验。

## 约束与证据

- 只接受**已存在**的路径；新增页面或语言会被拒绝（`Replacement must overwrite an existing published file`）。
- `allow_pending_replacements` 只对点名的页面跳过 release↔资产哈希；其他页面严格校验，默认是空集合，任何别的调用方都看不到这个放宽。
- `finish` 要求每个新 release 的 `httpVerification.evidenceSha256` 等于传入核验文件的哈希，且状态为 `published_http_verified`。
- 最终快照必须通过 `validate_catalog_snapshot` 的严格校验；`staged-changes.json` 的 `pendingReplacements` 清空。
- 定向测试：`tests/test_published_page_replace.py`（5 项：pending 只对点名页面放宽、finish 严格通过、只允许已存在路径、页面必须唯一、未核验的 release 被拒）。

## 与"撤回重建"的区别

2026-10-24 的官方录音替换改了来源媒体与窗口，属于**页面身份变化**：旧发布先撤回（目录移除、资产下线），再按新身份重建。那条路径见 `experiments/sentence-first-agent/publish_sat400_v2.py` 与对应 run.md；本页的原地替换不改变页面身份。
