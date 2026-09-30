# Web／原生共用 Release 合同夹具

本批补 `DEV-CICD-002`／E6 的部分跨端合同证据。唯一夹具为 [shared-release-contracts.json](../apps/tongxing-ios/Core/Tests/TongxingCoreTests/Fixtures/shared-release-contracts.json)，Web 测试直接读取它，Swift Core 以测试资源加载同一文件，不能各自维护两份看似相同的数据。

## 范围与修复

30 个确定性场景覆盖三语合法 production Release v2、缺短口播候选绑定、坏音频包 hash、缺 Page／Audio、重复 Audio、跨语言字幕路径、坏资产 hash、缺／错验收证据、未审内容、未发布 candidate，以及缺失／空／非字符串 package ID。新增 pageId 长度 140／141／160 的三语 producer 边界、合法长 packageId 和 opaque ID。

Web production loader 现在使用可独立验证的 `validatePublishedRelease`，要求现有 v2 合同的完整绑定与页面资产；验收状态与 evidence hash 必须匹配。原生 Core 同样校验 HTTP／设备／现场 receipt：`not_run` 必须没有 evidence，`pass/fail` 必须有有效 SHA；Dev candidate 不能自称已做设备或现场验收。这些是已有字段的入站验证，不会生成或提升审核收据。

Web 集成负例会重新计算 Release 的有效传输 hash，再移除其合同证据，确认即使文件传输完整也会拒绝该 locale；其他两个 locale 仍可用，坏 locale 的正文不会继续请求。现有读取全文／口播字幕分离、字节 hash 校验和历史页超时测试保留。

## 验证边界

- 共用夹具只覆盖 production Release v2 的已审核音频路径；不是全部 catalog／Release 状态空间等价证明。
- 原有 catalog v2／Release v1、Dev candidate 和 text-only 回退分别由既有 Web／Swift 回归保留；下方后续批次补 catalog target/text-only 准入 fixture；完整 catalog 和 text-only Release 仍待覆盖。
- `synthetic_decoder_tests_not_production_approval` 明确说明 fixture 中的人审／HTTP 状态只用于合成负例。没有真实内容批准、下载、HTTP 发布或现场证据。
- 本地 Swift Core 与 Infrastructure 在 macOS 上运行。环境条件启用的真实站点／录音 smoke 保持 skipped；这不是 iPhone、模拟器 UI 或 App Store 验收。
- 客户端代码发生变化，E6 必须保持 compatibility review required，不能签发 backend-only unchanged。此 draft 的 `native-client` 仍只是路由汇总；被跳过的 iOS／contract-validation 不计入执行通过。

命令：

```sh
node --test experiments/sermon-dubbing-poc/web/*.test.mjs
node --test tests/test_formal_dev_adapter.mjs
DEVELOPER_DIR=/Applications/Xcode.app/Contents/Developer swift test --package-path apps/tongxing-ios/Core --scratch-path /tmp/tongxing-contract-core
DEVELOPER_DIR=/Applications/Xcode.app/Contents/Developer swift test --package-path apps/tongxing-ios --scratch-path /tmp/tongxing-contract-storage
```

`DEV-CICD-002` 与 E6 继续为 in_progress，未完成未知路径全矩阵、全部跨端协议 fixture、人工兼容性签署或设备验收。

## packageId 长度回归

Release v1/v2 schema 对 `packageId` 规定非空字符串，没有 160 字符上限；它不参与资产路径或缓存文件名。正式 producer 允许最长 160 字符的 pageId，再追加 `-<locale>-dual-script`，中文最长 packageId 为 180 字符。Web 和 Swift 因此只对 packageId 使用 schema 的非空字符串要求，不复用 pageId 的限制，也不收紧 schema 拒绝既有有效包。pageId、同语言资产路径、hash 和状态验证保持原有合同。

新增 fixture 在旧 Web head 有 6 项失败，修复后完整 Web 224 项、legacy adapter 9 项、相关 Python 11 项通过。Swift Core 64 项报告中 6 项条件 smoke 跳过，实际执行 58 项通过；共用 30-case 夹具包含在其中。这是 decoder/本地行为证据，不是长 ID 的真实设备播放或任何内容批准。

## Catalog target 与 text-only 共用夹具

后续批次增加唯一 [shared-catalog-targets.json](../apps/tongxing-ios/Core/Tests/TongxingCoreTests/Fixtures/shared-catalog-targets.json)，Web 真实 loader 的 `validatePublishedTarget`、Swift `PageTarget.validate` 与 producer catalog v3 schema 测试读取同一份 31-case 数据。覆盖三语、140/141/160 字符 pageId、准确的 release path/hash、审核状态、唯一且已知的 capability、audio 可用性一致性、text-only 及基础 alignment binding。Web 在 release fetch 前拒绝错页／错语言／legacy／带 query 的路径和自相矛盾的声明，只排除受影响 locale。集成反例即使错误路径提供正确 release bytes/hash，也必须拒绝。

目录准入与播放能力分别验证：text-only 及只有 text+audio、没有 captions 的目标仍是合法目录项；当前 Web audio bridge 不请求这些目标的 release、不捏造音轨，选择实际可播放的语言。原生可展示 text-only 页面。共用 fixture 的 `webPlayback` 记录这种产品能力差异，不宣称 Web 已实现 text-only 阅读体验。

这批不是整个 catalog/header/page 或完整 Release text-only 状态空间的等价证明。原生 fingerprint 额外执行现有 7 秒至 4 小时资源限制；Web 不将该限制新加到目录准入，既有 sidecar 与实际索引/音轨验证仍负责对齐能力。长窗口及其他未覆盖边界继续需要兼容性评估，不能凭这 31 个样本关闭 E6。所有 fixture 人审字段仍仅为合成测试，没有改变真实批准或发布状态。

## Catalog header／page 准入补充

[shared-catalog-pages.json](../apps/tongxing-ios/Core/Tests/TongxingCoreTests/Fixtures/shared-catalog-pages.json) 新增 33 个共用场景，由 Web 真实 loader 的 header/page 准入、Swift `MultilingualCatalog.decode` 和 producer schema 验证读取。覆盖 104 页上限／重复 ID／默认页、真实日历日期、标题边界、source/media hash、默认 locale 与 16 个 target 上限；保留 schema 合法的 `_`／`-` 开头和 160 字符 pageId。所有接受样本也经过启用 format checker 的 catalog v3 schema 验证。

Web 现在在任何 Release／sidecar 请求前检查 header 与页面元数据。坏 header（例如重复 ID）拒绝该可选目录；坏页面只排除该页，其他页面保留。既有坏 locale 隔离保持。六个集成反例在旧 loader 上失败；另有有效历史页保留回归。测试夹具补齐真实 schema 本来要求的 title/generatedAt，不以缺字段的旧测试数据定义生产合同。

仍不宣称完整状态空间等价：generatedAt 的语法仅由 producer schema 检查；native/Web 对额外 JSON 字段、Unicode title 计数、坏页整体/局部恢复及非音频 locale 的产品展示策略尚有差异，videoDelivery 和完整 text-only Release 仍不在该矩阵。这里验证字段准入，不赋予真实 HTTP、人审、设备或现场验收。
