# 同行 Beta 与正式版晋升记录

Beta 与正式版共用同一套 App、播放器和实时活动源码，由构建配置区分身份和内容环境。桌面名称不同还不足以实现共存；两版的 App、扩展和返回链接身份均独立，下载与播放历史保存在各自沙盒中，不自动迁移。

后续数字版本按 [版本号约定](VERSIONING.zh.md) 使用 `1.26.N`，本次正式候选由用户指定为 `1.26.7`，下一新候选从 `1.26.8` 开始。Beta 到正式版保留已验收的数字版本，正式重建分配新 Build；功能变更需要新的 `N`。下面的 `1.2.0` 为现有历史候选，不因采用新规则而重命名或重建。

| 项目 | 独立 Beta | 正式版 |
| --- | --- | --- |
| 桌面名称 | 同行-beta | 同行 |
| App Bundle ID | `com.jonathanjing.tongxing.beta` | `com.jonathanjing.tongxing.dev`（已注册的历史正式身份，保留） |
| 实时活动扩展 | `com.jonathanjing.tongxing.beta.listening-activity` | `com.jonathanjing.tongxing.dev.listening-activity` |
| App / 实时活动返回链接 | `tongxing-beta` | `tongxing` |
| Scheme | `TongxingBeta` | `Tongxing` |
| 开发 / Archive 配置 | `BetaDebug` / `BetaRelease` | `Debug` / `Release` |
| 默认内容源 | Firebase Dev | Debug 为 Dev；Release 为正式站 |
| 当前候选版本 | `1.2.0 (48)` | `1.26.7 (50)`（Waiting for Review） |

## 当前分发状态（2026-10-01）

最新 dev 基线 `7e534bb` 的独立 Beta **1.2.0 (48)** 已在 2026-10-01 21:42:51 UTC 上传成功；归档源码为 `fac0c9c4769ad25a86d97ae4fa82dfb1a5c49bd7`，Apple 处理已完成，Rooted 内部测试组的 build 48 显示 `Testing`，测试说明已保存。模拟器 4 项 Beta 身份与交互检查通过，另有目录合成测试通过。随后用户确认 Beta 检查没有问题，并指定正式 `1.26.7`；Build 49 已上传并完成 Apple 处理，但因 beta Xcode / SDK 被拒绝加入正式审核。Build 50 已使用正式 Xcode 27 (`27A266a`) 重建，2026-10-01 22:34:58 UTC 上传成功，GM SDK 最终 5 项 UI 检查通过，24 张真实截图已上传；22:48 UTC 提交正式审核并显示 `Waiting for Review`，审核通过后自动发布。正式内容检查、截图和提交状态见 [正式 1.26.7 记录](RELEASE-1.26.7.zh.md)；Beta 原始证据见 [Beta 48 记录](BETA-RELEASE-1.2.0-48.zh.md)。用户确认与 Agent 模拟器、正式包真机及现场证据分别记录。

以下 Beta 47 与原 App 46 是既有分发记录，不作为 Beta 48 的验收证据：

原 App 的 `1.2.0 (46)` 已上传 TestFlight，Rooted 内部测试组显示 `Testing`；该构建仍使用正式 App 身份，会替换同身份的已安装正式版。独立 Beta `1.2.0 (47)` 已创建独立 App Store Connect App `6818272039`，并于 2026-10-01 18:32:21 UTC 上传成功。Apple 处理已完成，独立 Beta 的 Rooted 内部测试组显示 `Testing`（1 个测试账户、1 个构建），测试说明已保存。新 Beta 的实机安装与验收尚未完成。完整源码、归档哈希、实际测试及分发证据见 [Beta 1.2.0 (47) 候选记录](BETA-RELEASE-1.2.0-47.zh.md)。

TestFlight 上传、Apple 处理、测试组可用、实机验收和 App Store 发布分别记录。现有 Duo 外屏与大字号测试可作为历史证据，但不能替代新 Bundle ID 的双 App 共存、实时活动返回目标和真机验收；Duo 展开内屏、半折与现场验收仍未完成。正式 1.26.7 的用户发布授权与实际状态见其发行记录，不能推断未测设备状态。

Beta 48 已包含的麦克风失败反馈修复见 [修复记录](ALIGNMENT-FEEDBACK.zh.md)。该记录与已分发 Beta 47 分开，未改变旧包的源码或归档哈希；本次 48 的新归档与实际测试另行记录。

API Key 与 fastlane 的只读查询、上传及现有内部组分发见 [TestFlight 自动分发](TESTFLIGHT-AUTOMATION.zh.md)。它复用下述归档，不改变源码冻结或版本规则。

## 冻结源码并归档

