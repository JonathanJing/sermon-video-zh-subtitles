# FIELD-09：冻结数值合同检查

首批状态：**in_progress**。复用现有 JS→Swift golden 生成器与已提交的合成 fixture，新增只读检查入口，而不是在每次 CI 中重生成并接受新的期望值。

```sh
node apps/tongxing-ios/scripts/generate-published-fingerprint-golden.mjs --check
node apps/tongxing-ios/scripts/generate-published-fingerprint-golden.mjs --check --report /tmp/new-fingerprint-report.json
```

`--check` 不修改 fixture，报告文件必须不存在。原不带参数的显式重生成命令保持可用，但重生成属于待审查的基线变更，不能拿它消除未知回归。`--help` 说明参数；测试可通过 `--fixture PATH` 注入错误 fixture。

检查复用 production browser DSP，逐项核对冻结 query 与 matcher 输出：8 kHz、44.1 kHz、48 kHz，各自同源匹配、重复片段含糊、无关合成信号、静音，共 12 个确定性场景。量化 landmark 整数、数组长度、布尔接受与原因码必须一致；非整数浮点只容许 1e-9 的数值差异。差异路径最多输出 32 条，但 mismatchCount 记录完整数量。任何差异退出 1，不能给出通过报告。

报告绑定 fixture、DSP 和 generator 的 SHA-256，并记录 `spectral-landmarks-v1` / `sermon-landmark-index-v1`。它只声称 `deterministic_synthetic_browser_contract`；Swift parity、legacy packed、设备与现场默认 `not_run`，`promotionAllowed` 永远 false。原始冻结 fixture 和生产算法文件均未修改。

## 2026-09-30 本地证据

- Web 测试 197 项通过；新增 4 项覆盖不重写 fixture、严格数值/接受比较、坏基线退出失败、拒绝覆盖证据与错误文本不泄露。
- 12 个合成场景与冻结 fixture 一致。fixture SHA：`86528728985ecf9a6fcbfd9d4681fe1e37745581a114790dcd3d02614a9d91c0`。
- 另行执行 `PublishedFingerprintMatcherTests`：Swift Testing 报告 **2 个测试，其中 DSP 测试含 3 个采样率参数 case**，全部通过。它验证已有 Swift matcher 对同一冻结 fixture 的特征与接受/拒绝结果；不是 App、设备音频或可听输出测试。JS 报告不自动冒充这次独立 Swift 执行。
- 本机 SwiftPM 首次受嵌套沙箱阻止，随后同步目录构建产物受扩展属性签名限制；使用正常本地测试权限和 `/tmp` scratch path 后成功。未改全局 Xcode、签名账号、Core 源码或设备状态。

可复现 Swift 命令（按本机实际 Xcode 路径调整）：

```sh
DEVELOPER_DIR=/Applications/Xcode.app/Contents/Developer \
  swift test --package-path apps/tongxing-ios/Core \
  --scratch-path /tmp/sermon-field-parity-new-run \
  --filter PublishedFingerprintMatcherTests
```

这 12 个 case 是确定性数值合同，不能计算成独立声学样本、远场成功率、保留集误跳率或真机性能。真实授权语音、按源/会话分割的开发与保留集、Web Safari/iOS 分层、最低设备、route、耗时/误差分布及现场 P0 门槛仍待对应证据。没有下载素材、录音、上传或部署。
