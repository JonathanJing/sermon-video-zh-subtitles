# iOS 听声对齐早停：Beta 56 实现与验证边界

日期：2026-10-06。对应 [FIELD-03](field-fingerprint-alignment-backlog.zh.md) 的同次连续采集与预算合同。本文记录 PR #251 在 Beta 56 整合候选中的实际实现与定向验证；构建、分发和真机验收分别以发行报告为准。

## 1. 已实现行为

此前 legacy 固定采音 8 秒、published 固定采音 10 秒，采完后才匹配。当前控制器使用同一个连续录音会话，在 7 → 10 → 12 → 15 秒 checkpoint 取得已有 PCM 的快照并匹配。可靠命中即停麦、定位；证据不足继续采集，全部未命中则不改变播放位置。

两个现有匹配器都要求至少 7 秒查询。本次没有更换算法、修改阈值或降低拒绝门槛（FIELD-07），也没有实现 2–3 秒定位、后台持续监听或长期漂移追踪。采音保持 App 前台，权限、中断、换篇、换轨及手动操作继续受原有取消规则约束。

## 2. 实际接口与采音预算

`MicrophoneCapture.beginContinuousCapture(maxSeconds:)` 返回 `ContinuousCaptureSessionProtocol`，控制器调用：

- `waitUntil(seconds:)`：等待累计 PCM 达到 checkpoint，或会话终止；取消和中断会抛错。
- `snapshot() -> CapturedAudio?`：取得当前已采集的真实样本、采样率与同一首样本单调时钟，不停止引擎。
- `cancel()`：幂等停止引擎、移除 tap 和通知观察者，并按录音 token 恢复播放类别。

一次尝试只启动一个录音引擎，不拼接两次录音，不补静音。PCM 留在内存，不写入文件、不上传。原有一次性 `capture(seconds:)` 保留，现场对齐控制器改用上述连续会话。

预算分为三层：

| 范围 | 当前实现 |
| --- | --- |
| 单次采音 | 最多累计 15 秒 PCM；在引擎设置前冻结 `ContinuousClock` 的 15 秒绝对截止，独立 watchdog 在无 buffer 时也结束会话 |
| 每次匹配 | 3 秒绝对截止；超时结果丢弃，取消 worker，进入后续 checkpoint |
| 整次定位 | 保留 20 秒总 deadline，覆盖索引、权限、采音、匹配及恢复播放 |

watchdog 和匹配取消依赖系统调度；这些预算不构成对阻塞系统调用或不合作计算任务的硬实时抢占保证。15 秒限制采音会话，不保证定位结果在第 15 秒显示：最后一次匹配及播放恢复仍受总 deadline 约束。

音频 tap 的有效 `sampleTime` 必须连续；缺帧时安全中断，避免把断裂样本当作连续查询。无 buffer 或有效查询不足时拒绝，不隐形延长采音。

## 3. 匹配、状态与时间补偿

索引按本次来源绑定，legacy 和 published 使用各自现有匹配器。legacy 保留首尾窗口一致性检查；published 保留自己的现有证据门槛，不混用两者的量化或判定规则。

每个 checkpoint 的匹配通过一次性 continuation 竞争返回：结果、超时、取消只有一个获胜。超时不等待尚未退出的 worker；两个生产匹配器仍在计算循环中检查取消，晚到结果不能再次恢复 continuation 或改变播放位置。匹配期间采音可能被中断，所以结果返回后还会检查会话的 terminal error，确认后才接受命中或重试。

```text
准备索引和权限
启动同一连续会话 → listening
for checkpoint in [7, 10, 12, 15]:
    waitUntil(checkpoint) → snapshot
    matching → 有预算的 match(prefix)
    检查任务来源及采音终止错误
    命中：停止采音 → 定位 → 按原播放意图恢复
    未命中／匹配超时：listening → 继续下一 checkpoint
全部未命中：停止采音 → unmatched，播放位置不变
```

保留 Beta 55 的前台顶部反馈：只有录音引擎实际启动后进入 listening，权限弹窗阶段保持 preparing；匹配、继续采集与最终结果由同一控制器状态驱动。内部停麦不等同于用户取消；用户取消、中断或来源过期的结果不会自动跳转。

时间补偿继续使用 `AlignmentTarget.position`：`target = offset + elapsedSinceFirstSample`。所有 prefix 共用首样本 `startedAt`，恢复播放后的校正重新由原 offset 与当前单调时钟计算，不能把已补偿的 target 再累加 elapsed。首样本时钟仍使用回调时刻减首 buffer 时长的近似；硬件输入延迟及实际定位误差尚需真机验证，不能据早停推断精度提高。

## 4. 已执行验证

使用完整 Xcode，在 iOS 17.5 模拟器执行 hosted tests，没有使用真麦克风或现场声音。

| 阶段 | 实际结果 | 忽略目录中的证据 |
| --- | --- | --- |
| `AudioAlignmentControllerTests` 整类 | 35 个发现项，34 个实际通过、1 个 skipped、0 失败 | `artifacts/tongxing-ios/pr251-255/capture-cli/20261006T084801-test-d063a1bf/test.xcresult` 及同目录 `status.json`、`run.log` |
| 匹配期间中断修复后的定向回归 | 5 个实际通过、0 skipped、0 失败 | `artifacts/tongxing-ios/pr251-255/capture-cli/20261006T084924-test-25c6a73a/test.xcresult` 及同目录 `status.json`、`run.log` |

两阶段结果有重复测试，不相加成独立验收数量。Skipped 项是缺少冻结 Dev 资产的内容目录用例，没有使用实时网络回退，不能计作通过。

覆盖包括：7 秒快照的 56,000 帧、7 秒 miss 后 10 秒快照的 80,000 帧、全部 checkpoint miss、匹配超时继续、超时后不同位置的晚到 hit、checkpoint 等待中取消、无 buffer 的截止、启动失败的幂等恢复、sampleTime 缺帧与首样本时钟保持，以及匹配期间中断后不定位、不自动恢复。预算与资源清理测试使用可注入 setup／恢复回调，不宣称验证了真机录音硬件或系统音频路由。

首次整合验证中，旧 3 秒测试等待窗口不足以等待四次 published 匹配完成。只将三个真实 published DSP 用例的测试等待窗口改为 15 秒；产品每次匹配 3 秒和整次定位 20 秒预算没有改变，fake timeout 用例仍保留短等待以检测阻塞。

## 5. 尚未验收

- 真机引擎启动耗时、麦克风占用时长、耳机／来电中断、权限首次授予与取消后的音频路由恢复。
- 同一受控声源在 7／10／12／15 秒快照下的真实命中率、误跳率、延长后命中率，以及与原固定 8／10 秒策略的声学比较。
- 不同输入延迟、噪声、音量、设备与现场条件下的时间补偿误差和计算耗时。
- 冻结 Dev 资产目录验收及用户现场验收。

上述项目没有因模拟器通过或 Beta 分发而自动完成。当前证据支持状态、预算及取消语义；没有提供早停率、现场精度或耗电改善结论。后续受控回放和现场验证继续按 FIELD-09 记录实际设备、来源、操作与定位误差。