先提交已验证的 iOS 候选，记录完整 commit，再运行 [archive-channel.sh](scripts/archive-channel.sh)。脚本拒绝 tracked iOS 文件的未提交差异，要求 `--expected-commit` 完全匹配 HEAD；仓库其他模块的未提交变化不会无故阻塞归档。输出必须在 Git 忽略目录，并且使用新目录保留旧证据。私有签名配置、帐号、Team、设备唯一标识、Archive 和上传日志都不提交 Git。

从仓库根目录执行；以下 `TONGXING_CANDIDATE_COMMIT` 是当前冻结候选，不能用旧测试记录冒充它的验收：

```sh
TONGXING_CANDIDATE_COMMIT="$(git rev-parse HEAD)"
apps/tongxing-ios/scripts/archive-channel.sh \
  --channel beta \
  --expected-commit "$TONGXING_CANDIDATE_COMMIT" \
  --developer-dir /Applications/Xcode.app \
  --output-dir artifacts/tongxing-ios/beta-1.2.0-48 \
  --dry-run
```

确认命令后去掉 `--dry-run` 即归档；此工具不上传。工具链按显式 `--developer-dir`、已有 `DEVELOPER_DIR`、已安装的 Xcode beta、正式 Xcode 选择，不修改全局 `xcode-select`。如果 Beta 用正式内容验证发布候选，显式增加 `--content-origin production`，并记录实际内容源；BetaRelease 默认仍为 Dev。合法内容源固定为项目的 Dev 与正式 Firebase 域名，正式渠道不接受 Dev 内容源。

Archive 成功后，脚本从实际 App 与扩展的 Info.plist 核对身份、显示名、版本、返回链接及内容源，写入输出目录的 `release-record.json`。记录包含完整源码 commit、Git tree / iOS module tree、渠道、scheme、configuration、版本 / build、App / 扩展 Bundle ID、URL scheme、实际内容源、Xcode / SDK 和 Archive 路径；状态仅为 `archive_succeeded`，`upload`、`device`、`venue` 初始均为 `not_run`。归档期间 HEAD 或 tracked iOS 文件变化时，不生成成功记录。

上传后在同一记录的 `upload` 中补充实际版本、处理结果、测试组状态、检查时间和证据路径；不能只写“已上传”就视为测试者可用。真机和现场验证分别补充 `device`、`venue` 的实际结果及证据，不覆盖原 Archive 身份。示例状态可为 `uploaded_processing`、`internal_testing`、`passed`、`failed`、`not_run`，只使用本轮已观测到的状态。

## 从 Beta 晋升到正式版

1. 在 Beta 记录中冻结已验收的完整源码 commit、iOS module tree、版本、内容源及实际测试范围。需要正式内容验收时，先对同一 commit 构建 `BetaRelease --content-origin production`；Dev 候选内容通过不代表正式内容或现场验收通过。
2. 正式候选从该 commit 建立，使用 `Tongxing / Release` 重建，保留正式 App 和扩展的已注册身份、正式返回链接及正式内容源。**不修改或重新签名 Beta IPA 来当正式 IPA。** 对两个配置的构建设置差异逐项核对：仅渠道身份、显示名、返回链接、内容源、批准的版本 / build 和签名应不同，功能源码保持一致。
3. 正式构建必须先核对 App Store Connect 当前版本 / build，并递增需要发布的构建号（本文保留的正式 `1.2.0 (46)` 已上传，不可作为新上传复用）。版本 / build 或配置的调整单独提交，记录 `validatedBetaCommit`、`productionCommit`、`configurationDiff` 和原因；核对差异没有引入未验收功能。脚本不会自动改版本、自行推断 Beta 已验收或完成晋升。正式归档继续要求准确的 `--expected-commit`，生成新的记录，不覆盖 Beta 记录。
4. 使用正式渠道归档，并复核实际 App / 扩展身份、生产内容源、签名与关键交互。将正式 Archive、上传、真机验收、App Store 审核和用户批准的发布动作分别绑定到该候选记录；发现功能差异后返回候选验证，不能夹带未验收差异直接合并或发布。

正式归档命令使用新的输出目录与已冻结的正式 commit：

```sh
apps/tongxing-ios/scripts/archive-channel.sh \
  --channel production \
  --expected-commit "$TONGXING_PRODUCTION_COMMIT" \
  --developer-dir /Applications/Xcode.app \
  --output-dir artifacts/tongxing-ios/production-candidate \
  --dry-run
```

双版本实机至少检查：两版可同时安装且名称可区分；Beta 删除或更新不删除正式版下载与进度；各自实时活动回到对应 App；普通启动读取记录中的内容源；切换界面或内容语言不清零当前位置。其余音频与现场步骤沿用 [Beta 真机验收](BETA-TESTING.zh.md) 和 [发布清单](RELEASE-READINESS.zh.md)，只重验受本轮变化影响的部分。
