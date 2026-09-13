# 手机媒体回路探针

独立 Discovery 工具。首轮是可控 WebSocket/WSS 媒体回路，不是 WebRTC/SFU，也不包含 ASR、翻译、TTS 或已验证的手机生产体验。普通桌面浏览器、合成音和真实手机分别记录，不能互相替代。

只有一个固定静态页面与 `/ws`。页面可做：

- **单机回环**：本页合成静音、合成短音或麦克风 → 媒体服务器 → 本页 WebAudio 处理/播放。
- **admin/user**：admin 同三种输入 → 同一服务器 → user WebAudio 处理/播放；回执再发回 admin。

## 依赖与启动

Python 3.11+、`websockets>=16.1,<18`。当前 POC 的 `.venv/bin/python` 已有 websockets 16.1.1，可只读复用解释器；不修改它的依赖。另一台主机应使用独立环境，不升级正在运行的模型环境。

从仓库根目录启动示例（由负责主机/公网入口的操作者执行）：

```bash
experiments/local-live-poc/.venv/bin/python \
  experiments/mobile-live-translation/media-probe/probe_server.py \
  --host 127.0.0.1 --port 18781 --host-label macbook \
  --token-file /absolute/private/new-media-probe.token \
  --output-dir /absolute/private/media-probe-summaries \
  --ttl-seconds 1800
```

默认只允许本机 `http://127.0.0.1:18781`、`http://localhost:18781`。经过已授权的专用 TLS tunnel 时，额外传 `--public-origin https://exact-temporary-host.example`；服务器只接受该精确 Host/Origin，不信任 `X-Forwarded-Host`，不自动放宽域名。服务始终绑定 loopback，隧道只应指向探针端口。DGX 用相同文件和协议，可选择 `--port 18782 --host-label dgx`；经 SSH 转发时显式保留测试 origin。两主机顺序测，改变的变量和网络路径分别记录。

`--token-file` 必须是全新路径，服务生成 256 bit 高熵 token，文件权限 0600，不打印内容。进程结束删除自己创建的 token 文件；有效期为 60–3600 秒，默认 1800 秒，到期结束探针并关服务。每进程最多 10 轮，每轮 5–120 秒。停止探针不会自动关闭操作者另行启动的 tunnel。

桌面可在页面用文件选择器导入 token 文件：仅 `File.text()` 读入 password 字段，不上传文件、不输出内容。手机可使用私下交付的 `https://host/#token=...&role=user` 链接；fragment 不进入 HTTP 请求，页面载入后立即从地址栏移除。不得把实际令牌贴到 Git、普通日志或测试摘要。连接媒体前必须以首条 WS `auth` 消息鉴权；匿名只能读取固定 app shell，拿不到媒体、会话或摘要。

## 操作

1. 选择真实设备与网络声明，连接。单机选择“单机回环”；两端分别选 admin、user。
2. 接收端点击“启用接收播放”，满足浏览器用户手势要求。两端模式需 user 已就绪。
3. 发送端默认**合成静音（仅处理链路）**、30 秒，点击开始。`synthetic_silent` 仍发同样 3200 bytes/100 ms PCM，但样本全部为零，服务端拒绝该模式中的非零 PCM；只验证传输与 WebAudio 输出处理，不验证可听音。附近正在运行现场采音时保持静音。合成短音和真实麦克风仍可选；真实麦克风只在明确选中时申请权限，单手机麦克风回环应佩戴耳机，避免播放声再次进入麦克风。
4. 停止、断线、页面进入后台、音频输出暂停或时长到期会清空队列。迟到的旧 epoch 帧不恢复播放，不补发后台累积音频。
5. 服务器保存 JSON 摘要，页面也可下载。不默认落盘原始输入或输出音频。

协议/速率拒绝可能先关闭连接，页面未收到结束事件；重新连接同一仍有效的探针服务会自动请求最近一份摘要。首次连接的空摘要不会清除页面已有摘要。服务进程结束后仍可由操作者从摘要目录恢复 JSON。

## 计时含义

所有媒体计时从发送端 `emitPcm()` 开始：**不包含首个麦克风样本累积成 100 ms PCM 帧的等待**。也不包括用户耳机里的声学听觉测量。

