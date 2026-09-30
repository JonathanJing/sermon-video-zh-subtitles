# FIELD-02：Web 采音前索引预检

本批为 **in_progress** 的会话级实现，依赖 #132 的本地诊断；PR 目标为 `dev`，合入顺序需保留该依赖。用户点击自动对齐后，先显示资料检查；同源 Worker 下载当前所选索引，校验 SHA、schema、来源、音轨、时间窗、算法、采样率、hop 和 posting 形状。通过后才暂停配音并请求麦克风。缺失或损坏的资料不再消耗一次 10 秒采音。

预检与匹配使用同一个 Worker、同一份已校验索引；匹配再次比较完整 metadata 身份，不重新下载或接受另一份资料。切换内容或取消会关闭会话；失败、超时、完成均终止 Worker。采集仍是原 10 秒，整个操作保留 35 秒上限。预检耗时进入现有本地诊断，采集前失败不会捏造占麦时间。

`force-cache` 仅为 HTTP 缓存提示。这个实现没有持久离线资料库，不宣称完全断网 readiness；也不自动下载历史内容。选篇/下载预备、离线状态区分、缓存撤回及峰值内存证据仍待后续实现。iOS 原生采音不受本批修改。Safari/iPhone 的权限、AudioContext 启动与真实网络/音频路径需要独立真机验证。

## 本地证据

- 完整 Web 套件 210 项通过，其中指纹相关 66 项；真实 Worker 模块（注入浏览器 globals）校验损坏 SHA、错误来源/窗口/算法、坏 posting，并验证复用不再次 fetch、未准备或过期身份拒绝、PCM 清理。
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
