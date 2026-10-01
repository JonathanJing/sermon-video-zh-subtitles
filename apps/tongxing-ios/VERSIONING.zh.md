# 同行 App 版本号约定

2026-10-01 用户确认：后续版本统一采用 **`1.26.N`**，用点分隔；最初计划从 **`1.26.1`** 开始；同日用户明确指定将已验收的 Beta 48 晋升为正式 **`1.26.7`**。以这次明确指定为准，下一新候选从 **`1.26.8`** 继续，不补造 1–6 的历史构建。适用于 iOS App 与其扩展，不改变证道内容、目录或四层生产包的版本规则。

## 格式与显示

版本格式为 `产品代数.年份后两位.当年迭代序号`：`1.26.1` 表示第一代 App、2026 年、第 1 次候选。三段使用整数，不补零，不使用横杠或把 `Beta` 写入 Apple 版本字段。

| 场景 | 版本标识 |
| --- | --- |
| 本次正式候选 | `1.26.7` |
| 下一新 Beta 候选 | `1.26.8 Beta` |
| 后续修改后提交新候选（示例） | `1.26.9 Beta` |
| 该候选验收通过，晋升正式（示例） | `1.26.9` |
| 2027 年的新候选 | `1.27.1 Beta` |

Apple 的 `CFBundleShortVersionString` / Xcode `MARKETING_VERSION` 只填写数字版本，如 `1.26.1`；Beta 身份由现有 `TongxingBeta` 配置区分。桌面名称保持「同行-beta」和「同行」。项目沟通和测试说明使用上述版本标识，不把括号内 Build 作为对外版本名。

Apple 仍要求独立的 `CFBundleVersion` / `CURRENT_PROJECT_VERSION`；TestFlight 的系统界面会显示版本与 Build，项目命名约定不改变该显示方式。规则来源：[Apple 版本号](https://developer.apple.com/documentation/bundleresources/information-property-list/cfbundleshortversionstring)、[Apple Build 号](https://developer.apple.com/documentation/bundleresources/information-property-list/cfbundleversion)。

## 递增规则

- 每次提交一个新的分发候选，最后一段 `N` 加 1：`1.26.7` → `1.26.8` → `1.26.9`。本地编译、预览、Run 和测试不递增。
- 原有 Archive 因网络失败重试上传，保留其版本、Build、源码与归档哈希；先查 Apple 是否已接收，不因结果未知而另造版本。改变源码或配置并提交新候选时分配新的迭代号与 Build。
- 当年新候选按已分配记录的最大 `N` 继续递增，不回收已冻结、取消或失败候选的号码。并行分支在归档前核对版本记录与 App Store Connect，避免占用同一号码。
- 年份按新候选版本分配时的项目时区 `America/Los_Angeles` 确定。新年首个新候选使用 `1.27.1`；跨年晋升已验收的 `1.26.N` 时仍保留原版本，不因上传日期改变标识。产品代数只有明确批准的大版本变更时才调整。
- Build 作为技术记录按现有归档流程独立递增；核对所选 App 身份已上传与已冻结的最大 Build 后分配更大的号码，不因跨年或版本变化归零。App 与嵌入扩展的版本和 Build 必须相同。

## Beta 到正式版

Beta 验收通过后，正式版沿用同一数字版本。例如 `1.26.2 Beta` → `1.26.2`；单纯晋升不消耗下一个 `N`。正式版从已验收源码重建，使用正式身份、正式内容源及新 Build，并记录相对 Beta 的配置差异；若功能源码发生变化，则成为新候选，递增 `N` 并重新验证。

每次发行记录至少保留：数字版本、渠道、Build、源码 commit、iOS module tree、内容源、归档哈希、测试结果、Apple 处理与测试组状态。正式记录另外绑定 `validatedBetaCommit`。上传、测试组 Testing、真机验收和正式发布分别记录；详细步骤沿用 [Beta 晋升流程](BETA-PROMOTION.zh.md)。

## 从现有版本切换

已提交的 `1.2.0 (48)` 保留原有身份和 [历史记录](BETA-RELEASE-1.2.0-48.zh.md)，不重命名已上传包，也不改写其源码与归档哈希。用户已确认 Beta 检查没有问题，并指定本次正式候选使用 `1.26.7`。这是旧命名到新命名的首次晋升；后续新候选从 `1.26.8` 继续。构建、上传、审核与发布结果见 [正式发行记录](RELEASE-1.26.7.zh.md)。

版本约定本身没有自动递增脚本。正式 1.26.7 的配置调整单独绑定用户指定与已验收 Beta 源码；之后准备候选时：

1. 查当前发行记录与 Apple 状态，分配版本和 Build，记录对应源码与渠道。
2. 更新所选渠道的 App / 扩展配置；保留其他渠道正在验收的候选，不为了统一数字提前改动其配置。
3. 修改 `project.yml` 后在本目录执行 `xcodegen generate`，核对生成工程与渠道差异，完成受影响的验证后提交源码。
4. 用准确 commit 归档，从实际 App / 扩展 Info.plist 核对版本、Build 与身份，再上传并追加实际结果。
