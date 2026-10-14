# 复盘：20261013-web-early-stop-chrome

数据见同目录 INDEX.md 和 manifest.json。对应 PR #391（commit 4d476194）。

## 实际覆盖范围

只跑了 `scripts/verify_fingerprint_browser_capture.py`：在 Chrome 155 的合成媒体设备上运行真实 AudioWorklet 采集，覆盖 10 秒窗口、10 秒预算拒绝、15 秒带 7/10/12 秒前缀，以及在 10 秒处早停。不涉及 L1–L4 生产，没有使用真实麦克风、Safari 或 iPhone。

## 结果和结束信号

`summary.json`：`pass_2_of_3`。第 1 次在 110 秒内没有返回结果（`browser_deadline`），第 2、3 次通过：前缀 7/10/12 秒与 15 秒完整缓冲连续一致，10 秒处早停后占麦约 10.2 秒，4 条流和 4 个 context 全部释放。原始（dev）脚本基线单独跑一次也通过。

## 耗时

通过的两次各约 48 秒（含 Chrome 启动）。

## 错误

第 1 次超时的原因未查明：同一页面加入步骤标记后重跑，各步骤都正常完成，之后连续两次通过。可能与 Chrome 冷启动有关，但没有证据。

## 占用资源之后才暴露的错误

无。

## 遗留状态

无部署、无后台进程；临时浏览器 profile 已由脚本删除。

## 外部可见的变化

无。Safari、真机和会场验收均为 `not_run`。

## 后续

- iPhone Safari 实测早停与占麦释放：`FIELD-03`／`FIELD-09`，用户在设备上执行。
- 若超时复现，脚本应输出页面阶段，便于定位：`FIELD-01`。
