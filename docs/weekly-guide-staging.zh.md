# 研读手册：未来周准备与讲道绑定

第 8–12 周先以独立 JSON 放在忽略的 `artifacts/`，`sermonPageId=null`。每周保留中文机器译稿的全部当周页、相关附录和另附的和合本（1919）经文；第 11 周的附录跨源页 174–175。机器翻译未经人工审校，`humanApproval=false`；不把它称为教会官方中文译本。摘要 manifest 记录源文件 SHA、各周原书页号、内容字节数和 SHA，不含原文或译文正文。

已验证的第 8–12 周 staging 保存在私有位置：`gs://sermon-zh-artifacts-ai-for-god/staging/revelation-study-guide/d6c6064e8fab11ab012edd9535372a9f99b83cd5240b6014f5451795a9198f86/406e27e9aafcf624a93cfc0cc820d181656c9cbde25cfb355b8805dd86c2aae9/`。其中包括五周 JSON 和 staging manifest，`source/` 下两个按哈希绑定的源文件，以及 `evidence/` 下两份绑定证据；均已独立下载回读验证。它们尚未关联讲道，属于非公开内容；服务器尚无供客户端消费的手册 manifest。

可恢复到 Git 忽略的本地目录，随后使用下文的绑定流程：

```sh
mkdir -p artifacts/weekly-guide-staging/restored
gcloud storage cp --recursive \
  'gs://sermon-zh-artifacts-ai-for-god/staging/revelation-study-guide/d6c6064e8fab11ab012edd9535372a9f99b83cd5240b6014f5451795a9198f86/406e27e9aafcf624a93cfc0cc820d181656c9cbde25cfb355b8805dd86c2aae9/*' \
  artifacts/weekly-guide-staging/restored/
```

绑定时将下文的 `--staging` 指向恢复目录，并将 `--source`、`--cuv` 指向其中 `source/` 下对应文件；撤回旧 Bundle 所需的证据可从 `evidence/` 使用。

运行前确认译稿与经文文件来自已确定版本；生成器强制匹配其 SHA，禁止自动替换源。输出目录必须是仓库内 Git 忽略的 `artifacts/` 新目录；此命令不上传、不发布：

```sh
.venv/bin/python tools/ops/run.py delivery.weekly_guide_staging stage \
  --source /path/to/revelation-series-guide.zh-Hans.md \
  --cuv /path/to/cuv-1919-revelation.json \
  --output artifacts/weekly-guide-staging/new-run
```

讲道尚未出现或页面标识尚未核实时，不编造或推算 ID。需要绑定时，提供完整、已封存且可通过 `validate_catalog_snapshot` 的 Hosting 快照和明确绑定文件：

```json
{"schemaVersion":"tongxing-weekly-guide-bindings-v1","bindings":[{"week":8,"pageID":"已核实的讲道页面ID"}]}
```

```sh
.venv/bin/python tools/ops/run.py delivery.weekly_guide_staging bind \
  --staging artifacts/weekly-guide-staging/new-run \
  --snapshot artifacts/verified-hosting-snapshot \
  --environment dev \
  --bindings artifacts/weekly-guide-staging/reviewed-bindings.json \
  --source /path/to/revelation-series-guide.zh-Hans.md \
  --cuv /path/to/cuv-1919-revelation.json \
  --output artifacts/weekly-guide-staging/bound-run
```

绑定必须通过快照的完整发布合同检查，以及与目标环境 verified live receipt 的版本、v5 目录和文件哈希比对；之后逐层核对 v5 页面、简体中文目标、release 与 content 哈希和身份，排除测试/诊断或已撤回的页面。正文的系列、标题、经文范围必须与该周手册一致；经文范围按已校验的和合本逐节 ID 集合比较，并非按日期推断。工具重新从已校验源重建 staging 并比较字节，缺失或不一致均失败。

