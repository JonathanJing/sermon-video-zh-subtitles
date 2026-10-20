# 复盘：PR #594 PDF 可选依赖声明

## 结论先行

测试交付。代码审查发现搬入生产包的移动 PDF 模块直接导入 ReportLab，而独立安装包未声明。head `4af1a51cc8aa3ee26ac363d5b1d9deaa995af1a5` 增加 `pdf` 可选依赖并在包 README 中列出独立安装命令。`pyproject.toml` 可解析；用隔离构建环境生成 wheel 成功，wheel METADATA 含 `Provides-Extra: pdf` 与仅对该 extra 生效的 `Requires-Dist: reportlab<5,>=4.2`。

## 错误与处理

第一次 wheel 尝试用了 `--no-build-isolation`，测试虚拟环境没有 `setuptools.build_meta`，在构建准备阶段退出 2；没有生成可验证的包。随后按项目声明的构建依赖启用标准隔离构建，退出 0 并核对 wheel metadata。此前 #594 20/20 移动 PDF 定向测试通过；本轮只验证新的包装元数据与文档，不重跑同一渲染行为。

## 范围、时间与成本

本轮是本地打包测试。L1–L4 均 `not_run`；没有 PDF 内容发布、模型、付费 API 或远端生产调用。没有阶段耗时收据可拆分。旧 head 的手动完整 CI 因新提交已使其过时而请求取消；新 head 的 PR CI 单独运行。

## 遗留状态与外部变化

待新 head 完整 CI 与审查；上层双 PDF PR 尚须按依赖顺序重合并。未发布页面、PDF、HTTP、TestFlight 或设备交付。
