# 复盘：20261116-ios-builtin-mic-route

数据见同目录 INDEX.md 和 manifest.json。本轮是 iOS 客户端的定向测试与真机路由验收，没有 L1–L4 生产阶段，未执行的小节在下面写明原因。

## 结论先行

交付类型：测试。最终状态：模拟器全量通过；真机上两条目标测试通过，整轮仍报失败，8 项失败与本改动无关。

结束信号：三份 `summary.json` 与各自 xcresult。

证据边界：真机只证明「蓝牙耳机连接时，听声对齐的录音输入是手机内置麦克风、输出仍留在蓝牙 A2DP」。不证明实际听感、现场同步精度、TestFlight 分发或发布。

关键结论（真机 iPhone 17 Pro / iOS 27.2.1，蓝牙耳机已连接）：

```
[AudioSession] alignment capture route input=MicrophoneBuiltIn output=BluetoothA2DPOutput
```

`MicrophoneBuiltIn` 即 `AVAudioSession.Port.builtInMic` 的原始值。

## 总时间

- 模拟器 iOS 27.2 全量：33.6 s 测试，构建增量。
- 模拟器 iOS 26.2 定向：9.3 s 测试。
- 真机 Beta 构建 + 安装 + 启动：47 s；随后整轮测试 105.9 s。
- 等待：插件 lldb 三次 attach 均未停下进程（每次约 35 s），改用真机测试套件取证，损失约 2 分钟。

## 各层模型、耗时与速度

| 层／阶段 | 模型或后端 | 推理强度／tier | 调用次数 | 计算耗时 | token 或音频秒数 | 速度 | 费用 | 证据 |
|---|---|---|---|---|---|---|---|---|
| L1–L4 | not_run | — | 0 | — | — | — | 0 | 本轮只跑客户端测试 |

本轮没有模型调用，收据表为空；`manifest.json` 里的哈希对应三份 `summary.json` 与真机控制台节选。

## 错误

| 层／阶段 | 现象 | 原因 | 发现时机 | 处理 | 回归测试 | 提交或 PR |
|---|---|---|---|---|---|---|
| 真机整轮 | 7 个单测报 `NSCocoaErrorDomain 260`，读不到 fixture | 这些测试用 `#filePath` 拼绝对路径读构建机文件，设备上不存在 | 占用设备后 | 判为模拟器专用，未改测试 | 无 | 后续可加 `XCTSkip`（见改进） |
| 真机整轮 | `TongxingUITests-Runner` 初始化超时 | 设备未开启「启用 UI 自动化」 | 占用设备后 | 本轮不需要 UI 测试，未处理 | 无 | 操作员设置项 |
| 真机调试 | `xcode_lldb attach` 三次都在 35 s 后报「process never stopped」 | 未定位；设备调试通道未给出停止事件 | 占用设备后 | 改用真机测试套件读同一路由 | 本轮改用测试证据 | 记在本报告 |

## 可以改进的地方

| 类别 | 改进 | 依据（本报告的数值或错误） | 预期收益 | 负责人 | 跟踪 |
|---|---|---|---|---|---|
| 预检 | 设备跑全量前先确认 UI 自动化开关与 fixture 依赖 | 本轮 8 项失败 | 省一次约 2 分钟返工 | 待定 | 本报告 |
| 质量 | 给 `#filePath` fixture 测试加 `fileExists` 的 `XCTSkip`，让设备整轮可作回归信号 | 同上 7 项 | 设备全量不再红 | 待定 | 本报告 |
| 流程 | 记录无可用物理设备时先问，再准备构建 | 本次在无设备时先做了签名与构建准备 | 少一次等待 | 待定 | 本报告 |

## 实际覆盖范围

- 执行：`TongxingTests` 在 iOS 27.2 模拟器（178 项，16 跳过）；`AudioAlignmentControllerTests` 在 iOS 26.2 模拟器（48 项，2 跳过）；Beta 身份整轮在 iPhone 17 Pro / iOS 27.2.1（179 项，16 跳过，8 失败见上）。
- 未执行：L1–L4 生产、TestFlight 分发、现场听感与同步精度验收、iOS 17 最低系统（本机没有该运行时）。

## 遗留状态

- 手机上现在是同 bundle id 的本地签名 Beta 构建，覆盖了 TestFlight 版；用户会自行从 TestFlight 重装。
- 无 job hold，无新增构建号；本轮产物都在被忽略的 `artifacts/` 下。

## 外部可见的变化

- 分支 `fix/ios-builtin-mic-route` 已推送、未合并；本报告走独立 docs-only PR。
- TestFlight、App Store 与网页未变。