既有线上 `/weekly-guides/manifest-v1.json` 和全部引用资源须逐个通过 live receipt 的字节数和 SHA 校验，输出保留所有旧条目与不可变资源。新增只接受尚不存在的 pageID；更新或撤回须显式声明 `operation` 为 `update` 或 `revoke`，附旧 entry 规范 JSON 的 SHA（`expectedEntrySha256`）和变更原因。撤回保留原身份与资源路径，状态变为 `revoked`。线上文件清单确无 manifest 时，必须明确传 `--initialize-empty` 才能初始化；不得把 Hosting SPA fallback 的 HTTP 200 当作文件存在。远端 manifest 条目绑定 editionId、sourceIdentitySha256 和 releasePackageJsonSha256，资源路径以内容 SHA 命名，记录精确字节数。

这些核对是本地、离线候选证据；准备结果明确 `prepared_not_uploaded`。同源 Hosting 是客户端信任根，清单中自报 SHA 用于检查文件与清单一致性，不证明服务器未被篡改。发布前必须重新获取 live version，并由现有 guarded publisher 比对基线；不同渠道的客户端和生产发布分别验收。

准备产物和云端上传是独立步骤；上线前仍需确保对应渠道许可、人工核对实际周次，使用仓库现有 guarded Hosting 发布机制和版本化合同，进行独立的线上字节回读与客户端验收。App 已安装版本是否支持读取远端清单必须单独核实，服务端上传不等于用户已能在 App 内看到内容。

要产生可交给 guarded publisher 的完整 Hosting 候选，将上述 `bind` 子命令改为 `candidate`，使用相同的参数，并把 `--output` 指向新的候选目录。工具会先验证 live receipt 和整个快照，再在新目录复制基线、保留所有既有文件与默认目录，加入清单和不可变手册资源，重做 seal 与合同校验，生成 `publish-config.json`。它不做线上写入；`tools/ops/guarded_hosting_publish.py --config <候选>/publish-config.json` 仅预检，实际部署需指定 `--execute` 并使用该发布器的锁、live version 核对与发布后回读。若基线变化，重新获取并生成候选，不得覆盖其他更新。

`revoked` 是客户端拒绝加载该条目并禁止回退的标记；它保留旧资源字节和 URL，**不是公网删除**。如需版权撤回或真正下架，必须单独处理公网对象、CDN、历史版本和缓存，并核实相应结果，不能以 tombstone 冒充完成 takedown。

### 撤回仅存在于 Bundle 的旧周

如需阻止尚无云端条目的已内嵌手册回退，显式绑定 `operation: "revokeBundled"`，提供具体 `pageID`、`week` 和撤回 `reason`，并额外传入 `--bundle-evidence <已冻结 identity evidence.json>`。工具严格校验 evidence 的固定 SHA 与目标环境；v5 条目须与 live catalog 的 edition、source identity 和 release 哈希完全一致。legacy 周必须具有完整的 source ID、URL、media 哈希和 source 时间窗口，并与 live receipt 绑定的 `weekly.json` 逐字段一致；不完整的旧来源不能构造 tombstone。

legacy tombstone 使用 `status: "revoked"` 和嵌套 `legacy` 强身份对象，不包含可下载资源或 v5 edition/release 字段；v5 bundle-only tombstone 使用 v5 三重身份而不包含资源路径。两类仅在原条目不存在时可创建：已有云端条目的修改仍需要 `update` / `revoke`、准确旧条目 SHA 和原因。客户端只对身份严格匹配的 tombstone 禁止读取和回退。

legacy 记录若缺少顶层 `sourceSha256`，只在指纹的 schema、算法、索引格式、page ID、音轨 SHA 和来源窗口均有效且与周记录一致时，使用指纹的 source SHA；两处来源哈希同时存在但不同则拒绝。对于 v3/v4 中作为独立 page 的 Bundle alias，还需提供 `--alias-evidence <已冻结 alias evidence.json>`；工具验证其固定 SHA、Bundle 周次、目标环境及 v3/v4 的实证行，并用 live receipt 分别核对两个 catalog 与 release/content 的来源身份。任一信息缺失或不符都不能生成 tombstone。

撤回第 6 周整周时，必须分别为 family page ID `resi-20261018-15030286` 和 broadcast alias `resi-20261018-broadcast` 生成各自的 tombstone，并分别校验其身份与撤回原因。客户端按精确 page ID 匹配，撤回其中一个不会自动撤回另一个。
