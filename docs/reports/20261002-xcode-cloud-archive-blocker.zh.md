# Xcode Cloud 自动 Archive 阻塞与源码准入门禁

记录日期：2026-10-02 UTC。范围仅为 Xcode Cloud Archive 的源码准入。本 PR 的 **actual_upload=not_run**，没有新分发候选；此前外部自动尝试确实发生，并在 ASC 准备阶段失败，下一次上传当前仍被阻断。

## 已核实的边界

- [PR #209](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/209) 的冻结候选为 `b3bcf566406db3f9a5638e191a297f6e2ca9eced`。外部 squash 合并后的 [main `b9f9e1e`](https://github.com/JonathanJing/sermon-video-zh-subtitles/commit/b9f9e1efb49b1c3d161a196fe534372cdcd2a6a8) 与该候选的完整 Git tree 均为 `e72b34852758fd050aa021333c87ab0d2b69500f`；提交 SHA 不同，文件树一致。
- Required GitHub CI 通过不代表 Apple 接收。外部已配置的 Xcode Cloud Default workflow 自动执行了 Build / Archive：Build 成功，[Archive 检查](https://github.com/JonathanJing/sermon-video-zh-subtitles/runs/110733134280) 在 App Store Connect 准备阶段失败。
- 本次自动尝试的身份为 `1.2.0 (44)`。已核实的 Apple 拒绝结果包括 `ITMS-90186`（该版本 train 已关闭）、`ITMS-90062`（`1.2.0` 低于已批准的 `1.26.7`）及 `ITMS-90478`。这里仅保留排障结论，不公开账号标识、通知原文或私有链接；这些是本次时点证据，不是下一候选的实时许可。
- [PR #208](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/208) 的正式 `1.26.7 / source Build 50` 已在 dev；#209 的冻结树刻意不含它。不能通过“再把当前 dev 合到 main”来冒充同一已验证候选，也不能仅增加 `CURRENT_PROJECT_VERSION` 修复 Cloud 的分发计数器。

## 本次改动

加入 [`ci_pre_xcodebuild.sh`](../../apps/tongxing-ios/ci_scripts/ci_pre_xcodebuild.sh) 和同目录的离线 Python 标准库校验器。Apple 会自动发现与 `.xcodeproj` 同级 `ci_scripts` 中的预构建脚本，无需修改工作流配置。本 PR **不**设置 workflow 环境变量，不生成真实 intent，不改版本、Apple counter、签名、账号、分支保护，也不重试 Archive 或上传。

- `build`、`analyze`、`build-for-testing`、`test-without-building` 立即原样放行，连 Python、资源或 intent 都不读取。
- `archive` 缺少合格 intent 就以非零退出，并给出固定、可操作的错误；未知或缺失 action 同样 fail closed。
- 不调用、不包裹 `xcodebuild`，不添加 post hook，不吞掉其真实退出状态。guard 通过后仍由 Xcode Cloud 执行原命令。
- helper 与资源都从 `ci_scripts` 取用。源码工程、两个 scheme、App / 扩展 Info.plist 使用该目录内的 Git symlink。按 Apple 的资源规则，Cloud 会把链接目标提供给后续阶段；脚本不依赖 `.git` 或 `CI_PRIMARY_REPOSITORY_PATH` 在该阶段可读，也不依赖 post-clone 生成文件跨阶段保留。

## Intent v1 契约

操作人员在完成候选选择与准入核对后，才可供应非秘密的 `TONGXING_ARCHIVE_INTENT_JSON`。它是**外部提供的操作记录**，不是布尔开关，也不是签名批准或 Apple 许可。此 PR 没有供应任何真实记录。

| 字段 | 严格要求 |
| --- | --- |
| `schemaVersion` | 整数 `1`，不接受布尔值；禁止缺失、重复及未知字段 |
| `sourceCommit` | 完整小写 40 位 Git SHA，必须与 Cloud 的 `CI_COMMIT` 完全相同 |
| `channel`、`scheme`、`configuration` | 仅允许 `production / Tongxing / Release` 或 `beta / TongxingBeta / BetaRelease` |
| `version` | 无前导零的三段数字版本；App 与扩展所选配置的 `MARKETING_VERSION` 必须都相同 |
| `sourceBuild` | 正整数的字符串；App 与扩展所选配置的 `CURRENT_PROJECT_VERSION` 必须都相同 |
| `cloudBuild` | 单独选定的正整数字符串，必须等于 `CI_BUILD_NUMBER`；它不由 `sourceBuild` 推导，两者不必相等 |
| `issuedAt`、`expiresAt` | UTC 秒级 `YYYY-MM-DDTHH:MM:SSZ`；开始时间不得在未来，当前时间必须早于到期时间，窗口最长 24 小时 |
| `resourcesSHA256` | 恰好包含 `project.pbxproj`、`Tongxing.xcscheme`、`TongxingBeta.xcscheme`、`App-Info.plist`、`Extension-Info.plist` 的实际字节 SHA-256，不能是 symlink 路径字符串的哈希 |

同时严格检查 `CI_XCODE_CLOUD=TRUE`、`CI_XCODEBUILD_ACTION=archive`、`CI_XCODE_SCHEME`、`CI_BUNDLE_ID`、`CI_PRODUCT_PLATFORM=iOS` 与明确的 start condition。还对 Cloud 的 `CI_PROJECT_FILE_PATH`、`CI_PRIMARY_REPOSITORY_PATH` 做不访问文件系统的 POSIX 词法规范化，要求项目路径精确等于 `<primary>/apps/tongxing-ios/Tongxing.xcodeproj`；缺失、相对路径、外部路径、其他项目/workspace 或 `..` 遍历全部拒绝。不猜测 `CI_XCODE_PROJECT` 的未明确格式。PR 的测试树可能是合成 merge，不能仅凭其源 commit 声称树已冻结，因此拒绝 PR start condition / PR number。缺失或不匹配的 Cloud 身份不能回退到本地猜测。

采用外部记录，避免“一个 commit 在其中包含自己的 SHA”这一循环依赖。新的 SHA（包括同树 squash）、新 Cloud Build 或过期窗口必须重新核对、供应相应记录，旧值不能自动跟随分支。

校验器解析工程中当前受支持的 OpenStep 结构，要求两个目标具有直接、字面的版本、Build、bundle ID、Info.plist 路径设置；拒绝条件式身份覆盖、scheme action、自定义/歧义结构及缺少资源。还检查 scheme 实际 Archive 配置与 App 目标、Info.plist 的版本/Build 绑定。将来需要更复杂设置时先扩展并测试契约，不能宽松猜测。它不解析任意 Xcode 配置层或证明最终二进制身份。

## 验证与局限

离线命令（仓库根目录）：

```sh
python3 -m unittest discover -s tests -p test_xcode_cloud_archive_admission.py -v
python3 -m unittest discover -s tests -p test_ios_ci_route.py
python3 -m unittest tests.test_ci_change_scope
sh -n apps/tongxing-ios/ci_scripts/ci_pre_xcodebuild.sh
python3 -m py_compile apps/tongxing-ios/ci_scripts/validate_archive_intent.py tests/test_xcode_cloud_archive_admission.py
git diff --check
```

本轮 16 项新测试、8 项既有 iOS route、7 项 CI scope 测试通过；语法和 diff 检查通过。已基于合入 #212 的 dev `7e83fe23dfac3062b1e84eae7fe9406e9b5d5f30` 把新测试加入 `native_contracts` 精简套件，避免未来仅修改原生路径时漏掉它。独立源码审核发现的 Cloud 项目路径绑定缺口已修复并复验。覆盖两渠道真实已提交工程、只有 `ci_scripts` 的隔离环境、全部必需 Cloud 身份缺失/错误、短 SHA/源码漂移、时间窗口、版本/Build/渠道/扩展不符、资源缺失/漂移、重复/未知 JSON 字段、恶意输入不入日志、非 Archive 完全旁路，以及失败退出码保留。测试中的 SHA 和 Cloud Build 是临时合成值，不是可供发布的 intent。

尚未执行真实 Xcode Cloud、macOS/Xcode 构建、Archive、签名或上传；离线资源复制测试不能替代 Cloud 实际 symlink materialization 验证。Python 或资源不可用时 Archive 仍阻断，其他已知 action 不受影响。此处没有重新执行不受影响的 App/Core/播放器测试。

本门禁信任 Xcode Cloud 提供的 `CI_COMMIT` 与资源来源，绑定的是静态源码候选；不是针对可修改 workflow 的攻击者的安全边界。没有在线 ASC 查询、签名审批、一次性 token 消耗或上传校验。24 小时窗口也不是 ASC 状态新鲜度的保证。人工批准、Apple train/version/build 准入、实际归档结果、上传接收、真机验收与发布必须各自保留真实证据，不能从 guard 成功推导。

## 有界后续与停止条件

1. 本 PR 先经独立源码审核并保留合并审查点。合入 dev 不等于 main 或既有冻结分支已经有门禁；只有包含脚本的源码 revision 会受其约束。将门禁带入 main / 正式候选是后续独立决策，不能把当前 dev 全量当成 release。
2. 下一候选由用户确认版本、渠道、冻结源码及验收范围；遵守 [版本号约定](../../apps/tongxing-ios/VERSIONING.zh.md)，不重用已分配号码、不自动 bump。
3. 获准后，在真实 ASC 查看所选 App 的 train、已批准版本、已用 Build 及 Cloud next Build；选择有效版本和 Cloud counter，并记录时点。任何更改 Apple 设置或实际上传仍需要相应授权；源码 guard 不代做。
4. 供应与确切冻结 SHA 和下一 Cloud Build 匹配的短期 intent 后，再进行获准的 Cloud archive。核实 hook 的自动发现与资源可见性，并从实际 App / 扩展归档产物再次检查身份。若资源或身份不符，保留失败证据，先修复而非放宽检查。
5. 上传前重新检查实时 ASC 准入和授权；完成后记录 Apple 的实际接收结果。此报告不触发这一步，也不把等待中的上传视为完成。

当前停止于源码门禁验证与 PR 审查。本 PR 的 **actual_upload=not_run**；下一次实际上传仍为 blocked，不会因 CI 绿灯自动进入 Apple 发布。

## 官方依据（2026-10-02 核对）

- [Apple：Writing custom build scripts](https://developer.apple.com/documentation/xcode/writing-custom-build-scripts)：命名、自动发现、可执行脚本、临时环境与 `ci_scripts` 资源/symlink 规则。
- [Apple：Environment variable reference](https://developer.apple.com/documentation/xcode/environment-variable-reference)：action 枚举、`CI_COMMIT`、PR 合成 merge 语义及 `CI_BUILD_NUMBER`。
- [Apple：Setting the next build number for Xcode Cloud builds](https://developer.apple.com/documentation/xcode/setting-the-next-build-number-for-xcode-cloud-builds)：Cloud 自动递增整数，分发采用 Cloud Build；不是只改工程 Build 即可。Apple 对 iOS 允许新版本重新计数的最低要求，与本仓库要求跨版本递增的更严格运营约定分别处理。