| 指标 | 时钟与范围 |
|---|---|
| `role.transportRttMs` | 各浏览器自己的 `performance.now()`：ping → 服务 → pong；纯控制消息 RTT |
| `mediaReceiveAckRttMs` | 发送端自己的时钟：发 PCM → 接收端 JS 收包 → 回执返回发送端 |
| `mediaPlaybackAckRttMs` | 同一发送端时钟：发 PCM → 接收端 AudioWorklet 开始把该帧写到音频输出 → 回执返回 |
| `playbackAckMinusReceiveAckMs` | 同一 PCM 帧两个回执抵达发送端的差值；含缓冲、回调调度和返程网络抖动，不是纯播放/声学延迟 |
| `receiveToRenderCallbackMs` | 接收端自己的时钟：JS 收到 PCM → 主线程收到该帧的 Worklet 输出处理回调 |
| `receiveToOutputEstimateMs` | 浏览器支持 `getOutputTimestamp()` 时的设备输出时间估计；没有能力时不填，不冒充实际耳机发声 |
| `serverRelayToReceiveAckMs` / `serverRelayToPlaybackAckMs` | 服务器自身 monotonic clock 的出发/回执往返；不与浏览器时间相减 |

播放端初始缓冲 2 帧（200 ms），固定最多 8 帧。网络发送队列最多 16 项，排队超过 500 ms 的媒体帧直接丢弃。记录 seq gap、过期/队列丢弃和播放 underrun；有缺口的结果不称为完整播放。音频处理回执只证明 WebAudio 路径工作，扬声器静音、音量、蓝牙或耳机的真实发声还需独立声学验收。

浏览器 PCM 在 WebSocket 已积压约 10 帧时丢弃新增输入；所有控制消息发送前同时检查总发送缓存，超过 64 KiB 时停止本轮、清队列、清心跳并关闭连接。8 秒没有收到匹配 pong，或建立连接后 8 秒仍未完成鉴权，也会执行同样的本地收敛；不依赖半开连接最终触发 `close` 事件。正常停止一轮后可保留已连接的低频 RTT 心跳，故障关闭路径绝不递归发送 Stop。匹配中的 ping ID 最多保留 32 个，覆盖合法 watchdog 窗口。

摘要中的 `deviceClaims` 是操作者声明；`phoneVerifiedByProbe=false` 始终保留。手机实测的人工或外部设备证据需另附；不能因为把下拉选成“手机”就形成真实手机验收。

静音摘要保留 `inputMode=synthetic_silent`；只有实际接收过全零帧才有 `silentPcmValidated=true`，同时记录 `audibleSignalGeneratedByProbe=false`、`audibleOutputValidated=false`。有 Worklet 回执不改变这个限制。

## 协议与边界

- `auth`：版本 `mobile-media-probe-v1`、短期 token、角色和有限设备/网络枚举。每角色最多一连接；loopback 与 admin/user 不同时占用。
- `playback_ready` / `start` / `stop` 控制单轮；server 生成 runId 与递增 epoch。
- PCM：12-byte 网络序头 `MP01 + epoch(uint32) + sequence(uint32)`，后接 3200 bytes little-endian int16，16 kHz mono、100 ms。10 帧/秒，最多 5 帧瞬时 burst；拒绝错误格式、重复序号、过大 gap、错误角色。
- `received`、`played`、`media_ack`、`observation` 分开记录浏览器证据；控制数据上限 2048 bytes、65 条/秒（burst 80），WS 单消息上限 4096 bytes。合法 loopback 在 10 帧/秒时有 10 received + 10 played + 30 observation + 2 ping + 2 rtt = 54 条/秒，预算保留有限余量供状态回执；超额持续流量仍拒绝。
- `stopped` 返回无 token/音频正文的摘要；只保存最多 1220 个有界计时样本的统计分位数。HTTP 不提供模型、restart、任意文件、日志或摘要下载 API。

鉴权用户可以提交测量值，摘要明确为 client-reported；这不是对不可信客户的防作弊 benchmark。公网运行仅用于私有短时测试，不替代生产身份/房间/用户管理。

## 定向测试

从本目录运行：

```bash
../../local-live-poc/.venv/bin/python -m unittest test_probe_server -v
node --test protocol.test.mjs
node --check app.js
```

这些测试使用内存假连接与 Worklet 仿真，不启动持久服务、不调用模型、不开放公网。真实浏览器播放、手机麦克风、蜂窝网络与两主机对照由操作者另行验证。
