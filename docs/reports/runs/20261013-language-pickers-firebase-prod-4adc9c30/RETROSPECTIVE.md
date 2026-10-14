# Production 语言选择器部署复盘

- 范围：使用已有 Production 完整线上基线和 UI candidate，执行 guarded Hosting publish；不重跑 L1–L4 内容生产。
- 结果：退出码 0，deployed；c10d222bd231b959 → a0b4d399c4d38e81。发布前版本和 v3/v4 catalog 基线通过，发布后 catalog 回读通过，租约已释放。
- 耗时：收据起止 2026-10-13T17:53:25.075847+00:00 至 17:53:45.582493+00:00，约 20.5 秒；无分阶段计算/等待计时。
- 核验：Firebase 209 个文件清单无新增/删除，仅 8 个预期 UI 文件变化，其余 201 个 provider hash 保持。8 个变化文件 gzip hash 与 candidate 一致；8 文件及两个 catalog 全量 HTTP GET 原始 SHA-256 均一致。音频 Range 返回 206。反馈 API 只读 GET 返回预期 405 method_not_allowed，仅证明路由响应，未验证反馈写入。
- 浏览器：现场页面菜单中英韩西切换、证道中韩西切换均观察到相应正文及选择状态；界面语言与证道语言独立，最终恢复中文。控件检查不证明全部文案完成翻译；未做真实音频播放。
- 分支例外：来源 codex/language-pickers，114a10aa39dc2fbc51d348836c344923c1020217；PR #377 仍 open。用户明确要求执行该 Production candidate。尚未完成 dev/main 晋升，后续周更有覆盖旧 UI 的风险，应通过 #377 及后续代码晋升跟踪。
- 错误：未观察到发布/HTTP 检查错误，无重试。发布配置字节保留原有 rewrite、redirect 和 headers；未部署反馈服务或媒体 bucket。
- 遗留：保留本机候选与收据；没有删除产物。设备播放、场地验收 not_run，没有 TestFlight 操作。
- 报告：本地执行者已填写，待云端独立审核；后续代码晋升与设备/场地验收分别留证。
