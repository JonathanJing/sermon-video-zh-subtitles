# iOS 听声对齐早停设计：同一会话 checkpoint 可靠命中即结束

日期：2026-10-06。对应 [FIELD-03](../docs/field-fingerprint-alignment-backlog.zh.md)（同一次连续采集的 10→15 秒与预算合同）的 iOS 原生实现。FIELD-03 的 Web 批次已 in_progress（10 秒 Web 采集与瞬态恢复共享 15 秒占麦预算），本设计补上 iOS 原生侧。实现前已核对 `FingerprintMatcher`、`PublishedFingerprintMatcher`、`MicrophoneCapture`、`AudioAlignmentController` 当前源码。

## 1. 现状与问题

- iOS legacy 路径固定采音 8 秒、published 路径固定采音 10 秒，采完才匹配。现场用户平均要等 8–10 秒才有结果，20 秒总截止的大部分时间花在等待采音结束。
- `MicrophoneCapture.capture(seconds:)` 是一次性的：`CaptureAccumulator` 攒满固定秒数才返回，中间无法拿到 prefix 做增量匹配。
- 两个匹配器都要求查询 ≥7 秒（`FingerprintMatcher.match` 要求 ≥7 秒做首尾窗口一致性；`PublishedFingerprintMatcher` 要求 7–20 秒）。这是 checkpoint 下限的硬约束。

## 2. 目标与非目标

目标（FIELD-03 iOS）：

- 同一输入会话内积累连续 PCM；在 checkpoint 点用 prefix 做可靠命中检查，命中即早停并自动跳转；证据不足则继续采音至同次会话上限。
- 不重启麦克风，不拼接两次互不连续的录音；不足完整窗口时用合规真实时长或安全拒绝，不补静音、不隐形延长。
- 复用现有阈值与一致性门槛，不下调（FIELD-07）；时间补偿只做一次（FIELD-05）。

非目标：

- 不做任意 2–3 秒命中。FIELD-10 明确：当前 published 最短 7 秒，不能宣传更短命中；更早 checkpoint 是非阻塞后续实验。
- 不换算法、不调阈值权重（另开版本，见 FIELD-07）。
- 不做后台持续监听、不做长期漂移跟踪（FIELD-08）。

## 3. 方案

### 3.1 采集：流式快照（`MicrophoneCapture`）

- `CaptureAccumulator` 增加持锁快照方法 `snapshot() -> (samples: [Float], startedAt: ContinuousClock.Instant)?`，只拷贝当前已累积样本，不结束采音、不触发 continuation。
- `MicrophoneCapture` 新增 `captureStreaming(maxSeconds:totalBudget:)`（命名待定），返回 `AsyncStream<CapturedAudio>`：每累积满 1 秒发出一次当前 prefix（含 `startedAt`，即首样本单调时钟）。权限、tap、中断、取消逻辑与现有 `capture(seconds:)` 完全复用；`cancel()` 语义不变。
- 占麦预算：单次会话最多 15 秒（FIELD-03 Web 批次已冻结“单次占麦最多 15 秒”，iOS 对齐）。现有 `capture(seconds:)` 的 7–12 秒 guard 保留；流式路径上限 15 秒。总 deadline 保持 20 秒不变，覆盖权限等待、索引准备、匹配与恢复播放。

### 3.2 Checkpoint 与判定

Checkpoint 点：7s → 10s → 12s → 15s（会话上限）。

- 7s：最小有效查询（两个匹配器下限），legacy/published 通用。
- 10s：与 Web FIELD-03 的 10 秒快照对齐；legacy 路径现有 8 秒行为被 7s/10s checkpoint 覆盖，不再单独保留 8 秒固定值。
- 12s/15s：证据不足时的延长点；15s 到仍无可靠命中则安全拒绝。

判定（每个 checkpoint）：

- 对 prefix 跑现有完整 `match()`（legacy 用 `FingerprintMatcher.match`，published 用 `PublishedFingerprintMatcher.match`），**阈值一字不改**，含首尾 5 秒窗口一致性（≤0.16s）。FIELD-07：新采集策略不得下调阈值。
- 通过即早停。`match()` 的 `offsetSeconds` 即 query 首样本在源时间轴位置。
-任一 checkpoint 的 `match()` 明确拒绝（如 silence、ambiguous-offset）不直接判死：继续采音，后续更长 prefix 可能累积足够证据；只在 15s 上限到时统一按现有失败路径处理。

### 3.3 时间补偿（FIELD-05）

