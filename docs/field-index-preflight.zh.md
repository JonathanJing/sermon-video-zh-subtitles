# FIELD-02：Web 采音前索引预检

本批为 **in_progress** 的会话级实现，依赖 #132 的本地诊断；PR 目标为 `dev`，合入顺序需保留该依赖。用户点击自动对齐后，先显示资料检查；同源 Worker 下载当前所选索引，校验 SHA、schema、来源、音轨、时间窗、算法、采样率、hop 和 posting 形状。通过后显示“开始听取并对齐”；用户再次点击才同步暂停配音并请求麦克风。缺失或损坏的资料不再消耗一次 10 秒采音。

预检与匹配使用同一个 Worker、同一份已校验索引；匹配再次比较完整 metadata 身份，不重新下载或接受另一份资料。切换内容或取消会关闭会话；失败、超时、完成均终止 Worker。采集仍是原 10 秒。资料预检最多 35 秒，已就绪索引等待点击最多 30 秒，采音/匹配操作最多 35 秒；过期即关闭 Worker。预检耗时进入现有本地诊断，采集前失败不会捏造占麦时间。

`force-cache` 仅为 HTTP 缓存提示。初始会话预检没有持久离线资料库；后续单索引缓存的范围见下文，仍不宣称整篇完全断网 readiness，也不自动下载历史内容。选篇/下载预备、离线状态区分、缓存撤回及峰值内存证据仍待实现。iOS 原生采音不受本批修改。Safari/iPhone 的权限、AudioContext 启动与真实网络/音频路径需要独立真机验证。

## 本地证据

- 完整 Web 套件 212 项通过，其中指纹相关 68 项；真实 Worker 模块（注入浏览器 globals）校验损坏 SHA、错误来源/窗口/算法、坏 posting，并验证复用不再次 fetch、未准备或过期身份拒绝、PCM 清理。
- 控制器测试验证预检先于 pause/麦克风，以及缺失/损坏、取消、切换和超时不启动采音；UI 测试检查预检及采音中的语言重绘不重启会话。
- weekly app 构建测试 17 项、部署 guard 测试 3 项通过；没有实际部署。
- #133 冻结数值合同检查通过 12 个合成场景。其 DSP 与本分支 `fingerprint-core.mjs` 的 SHA 均为 `d1a76ed47c066e9f19d8bf0a8cb2d3961cf876af6de14ae2cc4a8b3699d391c5`，算法和阈值未改。没有把合成检查作为真实声学成功率。

复现：

```sh
node --test experiments/sermon-dubbing-poc/web/*.test.mjs
python -m unittest discover -s experiments/sermon-dubbing-poc -p 'test_build_weekly_app.py'
python -m unittest discover -s experiments/sermon-dubbing-poc -p 'test_deploy_firebase_guard.py'
```

本批改变 Web 行为，E6 仍为 `review_required`。现有或新增自动测试不能关闭真实断网、冷/热缓存、Safari/iPhone、语言切换现场、物理输出计时和人工体验验收。

## 权限重试与新点击

预检的 Worker 回复跨越原点击任务，不能假定仍保有 microphone privilege。现在首击只准备资料；`ready_to_record` 阶段的新点击直接进入实际 capture/getUserMedia，中间不 await。权限拒绝后重试仍先完成资料预检，再等待新的录音点击；不会从异步预检回调自动申请权限。就绪期间切换身份、取消或等待超过 30 秒均释放会话。

回归用延迟 Worker 回复、实际 capture 模块和手势敏感的 MediaDevices stub，先模拟拒绝，再模拟第二次权限请求，断言两次 getUserMedia 都在新的同步点击中发生，没有触发无手势的缓存拒绝。另测就绪超时与身份变更。此为本地回归，未在 Safari 真机复现。依据是 WebKit 的 [MediaDevices privilege 计算](https://github.com/WebKit/WebKit/blob/main/Source/WebCore/Modules/mediastream/MediaDevices.cpp) 和 [缓存拒绝判定](https://github.com/WebKit/WebKit/blob/main/Source/WebKit/UIProcess/UserMediaPermissionRequestManagerProxy.cpp)；系统权限被长期禁用等情况仍需用户在浏览器/系统设置处理。

## 单个公开索引的持久缓存补充

后续实现为当前准备的公开索引增加 CacheStorage：使用独立版本化 cache 和一个固定 key，仅保留最后一份通过完整校验的索引，单份最多 32 MiB。并发 Worker 也只覆盖同一个 key；没有历史批量预取，不持久化现场 PCM、query landmarks 或诊断。另一个 locale/版本的准备只有在新 bytes 通过 SHA/schema/来源/音轨/窗口/postings 校验后才替换旧索引。

新 Worker 每次使用缓存均重新核对完整 SHA 和绑定；header 只是查找提示，不能替代验证。坏缓存移除后尝试正常下载，离线或下载仍坏则拒绝 readiness。CacheStorage 不可用/配额失败时，已校验的当前会话可继续；下次不能假称持久资料仍在。响应声明超限时立即取消，流式响应累计超限时取消 reader，先于 JSON 解码和持久化；这不是实测峰值内存上限。

这里只补**当前索引缓存**，不是整个 App 的离线资料包。浏览器可清理存储；其他页面/语言会覆盖缓存，目录、字幕、音轨仍有各自获取和离线状态。未实现选篇/下载时的完整资料预备或“可离线自动对齐”状态 UI，FIELD-02 验收仍未完成。再次录音继续要求 ready 阶段的新点击，不改变权限、采音长度或匹配阈值。

新增 7 个 Worker 回归（旧实现失败 6 个）覆盖新 Worker 断网复用、坏 bytes、伪造 header/不匹配绑定、切换索引、配额/存储不可用、声明/流式超限和并发固定容量。另有可重复的真实 Chrome 检查：

```sh
python scripts/verify_fingerprint_browser_cache.py \
  --browser '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome' \
  --out /tmp/fingerprint-cache-report.json
```

工具只用临时 profile、loopback 合成 fixture；冷加载后令**索引路由**返回 503，再创建新 Worker 验证真实 CacheStorage 复用，最后破坏缓存并确认失败及移除。浏览器/Worker 脚本路由仍在线，因此结果不能称整浏览器完全断网、跨 App 重启或 Safari/iPhone 验收。测试不请求麦克风，报告只记录粗粒度结果、浏览器版本和 Worker hash。
