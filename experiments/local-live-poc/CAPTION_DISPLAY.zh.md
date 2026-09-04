# 实时字幕显示方案：当前句流式 + 前一句保留

## 结论

推荐把现有“只显示一组中英文”的页面升级为一个克制的双层字幕栈：

1. **当前句**占据主视觉区域：中文最大，英文较小；中文使用 append-only token 流式显示。
2. **前一句 final**保留在当前句上方：中英文都显示，但字号缩小、颜色弱化。
3. 新句开始时，上一组完整中英文移入前一句区域；当前英文立即出现，当前中文从空白开始流入。
4. 不做横向跑马灯，也不让整段文字持续像新闻 ticker 一样移动。

这是一种 `paint-on + one-line history` 的混合方案：保留实时感，也让偶尔抬头、漏看半句的人能恢复上下文。它比传统多行 roll-up 更适合当前“远距离看大号中文”的核心目标。

## 已保存的当前 UI 基线

2026-09-04 在 `1280 × 720` 浏览器视口检查了当前 operator 页面：

- 顶部是麦克风、输入音量、计时和开始/停止控制。
- 中央只有一组字幕：超大中文居中，较小英文位于其下。
- 底部是 ASR、翻译模型、延迟、Gateway、本地保存和 context 状态。
- 手机 viewer 同样只显示一组中英文，并提供字号加减。
- `translation.partial` 已经让当前中文逐步增长；非 append 更新会被拒绝，因此已有稳定流式显示的基础。

当前基线保持不变，本文只保存下一版方案，没有修改 working UI。

## 当前实现中的一个配对风险

收到新的 `asr.final` 时，operator 页面会立即换成新英文，但暂时保留上一句中文，直到新中文的第一个 token 到达。这个短窗口会把“新英文”和“旧中文”错误地放在同一组中。

双层字幕栈可以自然解决：旧中英文整体移入前一句区域；当前区域显示新英文和“正在翻译”的空中文状态，绝不把跨 segment 的中英文配成一组。

## 常见流动字幕模式