复用 `AlignmentTarget.position`，公式不变：`target = offset + elapsedSinceFirstSample`，其中 `elapsed` 从 prefix 的 `startedAt`（首样本单调时钟）到定位时刻。早停时 elapsed 更小，补偿误差反而小于等满 8/10 秒。补偿只做一次；恢复播放后的二次校正逻辑保留。

### 3.4 控制器状态机（`AudioAlignmentController`）

`run(selected:token:)` 改为 checkpoint 循环：

```
启动流式采音（同一会话）
for checkpoint in [7, 10, 12, 15]:
    等待 prefix 达到 checkpoint 秒数（或会话因中断/取消提前结束）
    后台 detached task 跑 match(prefix)
    guard current(token) else return          // 换篇/换轨/手动操作使旧结果失效
    if match 通过:
        停止采音（内部取消，不走用户取消路径）
        计算 target，applyAlignedPosition
        走现有"已对齐"分支（含恢复播放意图、二次校正）
        return
// 15s 上限到仍无可靠命中
走现有失败路径（"未找到可靠匹配，播放位置未改变。"）
```

- 状态文案新增"证据不足继续听"（FIELD-08 要求的状态区分）："已听 X 秒，继续确认中…"。原有"正在听原声，约 8/10 秒"文案按 checkpoint 改为渐进式。
- 早停成功与用户取消严格区分：内部停止采音用独立 token，不触发 `onFailure`；用户点取消仍走现有 `cancel(message:)`。
- 换篇、换轨、手动定位、`alignmentRevision` 变化：现有 `sourceStillCurrent`/`current(token)` 检查在每次 checkpoint 后都执行，过期结果直接丢弃。
- 匹配耗时计入占麦预算：checkpoint 计算在后台线程跑，不阻塞采音 tap；若某次匹配超时未返回，不阻塞后续 checkpoint（取消该次 worker，继续采音）。

### 3.5 线程与取消

- tap 回调只做 PCM 拷贝（现有约束保留）；快照拷贝持 `NSLock`，不做 actor hop、不做文件 IO。
- 每个 checkpoint 的匹配是独立的 detached task，可取消；新 checkpoint 开始时取消上一个未完成的匹配任务，避免旧结果晚到覆盖（`current(token)` + task 取消双保险）。
- `capture.cancel()` 后 `finish` 恢复播放会话（现有行为保留）。

## 4. 测试

- 复用 `Core/Tests/TongxingCoreTests/FingerprintReplayTests.swift` 的合成集：对 7s/10s/12s prefix 跑早停判定，统计早停率、与完整 8s/10s 结果的一致性、误跳率。阈值不调，只验证策略。
- `apps/tongxing-ios/Tests/AudioAlignmentControllerTests.swift` 新增用例（用 mock capture/mock matcher，不碰真麦克风）：
  - 7s checkpoint 命中 → 早停，采音停止，`applyAlignedPosition` 被调用一次且位置正确（含 elapsed 补偿）。
  - 7s 未命中、10s 命中 → 继续采音后早停。
  - 15s 上限无命中 → 安全拒绝，播放位置不变。
  - checkpoint 间用户取消 → 不跳转、不报失败（现有语义）。
  - checkpoint 间换篇 → 旧结果丢弃。
- 不新增真机/现场验收（FIELD-09 范畴），合成失败不能代替现场验收，文档中明确标注。

## 5. 验收（对照 FIELD-03）

- [ ] 10 秒命中、延长后命中、15 秒安全拒绝、启动慢、checkpoint 计算慢、frame gap、取消与晚到回调，均有测试覆盖。
- [ ] 新旧行为交叉：固定 8s/10s 旧路径的测试保留为回归（或明确标注被 checkpoint 覆盖）。
- [ ] 失败/取消不改播放位置；所有重试计入公开预算（20s deadline 内）。
- [ ] 阈值与 FIELD-07 基线一致（CI 可加一条"阈值未下调"的断言，或 code review 人工核对）。

## 6. 风险与未决

- 低端设备上 `match()` 对 7s prefix 的耗时：若单次匹配 >2s，会吃掉占麦预算。缓解：checkpoint 匹配任务设独立超时（如 3s），超时则放弃该次结果继续采音；真机实测后再冻结。
- `startedAt` 目前以"回调时刻减首 buffer 时长"近似（FIELD-05 已知限制）。早停不改变该近似，只是不再叠加多余等待。
- 7s prefix 的首尾 5s 窗口高度重叠，一致性检查的区分度低于 10s+。这是接受 7s 为下限的代价：误跳防护主要靠未下调的阈值 + runner-up 分离比；FIELD-10 的更早 checkpoint 实验另行评估。
