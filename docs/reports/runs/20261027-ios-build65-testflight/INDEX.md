# Run digest 20261027-ios-build65-testflight

Generated 2026-10-27T15:27:08+00:00. Redacted copies only; source hashes are in manifest.json.

## 20261027-ios-build65

Source: `~/SynologyDrive/GitHub/Active/sermon-video-zh-subtitles/artifacts/run-report-inputs/20261027-ios-build65`

- summary `summary.json`: **uploaded_and_valid_but_device_routing_failed**

## 结果与证据边界

- Beta `1.26.22 (65)` 的原 Archive 已复用并导出 IPA；签发了 Apple Distribution 证书。Archive 与 IPA 的身份和 SHA-256 见 [summary.json](20261027-ios-build65/summary.json)。
- 上传日志显示二进制上传成功；随后 Beta 分组快照查询失败，包装命令以 1 退出。未据此重复上传。
- 2026-10-27 15:17:25 UTC 的 Apple 查询显示 Build 65 为 `VALID`、`IN_BETA_TESTING`，并属于 Rooted。
- 用户报告真机已安装 Build 65：测试链接能打开 Beta，但落到错误的默认页面。目标页面路由未验通过；设备现场验收 `not_run`。
- [summary.json](20261027-ios-build65/summary.json) 保留本机相关记录的 SHA-256；本报告不包含原始日志、密钥或二进制。
