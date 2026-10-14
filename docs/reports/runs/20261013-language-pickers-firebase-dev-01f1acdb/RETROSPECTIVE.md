# Firebase Dev 语言选择器部署复盘

- 实际范围：执行已有 UI Hosting candidate 的 guarded publish，复用既有内容；没有重跑 L1–L4 生产或人工审核。
- 结果：退出码 0，部署收据状态 deployed。基线 9701b07e637ce5a8；新版本 bc4e94edeec02a88。发布前检查版本及 v3/v4 catalog 基线，发布后版本变化及两份 catalog 哈希回读通过。
- 耗时：收据起止 2026-10-13T17:12:45.024693+00:00 至 2026-10-13T17:13:36.037426+00:00，共约 51 秒；没有单独阶段计算/等待计时。
- 错误：本次未观察到发布错误，无需重试。
- 预检：目标为 ai-for-god-sermon-audio-dev；当前 checkout codex/language-pickers，提交 114a10aa，执行前工作树干净。
- 遗留状态：发布器完成并释放远端租约；本机保留原始发布收据和候选产物。未执行清理。
- 外部变化：Firebase Dev Hosting 已更新。浏览器渲染、真实设备播放、场地验收均 not_run；没有 TestFlight 操作。
- 报告：本报告为本地执行者填写，供文档 PR 审核；云端独立复盘尚未执行。
- 后续：如需 UI 交互或设备验收，应针对此新版本另行验证。
