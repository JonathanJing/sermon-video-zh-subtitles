# Firebase Dev 分类上线与 iOS Beta 分发准备复盘

记录日期：2026-10-03。范围是把内容分类显示在 Firebase Dev 页面与 iOS Beta 界面，并准备提交 Beta 1.26.9 (50) 到 TestFlight。本报告记录本轮实际状态；**TestFlight 上传尚未完成**。

## 结果摘要

| 阶段 | 结果 | 证据与边界 |
| --- | --- | --- |
| Firebase Dev 网页 | 已部署，并在实际页面确认三种标签 | 播客、周日证道视频、YouTube 证道视频分别见下方链接。此结论仅覆盖 Dev 页面 HTTP/UI 读回。 |
| iOS Beta 分类界面 | BetaDebug 构建成功，模拟器安装、启动并显示分类胶囊 | 截图显示 “Sunday sermon video”；内容选择器中可见 YouTube 分类。属于模拟器证据，不代表 TestFlight 或真机验收。 |
| TestFlight 归档 | `1.26.9 (50)` Archive 成功，但使用 Apple Development 签名 | 不满足 App Store Connect 上传所需的 Apple Distribution 签名。 |
| Apple Distribution | Apple Developer 门户已签发证书，ID `9CSB7GHL64`，到期日 `2027-10-03` | Chrome 将 `.cer` 下载标为 “Blocked by your organization”。证书尚未导入；本机有效签名身份仍只有 Apple Development。 |
| App Store Connect | 核验时最新可见版本是 Build 49，状态 `Ready to Submit` | 没有观察到 Build 50 上传或处理记录；不报告为 Beta 已发布或可供测试。 |

Dev 页面读回：

