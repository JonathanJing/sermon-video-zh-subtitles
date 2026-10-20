# 复盘：20261017-dual-pdf-p2-parent-merge

证据：同目录 `INDEX.md`、`manifest.json` 与脱敏 pytest 日志。

## 结论先行

测试通过：dual PDF 五个串行 PR 合入 #571 最新 P2 修复后，顶端 #607 精确提交 `e9179499` 的 115 项测试和 90 个 subtest 全部通过；`git diff --check` 逐分支通过，五个远端提交均已核对。只证明本地代码兼容性。

## 总时间

最终 pytest 运行 30.07 秒。未运行远端模型、来源抓取或人工等待；本次不与此前不同测试范围比较速度。

## 各层模型、耗时与速度

L1–L4 均 `not_run`；模型调用 0、费用 0，没有 token、音频和模型速度数据。

## 错误

无测试失败或合并冲突。此前各 PR 的完整 CI 收据属于旧父提交，不能作为本轮最终树的完整 CI。

## 可以改进的地方

先固定 #571 的合同基线，再合并叠层 PR 并执行最终 CI，可减少重复验证；依据本轮五次无冲突父提交传播。负责人 Codex，跟踪 #571、#584–#607。

## 实际覆盖范围

覆盖 accounting sidecar、合同、严格 L2、post-live timeline、恢复交接和 supervisor 的定向测试；未执行真实媒体下载、PDF 发布、Secret Manager、GCS、设备播放或场地验收。

## 遗留状态

#584→#594→#598→#602→#607 均保持草稿，依赖 #571。父 PR 合并后需逐个 retarget 和最终 CI；无生产 job hold 或待处理构建产物。

## 外部可见的变化

只推送代码分支；Dev、Firebase、TestFlight、设备、场地均 `not_run`。报告经独立文档 PR 公开。