W3C 将常见 caption 表现归纳为 `pop-up`、`roll-up` 和 `paint-on`。其中 roll-up 会逐词或逐小组填充一行，新行出现后把旧行向上推出；paint-on 则逐步增加文字但不移动已经显示的内容。[W3C TTML caption styles](https://www.w3.org/TR/ttml10-sdp-us/)

| 模式 | 显示方式 | 优点 | 缺点 | 本项目判断 |
|---|---|---|---|---|
| Pop-on / 整句替换 | 等 final 后整块出现，下一句直接替换 | 最稳定；句子完整；排版容易 | 等待感更强；上一句立刻消失；偶尔抬头容易漏掉 | 可作为 A/B 基线，不做默认 |
| Paint-on / 当前句逐步增长 | token 或短词组从左到右追加 | 首字最快；与讲话进度同步；不需要滚动整页 | 如果模型回写会闪动；不断增长会引起换行 | 当前已有基础，继续使用 append-only |
| 传统 Roll-up | 保留 2–4 行，新行把旧行向上推 | 上下文连续；适合高密度实时转写 | 持续运动；占屏幕；字号被迫缩小；眼睛需要更多追踪 | 不适合作为远距离大字默认 |
| 当前句 + 前一句 | 当前句大字流入，上一句固定在上方、弱化 | 实时、稳定、可恢复上下文；层级清楚 | 比单句占更多空间；双语会增加视觉密度 | **推荐默认** |
| 完整滚动 transcript | 历史文本形成可滚动列表 | 可回看很久；适合会议记录 | 不适合远距离跟读；用户滚动后会脱离 live 位置 | 以后可做独立回看模式，不放主屏 |
| Karaoke / 当前词高亮 | 整句已知，当前词随音频高亮 | 很容易跟随精确时间 | 依赖可靠词级 timing；视觉活动频繁；翻译并非逐词对齐 | 不做第一版 |

正式字幕指南通常偏向一至两行、在语法停顿处分行，并避免字幕在屏幕上跳来跳去。DCMP 也建议最多两行和一致的位置。[DCMP Captioning Key](https://dcmp.org/captioningkey/print) 传统 roll-up 虽然适合 live 场景，但 W3C 汇总的研究信号显示用户对 roll-up 与 pop-on 的偏好并不一致，而且滚动字幕可能需要更多眼睛注视。[W3C Roll-up Captions](https://www.w3.org/community/texttracks/wiki/RollupCaptions)

## 推荐布局

### 当前句

- 中文是唯一一级视觉，使用现有大字号策略。
- 英文继续放在当前中文下方，保持现有次要字号。
- 中文 partial 只允许末尾追加；每秒最多渲染约 5 次，避免每个 token 都引发布局抖动。
- 为两至三行中文预留固定高度；换行时文字区域不整体上下跳。
- final 到达后冻结，不再修改。

### 前一句

- 位于当前句上方，保持固定区域，不随 token 持续滚动。
- 上一句中文使用当前中文约 `38%–45%` 的字号；英文再小一级。
- 不直接给整个区域使用低 `opacity`；使用经过对比度验证的 muted 文字颜色，让它看起来弱化但仍能读清。
- 保留到下一句开始并被新的 previous final 替换，不按固定秒数自动消失。
- 只在句子交接时做一次 `160–200 ms` 的轻微上移和淡入；开启 `prefers-reduced-motion` 时完全取消动画。

### 不同屏幕

| 屏幕 | 前一句区域 | 当前句区域 | 重点 |
|---|---:|---:|---|
| MacBook Pro | 可用字幕高度约 20% | 约 65% | 当前中文仍需支持远距离阅读 |
| iPhone 竖屏 | 最多约 28% | 至少约 58% | 前一句中英文各最多两行，当前中文优先 |
| iPhone 横屏 | 最多约 22% | 至少约 64% | 当前中文尽量保持一至两行 |

横屏/竖屏按钮只切换页面布局；物理方向锁定仍按 [公网分享方案](./PUBLIC_SHARING.zh.md) 中的 best-effort 规则处理。

## 字幕状态模型

建议把单个 `caption` state 改为两个明确对象：

```json
{
  "previousFinal": {
    "segmentId": "seg-41",
    "en": "We walk by faith, not by sight.",
    "zh": "我们凭信心而行，不凭眼见。"
  },
  "active": {
    "segmentId": "seg-42",
    "en": "That changes how we face tomorrow.",
    "zh": "这改变了我们…",
    "phase": "streaming"
  }
}
```

状态转换：

1. `asr.final(seg-42)`：把上一组完整 final 移入 `previousFinal`；创建只有英文的新 `active`。
2. `translation.partial(seg-42)`：只 append `active.zh`；旧 segment 或非 append partial 继续拒绝。
3. `translation.final(seg-42)`：冻结 `active`，等待下一次 ASR final。
4. `translation.failed`：当前英文保留，中文显示简短降级状态；前一句不消失。
5. SSE/公网重连：snapshot 同时包含 `previousFinal` 和 `active`，避免重连后上下文丢失。

现有 SSE event 已包含 `segmentId`、英文、中文和 partial/final 类型，所以正常流式过程中不需要新协议。为了让刷新或重连后仍能恢复前一句，`caption.snapshot` 需要从单组字段扩展为上述双层状态。

## 稳定性原则

Google Research 的 CHI 2023 研究发现，live caption 中反复改写 interim text 会产生可测量的闪动，并与分心、疲劳和阅读困难相关；token alignment、语义合并和轻微平滑动画可以改善体验。[Google Research: Text Stability in Live Captions](https://research.google/pubs/modeling-and-improving-text-stability-in-live-captions/)

因此本项目保持以下约束：

- 已显示的当前中文不从中间删除或改写。
- 前一句只接收 `translation.final`，绝不显示 partial。
- 句子交接时整组中英文一起移动，避免语言错配。
- 不做连续像素滚动、跑马灯或逐字跳位。
- 动画不能延迟字幕事件，也不能进入模型延迟指标。

中英双语会占用更多视觉注意力，但相关眼动研究也表明双语字幕的效果取决于观看任务和内容；不能简单断言双语一定更好或一定造成过载。[Liao, Kruger & Doherty 2020](https://www.jostrans.org/article/view/8244) 对本项目而言，中文是理解主通道，英文是较弱的核对 sidecar，因此需要明确层级，而不是两种语言同权显示。

## A/B Test

使用同一场已保存的 ASR/翻译 event replay，不重新运行模型：

- **A：当前基线**——只显示当前中英文。
- **B：推荐方案**——当前句 paint-on + 前一句 final。
- **C：可选压力组**——传统两行 roll-up，只用于证明是否真的有必要。

至少在 MacBook、iPhone 竖屏和 iPhone 横屏分别验证：

- 偶尔移开视线 3–5 秒后，能否恢复语义上下文。
- 当前中文字幕是否仍足够大，是否超过两至三行。
- 中英文是否曾跨 segment 错配。
- partial rewrite/reject 次数、caption layout shift、掉帧和 render latency。
- 主观评分：易读、分心、疲劳、上下文连续性。

## 第一版验收标准

- 当前句始终是全屏最明显的信息；前一句不能抢夺视觉中心。
- 前一句完整保留中英文，并只来自 final event。
- 新 ASR final 到新中文首字之间不出现“新英文 + 旧中文”配对。
- 断线重连后同时恢复前一句和当前句。
- 典型三秒 segment 在三类目标屏幕上不溢出、不遮挡状态栏。
- `prefers-reduced-motion` 下没有滚动动画，功能不受影响。

## 当前状态

本方案已经记录，尚未修改 operator 或手机 viewer。下一步应先用固定 replay 制作 A/B 页面状态，再决定是否替换 working UI。
