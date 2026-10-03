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

## 后续步骤

1. 在这台 Mac 上允许从 Apple Developer 门户下载本次证书，或由操作人员安全地把证书文件放到本机；不要把私钥或证书备份提交到仓库。
2. 将证书与本轮 CSR 私钥配对并导入钥匙串；确认 `security find-identity -v -p codesigning` 显示有效的 Apple Distribution 身份。
3. 从 `codex/content-category-ui` 的已记录源码重新执行 Distribution 签名归档，核实签名身份与版本 `1.26.9 (50)` 后再上传。
4. 在 App Store Connect 核对 Build 50 的上传处理状态和测试组可用性。其后再分别记录 TestFlight 安装、真机播放和设备验收；它们不能由 Dev 网页、模拟器截图或上传状态替代。

## PR 范围说明

本 PR 只加入本次运行的复盘记录。分类实现仍位于 `codex/content-category-ui`；该分支包含尚未进入 `dev` 的播客准备提交，因此不通过本 PR 一并合入。TestFlight 上传和真机验收也不属于已完成事项。
