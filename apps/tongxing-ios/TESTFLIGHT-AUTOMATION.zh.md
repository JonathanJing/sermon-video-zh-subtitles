# TestFlight Beta 自动分发

保留 `archive-channel.sh` 的冻结源码、渠道身份和归档哈希；fastlane 只负责 Apple 查询、已导出 IPA 上传、等待处理和现有内部组分发。当前仅支持独立 Beta `com.jonathanjing.tongxing.beta`，不提交 App Store 审核，不新建测试组或测试者。

## 本机配置

2026-10-04 本机已安装 Homebrew fastlane `2.240.1`。新机器执行 `brew install fastlane`；不使用 macOS 系统 Ruby 安装 gem，不修改全局 `xcode-select`。运行时记录实际 fastlane 版本。上传通过进程级 `DEVELOPER_DIR` 使用完整 Xcode，默认 `/Applications/Xcode.app`；可用 `--developer-dir` 覆盖，避免 Command Line Tools 被误当成 Xcode。升级后先核对下列定向检查与只读 API 查询。

在 App Store Connect → Users and Access → Integrations 创建 API Key，供 TestFlight 构建信息与分发使用的角色为 App Manager；仅上传的 Developer 角色不满足完整分发权限。使用 Team Key 时需要 `.p8`、Key ID 和 Issuer ID。密钥创建与权限授予由账户持有人处理；不要把私钥内容粘贴到聊天或提交 Git。依据：[fastlane 认证](https://docs.fastlane.tools/getting-started/ios/authentication/)、[TestFlight 权限](https://docs.fastlane.tools/actions/upload_to_testflight/)、[Apple API Key](https://developer.apple.com/help/app-store-connect/get-started/app-store-connect-api/)。

`.p8` 放在仓库外的私有目录，文件权限设为 `600`。以下变量均从本机已创建的 Key 取得，不把示例当成真实标识：

```sh
chmod 600 "$TONGXING_ASC_KEY_FILE"
python3 apps/tongxing-ios/scripts/testflight.py configure \
  --key-file "$TONGXING_ASC_KEY_FILE" \
  --key-id "$TONGXING_ASC_KEY_ID" \
  --issuer-id "$TONGXING_ASC_ISSUER_ID"
python3 apps/tongxing-ios/scripts/testflight.py status
```

默认私有配置为 `~/Library/Application Support/TongxingRelease/api-key.json`，只记录标识与 `.p8` 文件路径，不复制私钥内容。文件为 `600`，新建目录为 `700`。已有配置不会覆盖；其他账户显式选择 `--config`。脚本拒绝任何 Git worktree 内的凭据路径及宽松文件权限。不同 worktree 使用同一配置时共享操作锁。

`status` 只读查询已上传构建和内部组关联，证据保存在忽略目录 `artifacts/tongxing-ios/testflight/<运行ID>/apple-state.json`，不输出测试者邮箱。用其营销版本与 Build 清单核对已占用号码；仍须结合其他分支已冻结的候选遵循 [版本约定](VERSIONING.zh.md)。没有 API Key 时，可执行 `status --dry-run`，仅验证命令结构，不能视为认证成功。

## 同一候选的上传与分发

1. 核对 Apple 与仓库发行记录，分配新候选版本／Build，提交已验证源码。按 [归档流程](BETA-PROMOTION.zh.md#冻结源码并归档) 生成 `release-record.json`。
2. 用该记录的同一个 Archive 导出 IPA。`xcodebuild -exportArchive` 的私有 ExportOptions 使用 `method=app-store-connect`、`destination=export`、`signingStyle=automatic`、`manageAppVersionAndBuildNumber=false`；显式指定完整 Xcode `DEVELOPER_DIR`，保持版本不由导出工具改写。API Key 不代替代码签名证书与 provisioning profile。
3. 以下 `TONGXING_BETA_RECORD`、`TONGXING_BETA_IPA`、`TONGXING_BETA_NOTES` 指向本轮实际产物：

```sh
python3 apps/tongxing-ios/scripts/testflight.py upload \
  --record "$TONGXING_BETA_RECORD" --ipa "$TONGXING_BETA_IPA" --dry-run
python3 apps/tongxing-ios/scripts/testflight.py upload \
  --record "$TONGXING_BETA_RECORD" --ipa "$TONGXING_BETA_IPA"
python3 apps/tongxing-ios/scripts/testflight.py wait --record "$TONGXING_BETA_RECORD"
python3 apps/tongxing-ios/scripts/testflight.py distribute \
  --record "$TONGXING_BETA_RECORD" --notes "$TONGXING_BETA_NOTES" --group Rooted
```

上传前重新计算归档清单哈希，并核对 IPA App／扩展的身份、版本、Build 和 App 内容源。IPA 必须由指定 Archive 导出；上述字段校验不独立证明 IPA 每个文件的源码来源。每次操作保存实际 IPA SHA-256、命令退出状态与 Apple 清单；不把执行成功直接写为真机或现场验收通过。

`upload` 先准确查询营销版本与 Build；Apple 已有同号构建时跳过二进制上传。私有配置旁的 `upload-intents/` 在上传前记录候选、IPA SHA 与尝试阶段；已有尝试时再次 `upload` 默认拒绝，避免未知窗口重复上传。上传结果未知时，先执行 `status` 并对照该记录，不换版本或立即重传；首次上传后 API 暂时不可见也不代表上传失败。只有人工明确确认 Apple 未接收、同一包应重试后才使用 `upload --retry-upload`；该选项不能由超时自动启用，每轮尝试证据保留在各自运行目录。`wait` 每 30 秒查询一次，最多 15 分钟，超时保存当时 Apple 状态，可继续同一记录等待，不重复上传。

`distribute` 仅接受 Apple `VALID`、未过期且内部状态为 `READY_FOR_BETA_TESTING` 或 `IN_BETA_TESTING` 的准确构建。它要求唯一匹配的现有内部组，保存并读回 What to Test，再关联构建、读回组内 build ID。不会触发外部 Beta Review。分发关联成功、Apple 内部状态、真机安装与功能验收分别记录；私有日志不进入 Git。原归档记录保持不变，将本轮 `apple-state.json` 和 `command-result.json` 作为追加证据引用到发行记录。

## 本轮配置验证

2026-10-04：fastlane 2.240.1 已安装；9 项离线发行守卫测试通过，覆盖归档被改写、生产渠道误用、IPA 扩展身份／版本不匹配、私钥权限、配置不覆盖，以及未知上传的重复阻止。账户持有人已提供本机 Key；2026-10-04 实际 API 认证与 Beta 构建／Rooted 内部组查询成功。私钥未进入 Git。

Python／Ruby 语法、CLI `--help`、`status --dry-run`、fastlane lanes 加载及离线发行守卫测试通过后，才提交配置。新机器尚未提供 API Key 时，真实认证、最新 Build 查询、IPA 上传和 Rooted 分发均为 `not_run`；不能据此声称 Beta 已可用。本机真实归档、签名、上传及分发结果按该候选的独立发行记录保存。App Manager API Key 的 TestFlight 权限与云托管分发签名权限不同；本轮 API Key 导出遇到云签名权限错误，既有 Xcode 账户完成同一个 Archive 的导出，IPA 上传仍使用 API Key。
