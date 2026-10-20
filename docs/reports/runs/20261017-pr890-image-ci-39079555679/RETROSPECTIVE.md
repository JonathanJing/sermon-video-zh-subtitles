# 复盘：PR #890 镜像资源 CI

## 结论先行

测试类型运行；Backend image resources run 39079555679 在代码 head `e6a9c9a9` 成功结束。`resource-smoke` 成功，镜像构建日志显示安装 `tongxing-production` 与 `tongxing-api`，并执行新旧 Cloud Run dispatcher 导入检查。这是 CI 镜像证据，不代表部署或真实 Cloud Run 派发。

## 总时间

运行创建于 23:34:35 UTC，更新至 23:35:45 UTC，约 70 秒；`resource-smoke` 作业 23:34:37 至 23:35:44 UTC，约 67 秒。未保存作业内计算与排队细分。

## 各层模型、耗时与速度

L1–L4 均 `not_run`。没有模型请求、token、音频或费用指标；Cloud Run 请求 0。

## 错误

本轮无失败作业。镜像构建和导入检查成功。

## 可以改进的地方

保留镜像内旧路径、新路径和 `backend.app` 绑定烟测，后续包迁移可及时发现缺少 COPY 或安装步骤。此项由 PR #890 的 workflow 修改承担。

## 实际覆盖范围

CI 构建后端镜像并做导入烟测；没有真实凭据、Cloud Run API 请求、部署或线上服务读取。L1–L4 均未执行。

## 遗留状态

没有远端 Job 或生产产物。代码 PR #890 仍为草稿，Python 全量 CI 当时尚未终结。

## 外部可见的变化

仅 GitHub Actions 成功状态；没有部署、页面发布或设备验收。
