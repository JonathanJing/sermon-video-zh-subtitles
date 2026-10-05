# 固定三分钟 Dev 页面测试工具

这组工具复用既有缓存，测试正常页面 prepare、校验、封存、guarded Hosting 发布和 reader；不调用模型 API。模拟审核仅用于用户明确授权的 Dev 测试，不代表正式内容批准。初次线上测试发现的时间轴问题已在 PR #245 的后续代码中修复并完成本地双端读回；没有重新部署或更新 TestFlight，见 [本轮复盘](reports/20261004-dev-180s-page-generation-retrospective.zh.md)。

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
- 新内容采用 `sermon-full-video-text-content-v2`：`durationSeconds` 继续代表源窗口，必需的 `audioDurationSeconds` 来自绑定音轨的 ffprobe 与完整解码，producer 要求与实际音轨相差不超过 0.05 秒。必需的 `reviewMode` 为 `formal` 或 `simulation`；后者只允许精确 Dev intent 和 page/target 的两种隔离 flags。全文/source cues 校验源时钟，口播 captions 和 Web track 使用音频时钟。
- v1 读取保留兼容性：缺少音频字段时回退原源时长；显式字段不可为 null、错误类型、非正、非有限或超过 24 小时。v2 缺少字段必须拒绝，不能从最后一条字幕猜时长。迁移时先测量原音轨、保留源窗口/全文坐标和音频/字幕字节，重新生成 content、HTML 与绑定它们的 products/release/catalog hashes，再走 prepare/verify/seal/publish。新旧契约的物理设备验收仍独立。
- 静态模板根据显式 `reviewMode` 输出审核声明；模拟 metadata 必须绑定模拟 v2 content，正式 metadata 拒绝模拟 content。模拟页不显示“已批准完整文稿”或“已审核译文”。

媒体、环境、缓存、模拟包及部署回执留在 ignored artifacts。Git 只保存工具、schema、相关回归与复盘。
