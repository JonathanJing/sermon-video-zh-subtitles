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

真机整轮 179 项：155 通过、16 跳过、8 失败。8 项都在设备上真实复现，但都不经过本次改动触及的音频会话代码；同一批测试在模拟器上 0 失败。

| 层／阶段 | 现象 | 原因 | 发现时机 | 处理 | 回归测试 | 提交或 PR |
|---|---|---|---|---|---|---|
| 真机整轮（7 项单测） | `NSCocoaErrorDomain Code=260`，读不到 fixture | `URL(fileURLWithPath: #filePath)` 把构建机的源码绝对路径编进了测试二进制；手机上该路径不存在 | 占用设备后 | 判为模拟器专用，未改测试 | 模拟器同一轮同名测试通过 | 建议加 `XCTSkip`（见改进） |
| 真机整轮（1 项 UI） | `TongxingUITests-Runner (10788)` 初始化失败，`Timed out while enabling automation mode` | 手机未开启「设置 → 开发者 → 启用 UI 自动化」，自动化模式握手超时 | 占用设备后 | 本轮不需要 UI 测试，未处理 | 无 | 操作员设备设置 |
| 真机调试 | `xcode_lldb attach` 三次都在约 35 s 报「process never stopped」 | 未定位；设备调试通道没有给出停止事件 | 占用设备后 | 改用真机测试套件读同一路由 | 本轮改用测试证据 | 记在本报告 |

### 8 项失败逐条对照

| # | 测试 | 原因 |
|---|---|---|
| 1 | `AppDeepLinkModelTests.testLinkDuringRefreshSurvivesDelayedCatalogResponse` | 读 `Core/Tests/TongxingCoreTests/Fixtures/catalog.synthetic.json`，靠 `#filePath` 定位源码树；设备上无此路径 |
| 2 | `AppDeepLinkModelTests.testLinkDuringStartupSurvivesDelayedInitialCatalogLoad` | 同上 |
| 3 | `AppDeepLinkModelTests.testManualSelectionSurvivesDelayedMissingLinkRefresh` | 同上 |
| 4 | `AppDeepLinkModelTests.testMissingLinkPreservesExistingSelectionAndLocale` | 同上 |
| 5 | `AppDeepLinkModelTests.testWarmLinkSelectsRequestedPageAndLocale` | 同上 |
| 6 | `AudioAlignmentControllerTests.testDevCandidateSelectionRequiresBetaIdentityAndExactOrigin` | 读 `dev-candidate-catalog-readback.json`，同一 `#filePath` 机制 |
| 7 | `MachineDisclosureTests.testAudioDisclosureSurvivesTranscriptFailureAndRejectsStaleSelections` | 读 `shared-machine-checked-contracts.json`，同一 `#filePath` 机制 |
| 8 | `TongxingUITests-Runner`（不是具体用例） | UI 自动化模式未启用，runner 无法初始化 |

1–7 都用同一写法：`URL(fileURLWithPath: #filePath).deletingLastPathComponent()...Core/Tests/TongxingCoreTests/Fixtures/...`。`#filePath` 在编译期展开成这台 Mac 上的源码绝对路径，模拟器上该路径可读，设备上不可读；因此差异只在 fixture 能否打开，不在被测行为。本次两条路由测试不用 fixture，所以不受影响。

## 可以改进的地方

| 类别 | 改进 | 依据（本报告的数值或错误） | 预期收益 | 负责人 | 跟踪 |
|---|---|---|---|---|---|
| 质量 | 把 7 个 `#filePath` fixture 测试改成 bundle resource，或先用 `FileManager.fileExists` 判断后 `XCTSkip` | 真机 7 项失败 | 设备整轮不再红，可当回归信号 | 待定 | 本报告 |
| 预检 | 跑真机整轮前先确认「启用 UI 自动化」和 fixture 依赖 | 真机 1 项 UI runner 失败 | 省一次约 2 分钟返工 | 待定 | 本报告 |
| 流程 | 没有可用物理设备时先确认再准备构建 | 本次在设备接入前先做了签名与构建准备 | 少一次等待 | 待定 | 本报告 |

## 实际覆盖范围

- 执行：`TongxingTests` 在 iOS 27.2 模拟器（178 项，16 跳过）；`AudioAlignmentControllerTests` 在 iOS 26.2 模拟器（48 项，2 跳过）；Beta 身份整轮在 iPhone 17 Pro / iOS 27.2.1（179 项，16 跳过，8 失败见上）。
- 未执行：L1–L4 生产、TestFlight 分发、现场听感与同步精度验收、iOS 17 最低系统（本机没有该运行时）。

## 遗留状态

- 手机上现在是同 bundle id 的本地签名 Beta 构建，覆盖了 TestFlight 版；用户会自行从 TestFlight 重装。
- 无 job hold，无新增构建号；本轮产物都在被忽略的 `artifacts/` 下。

## 外部可见的变化

- 分支 `fix/ios-builtin-mic-route` 已推送、未合并；本报告走独立 docs-only PR。
- TestFlight、App Store 与网页未变。
