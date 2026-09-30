# Web 占麦累计预算：FIELD-03 的部分实现

当前 Web published 合同仍是 `captureSeconds: 10`，worklet 及匹配门槛不变。这一批只为现有采集及瞬态恢复增加共享的 15,000 ms 占麦预算；没有实现连续 10→15 秒策略，也没有改变原生 iOS 行为。

`captureFingerprintAudio` 累计每次流授权到停止轨道的单调时间，包括输入启动、worklet 加载及采集。每次恢复已清理前一段输入，并使用剩余预算；若不足完整的 10 秒窗口，直接拒绝，不请求新麦克风、不补静音、不拼接两次录音。独立权限等待及已停麦后的恢复等待不计入占麦；UI 原整次操作截止继续生效。

每个已授权输入设置剩余额度的停止计时器；worklet 消息到达时还核对真实经过时间，避免迟到的完整缓冲赶在延迟计时器前被接纳。结束、取消和预算错误均走现有轨道停止、端口清理和 AudioContext 关闭。诊断回调在内部累计之后执行，篡改或抛错不能恢复额度。`MIC_BUDGET` 只输出白名单提示，没有新增设备身份、PCM 导出或遥测。

这是浏览器可观察的 deadline 与拒绝策略，**不是硬实时停止保证**：主线程阻塞、系统挂起或浏览器调度可能延迟实际停止。必须继续记录实际占麦并进行真机生命周期验收，不能把设置了 15 秒定时器写成物理上绝不超时。

## 本地证据

- 9 项新增采集预算回归在旧实现全部失败，修复后通过。覆盖累计重试、启动耗时、权限等待分离、迟到缓冲、取消、诊断回调异常、非法预算；旧连续 PCM 与资源清理测试保留。
- Web 全套 228 项测试通过。错误控制器同时验证预算拒绝不 seek、不 play；诊断白名单加入有界错误码。
- 周页面打包与部署保护 20 项测试通过；没有执行部署。
- 可选真实 Chrome 假设备检查：

  ```sh
  python3 scripts/verify_fingerprint_browser_capture.py \
    --browser '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome' \
    --out /tmp/fingerprint-capture.json
  ```

  使用临时 profile、loopback HTTP、Chrome 合成媒体输入及真实 AudioWorklet；不使用物理麦克风、不导出 PCM。Chrome 154.0.8037.59 本次测得成功窗口为 10 秒/48 kHz、流占用约 10,172 ms；10,000 ms 预算用例拒绝并在约 10,005 ms 停止。两个流 ended、两个 context closed。初次测试 harness 的未绑定浏览器 timer 方法出现 Illegal invocation，修正 harness 后通过；该错误不计为产品回归通过。

FIELD-03 整项保持未验收。连续扩展能力版本、跨端协议、Safari 新点按权限、真实设备/route/后台/锁屏、低配总时间、现场误跳和精度证据仍待完成。没有降低任何匹配阈值，没有发布网站或提交 iOS 版本。
