# 复盘：20261021-ios-alignment-beta60

数据见同目录 `INDEX.md`、`beta60-report-input/summary.json` 和两份 receipt；本报告仅记录客户端验证与 Beta 分发。

## 结论先行

交付类型为 iOS 测试与内部 Beta 构建。冻结源码 `8282d3cb915b6ed4261e3d2dcf03fceeab7dc72f` 的 `1.26.19 (60)` 已归档、上传，Apple 读回 `VALID / IN_BETA_TESTING`，Rooted 内部组包含准确 Build；`outcome.json` 状态为 `internal_testing`。这不构成四层内容、真机麦克风或现场对齐验收。

## 总时间

`outcome.json` 记录从模拟器测试开始到 Apple 分发读回约 13 分 24 秒。没有 journal，计算与等待未精确拆分；Apple 上传后至有效 Build 读回约 8 分钟。没有重传或更换 Build。

## 各层模型、耗时与速度

本轮未执行 L1–L3 生产或模型调用，相关 token、费用与速度均为 `not_run`。L4 客户端验证使用 Xcode 27.1／iOS SDK 27.1：模拟器对齐控制器 41 项通过、2 项跳过、0 失败；Swift Core 指纹定向检查 9 项通过、2 项跳过、0 失败。BetaRelease 签名 Archive、同一 Archive 的 IPA 导出与 TestFlight 分发通过。证据见 `test-receipt.json`、`distribution-receipt.json` 和原本机 `.xcresult`；报告不复制二进制。

## 错误

测试与 Archive 无失败。模拟器 2 项跳过分别需要冻结 Dev 素材和普通 Debug 身份；Core 2 项跳过需要显式冻结线上参考。报告导出最初尝试的工作树没有 `.venv/bin/python`，改用系统 `python3` 后导出并验证成功。跳过项未计入通过数。

## 可以改进的地方

Firebase Dev 对齐核心文件与源码一致，但 `multilingual-v5.json` 返回 404，且线上 `published-weeks.mjs`、`app.mjs` 落后。应准备保留现有内容的 Dev App 外壳候选，完成快照门禁、HTTP 哈希与真实页面读回后再测试 v5 混源对齐；当前 Beta 只能使用已有带指纹周次核验基本定位。见发行记录 `apps/tongxing-ios/BETA-RELEASE-1.26.19.zh.md`，此项未在本轮部署。

## 实际覆盖范围

L1–L3：`not_run`，复用 dev 已有代码及 Dev 内容。L4：核对 iOS 和 Firebase 主入口对齐代码、运行 Core／模拟器定向测试、签名归档、IPA 上传、Apple 处理与 Rooted 内部分发。真实麦克风、现场声学精度、真机安装和正式渠道均为 `not_run`。

## 遗留状态

本地 Archive、IPA、`.xcresult`、HTTP 核查与 Apple 收据仅在忽略目录。Build 60 已使用并分发；没有待重试的未知上传。Firebase Dev v5 页面缺口待单独候选处理。

## 外部可见的变化

独立 Beta App 的 TestFlight `1.26.19 (60)` 已处于 Rooted 内部测试，准确 Apple Build ID 与状态见 `distribution-receipt.json`。候选源码分支已推送；Firebase Dev／Production Hosting 和正式 iOS App 本轮未部署。设备与会场验收均为 `not_run`。
