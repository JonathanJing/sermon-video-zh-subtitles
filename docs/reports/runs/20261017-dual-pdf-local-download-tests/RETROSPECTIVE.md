# 复盘：20261017-dual-pdf-local-download-tests

数据见同目录 `INDEX.md`、`manifest.json` 和 `dual-pdf-local-download-tests-20261017/summary.json`。本报告仅记录本机 mock 与固定文件测试。

## 结论先行

交付类型：测试。基于 #598 head `a4d42f81`，纯移动提交 `a4831208` 保留实现字节；接线提交 `e67dccc0` 保留旧 CLI 和导入门面，给云服务及未迁模块增加延迟宿主绑定。6 个本地交接测试及 40 个相邻 post-live 测试均通过，`outcome.json` 为 `status=passed`、`exitCode=0`。`git diff --check` 退出 0。没有访问 Secret Manager、YouTube 或 GCS，没有下载媒体、付费模型调用或发布。

## 总时间

本地交接测试墙钟 0.453 秒，相邻 post-live 测试 2.302 秒，合计记录 2.755 秒，见 `timings.tsv`。其他短检查未统一计时；等待与返工未分段记录。无可比同范围上轮测试。

## 各层模型、耗时与速度

| 层／阶段 | 状态 | 模型、用量与费用 | 证据 |
|---|---|---|---|
| L1 来源 ASR、MFA、英文机器评审 | `not_run` | 无调用、无费用 | `summary.json` |
| L2 初译、独立审核、文本质检 | `not_run` | 无调用、无费用 | `summary.json` |
| L3 配音、回转写、音频质检 | `not_run` | 无调用、无费用 | `summary.json` |
| dual-PDF 下载交接与相邻时间线 | 46 个本机 unittest | 固定字节和 mock，远端调用 0，费用 0 | `summary.json`、`timings.tsv` |
| L4 发布 | `not_run` | 无发布、无费用 | `summary.json` |

## 错误

本轮最终命令无失败。未占用付费资源，也没有发布后错误。

## 可以改进的地方

| 类别 | 改进 | 依据 | 预期收益 | 负责人 | 跟踪 |
|---|---|---|---|---|---|
| 预检 | 隔离工作树测试时核对生产包文件路径及旧 CLI 工作目录 | 本轮使用工作树 PYTHONPATH，并对加载身份键和外部 CWD 做断言 | 避免误测主检出 | 该批维护者 | 代码 PR 验证说明 |
| 身份 | 迁移后的新运行冻结新实现哈希；旧收据保留原哈希 | 原实现 SHA-256 `561a042d…`，接线后 `e5a8185f…` | 避免误把旧交接证据当新实现批准 | 该批维护者 | 本批代码审查 |

## 实际覆盖范围

测试覆盖旧 `scripts` 导入同一模块、旧模块 patch 目标、仓库外 CWD 的 `--help` 和完全 mock 的 `missing_source`、相对与绝对路径解析、固定媒体的 SHA-256、manifest 无密钥及已完成重跑的幂等返回。相邻 post-live 时间线和字幕生成测试覆盖恢复提示与入口行为。没有执行真实下载、ffprobe 媒体探测、云端上传或四层生产流程。

## 遗留状态

没有远端 job hold、Dev 文件或构建号。代码提交 `e67dccc0` 已推送至独立分支，代码 PR #602 为草案；本报告通过单独文档 PR 交付。新实现哈希与旧收据不兼容，不改写旧收据。

## 外部可见的变化

无 Dev 发布、TestFlight 或受保护分支推送。HTTP、浏览器、设备播放及场地验收均为 `not_run`。
