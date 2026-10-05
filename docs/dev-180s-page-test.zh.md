# 固定三分钟 Dev 页面测试工具

这组工具复用既有缓存，测试正常页面 prepare、校验、封存、guarded Hosting 发布和 reader；不调用模型 API。模拟审核仅用于用户明确授权的 Dev 测试，不代表正式内容批准。当前双端读取存在已记录的时间轴失败，见 [本轮复盘](reports/20261004-dev-180s-page-generation-retrospective.zh.md)。

## 生成与发布

```sh
.venv/bin/python -m scripts.verify_dev_180s_page_test --help
.venv/bin/python -m scripts.build_dev_180s_simulated_inputs --help
.venv/bin/python -m scripts.prepare_dev_simulated_publication --help
```

`verify_dev_180s_page_test` 对固定媒体 SHA、时长、完整解码及 CLI 正负准入进行只读验证，输出使用新的目录。`build_dev_180s_simulated_inputs` 从 `artifacts/dev-full-rerun-20261001` 提取既有单元、译文与音频，构造醒目标记的独立模拟包并执行正常 delivery prepare。其 `--out` 应使用独立的 artifacts 子目录，不得指向正式 run 或已需保留的产物。

`prepare_dev_simulated_publication` 的 `baseline` 从真实 Hosting 版本获取文件清单和配置，缓存重用必须匹配线上 hash；`asset-first` 保留目录并先加入完整资源；正常 builder HTTP verification / seal 后，`overlay` 只允许增加一个隔离测试页，保持原有页面和默认页；`runtime-repair` 仅更新完整 reader 模块闭包，catalog 字节不变。该工具只准备快照，不自行部署。部署须使用正常 `guarded_hosting_publish` 的 Dev 配置与回执。不要重复发布结果未知的 attempt；先对账。

## Schema 与迁移

- 新 schema `sermon-dev-simulated-metadata-v1` 与正式 metadata schema 分开。精确绑定 Dev project、site、origin、channel、environment；生产 intent、缺失 intent、缺少模拟标题/摘要均拒绝。正式调用不接受该 schema。
- `sermon-multilingual-catalog-v3.schema.json` 标记 `x-contractRevision: 2`，补上 page/target 的可选 boolean `simulationOnly`、`diagnosticOnly` 和兼容线上既有顶层 `defaultTargetLocale`。wire `schemaVersion` 保持 v3，因为客户端已识别这些可选 flags；旧目录无需转换。新增标记后须重新封存、绑定 hash；默认 production reader 隐藏模拟页。page 内默认语言继续是权威值。
- prepared snapshot 从三个 Web 模块扩展为递归导入闭包。旧 preparation 的 runtimeAssets 不能充当新版闭包的完整证据，需重新 prepare/verify/seal。复盘里的运行时补丁有独立部署与 HTTP 回执。
- `content.durationSeconds` 继续代表源窗口；本轮没有新增配音时钟字段。长于视频的自然语速音轨可以通过 producer，但当前 Web/Beta reader 会失败；这是待修复的契约缺口。

媒体、环境、缓存、模拟包及部署回执留在 ignored artifacts。Git 只保存工具、schema、相关回归与复盘。