- [播客节目](https://ai-for-god-sermon-audio-dev.web.app/?week=if-i-had-more-time-jesus-is-worthy&contentLang=zh-Hans)
- [周日证道视频](https://ai-for-god-sermon-audio-dev.web.app/?week=2026-09-27-weekend-sermon-drive-530&contentLang=zh-Hans)
- [YouTube 证道视频](https://ai-for-god-sermon-audio-dev.web.app/?week=2026-09-13-live_archive-8JYwTq1xcBE)

## 执行记录

1. 在 iOS 与网页目录中加入内容来源分类映射和显示文案，包括「播客节目」「周日证道视频」「YouTube 证道视频」及相应英文、西班牙文、韩文标签。实现提交为 [`b63cb16`](https://github.com/JonathanJing/sermon-video-zh-subtitles/commit/b63cb1644c086f02fb98403f69561eee725141d3)，分支为 `codex/content-category-ui`。
2. 使用 Xcode 27.1 构建 BetaDebug，并在 iOS 模拟器安装、启动和查看分类界面；模拟器截图保存在被忽略的本地路径 `apps/tongxing-ios/artifacts/tongxing-ios/2026-10-03/category-beta.png`。未运行单元测试。
3. 将网页资源部署到 Firebase Dev。实际读取播客、周日证道视频和 YouTube 证道视频三个页面，均看到预期分类。Dev 部署不代表生产环境发布。
4. `1.26.9 (50)` Archive 成功，但归档使用的是 Apple Development 身份。`security find-identity -v -p codesigning` 只列出 Apple Development，没有 Apple Distribution 身份；App Store Connect 当时也只显示 Build 49。
5. 用户授权创建 Apple Distribution 证书后，Xcode 的证书创建选项显示禁用，于是通过已登录的 Apple Developer 门户注册 CSR。Apple 成功签发证书；随后 Chrome 按组织策略阻止 `.cer` 文件下载。未导入证书，未进行 Distribution 签名，也未上传到 App Store Connect。

## 原因与经验

本轮前半段的内容分类实现、Dev 部署和模拟器验收均完成；发行阶段的前置条件没有在归档前验证。电脑已解锁且 App Store Connect 已登录，并不意味着本机已安装可用的 Apple Distribution 私钥与证书，也不保证浏览器策略允许下载证书文件。该差异到准备分发签名时才暴露。

证书在门户签发成功也不等于本机具备签名能力。必须把下载的证书与生成 CSR 的私钥配对、导入钥匙串，再确认 Apple Distribution 身份确实出现在本机签名身份列表中，才可制作上传候选。当前没有这些证据。

## 日志与时间分析

本节把命令自身运行时间与人工操作、等待及对话历时分开。只有带 `status.json` 的 iOS CLI 阶段有精确开始/结束时间；Firebase 和归档时长来自命令返回记录，其他 UI 操作只保留了事件时间点。因此不能把整段历时当作机器执行时间。

| 阶段 | 时间（太平洋时间） | 可核对时长 | 日志结论 |
| --- | --- | ---: | --- |
| BetaDebug CLI 构建 | 09:24:48.525–09:25:13.360 | 24.835 秒 | `status.json` 退出码 0；`xcodebuild` 成功，产生 `.xcresult`。 |
| 模拟器安装与启动 | 09:25:18.676–09:25:22.710 | 4.034 秒 | `status.json` 中 boot status、安装、启动各命令均退出码 0。 |
| XcodeBuildMCP 首次构建尝试 | 约 09:28:29 | 约 0.004 秒 | 尚未开始编译；配置的 `DEVELOPER_DIR=/Applications/Xcode-beta.app/Contents/Developer` 不存在。 |
| 显式指定 Xcode 的重复 BetaDebug 构建 | 约 09:28:38–09:29:02 | 工具报告 19.4 秒；事件时间跨度约 24 秒 | `Xcode.app` 27.1 构建成功。这次与前面的 CLI 构建重复，原因是第一次结果未作为当前流程的可见证据复用。 |
| Firebase Dev 部署 | 约 09:29:36–09:29:41 | 5.275 秒 | CLI 上传并发布 360 个文件；之后另行从三种分类页面读回确认。 |
| 第一次 Beta Archive | 约 09:30:10–09:30:18 | 约 7.9 秒 | 退出码 65；未传 `DEVELOPMENT_TEAM`，签名阶段即失败。 |
| 带 Team 的 Beta Archive | 约 09:33:24–09:34:02 | 约 38.1 秒 | Archive 成功，但可用身份是 Apple Development，因此仍不是上传候选。 |

按带机器时间戳的 CLI 记录，BetaDebug 构建加模拟器安装/启动共 **28.869 秒**。Firebase 部署命令和成功归档命令合计约 **43.4 秒**；将表中所有可计时的成功与失败命令相加，约 **80.2 秒**。这不包括构建后页面人工核验、证书门户操作、浏览器拦截处理和对话等待；也不能代表完整端到端耗时。

从最初分类需求（09:14:22）到用户提出先写复盘（10:16:02），墙钟历时约 **61 分 40 秒**。其中至少有一个可辨认的用户等待段：证书创建确认发出后至用户回复约 **19 分 57 秒**。其余时间包含实现、页面核验、Apple 门户/钥匙串操作和沟通，现有日志没有为这些阶段记录连续计时，不能进一步精确拆分。

### 主要耗时与流程改进

1. **签名预检放得太晚。** Archive 前没有确认 Distribution 身份和证书私钥已在钥匙串中，导致一次签名失败后又生成了一个仅供开发签名的 Archive。后续 Beta 应在归档前检查 Team、证书身份、profile 与目标版本；条件不齐时先处理签名，避免制作错误用途的 Archive。
2. **Xcode 路径配置失效且触发重复构建。** MCP 指向不存在的 Xcode Beta 路径，失败在 4 ms 内；随后又单独跑了一次构建，虽然成功但与已有 CLI 构建重复。修复默认 `DEVELOPER_DIR` 后，沿用同一份构建状态/产物即可减少重复编译。
3. **机器日志覆盖不均。** CLI 构建和启动有结构化状态与 `.xcresult`，部署有命令输出，但门户证书、人工页面检查、Archive 缺少统一事件记录。因此只能比较各命令片段，无法准确回答每一人工阶段花了多久。下一轮可用一个本地运行清单按阶段记 UTC 起止、commit/build、退出码、产物 ID 和验收结果；不保存证书、私钥或登录信息。
4. **验收与执行应保持分列。** Dev 部署约 5 秒完成，但三页面读回属于后续验收；模拟器启动也不等于 TestFlight 安装。今后继续把部署、HTTP/UI 读回、TestFlight 处理和真机验收分别计时和报告。

## 后续步骤

1. 在这台 Mac 上允许从 Apple Developer 门户下载本次证书，或由操作人员安全地把证书文件放到本机；不要把私钥或证书备份提交到仓库。
2. 将证书与本轮 CSR 私钥配对并导入钥匙串；确认 `security find-identity -v -p codesigning` 显示有效的 Apple Distribution 身份。
3. 从 `codex/content-category-ui` 的已记录源码重新执行 Distribution 签名归档，核实签名身份与版本 `1.26.9 (50)` 后再上传。
4. 在 App Store Connect 核对 Build 50 的上传处理状态和测试组可用性。其后再分别记录 TestFlight 安装、真机播放和设备验收；它们不能由 Dev 网页、模拟器截图或上传状态替代。

## PR 范围说明

本 PR 只加入本次运行的复盘记录。分类实现仍位于 `codex/content-category-ui`；该分支包含尚未进入 `dev` 的播客准备提交，因此不通过本 PR 一并合入。TestFlight 上传和真机验收也不属于已完成事项。
