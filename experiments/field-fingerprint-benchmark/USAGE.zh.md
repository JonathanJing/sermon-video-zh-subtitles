# FIELD-09：离线声学基准的输入与测量工具

本目录只交付 **manifest + 本地离线测量 runner**。默认示例是合成信号，用于验证工具合同；没有真实录音成绩，也没有远场、Safari、iOS、最低设备或现场通过声明。报告永远 `promotionAllowed: false`。

背景：[冻结数值合同](../../docs/field-fingerprint-contract-baseline.zh.md) 与 [FIELD-09 待验收项](../../docs/field-fingerprint-alignment-backlog.zh.md)。已有 12 个 JS/Swift golden 是确定性数值合同，不能算本基准的独立声学样本。本工具只读复用 [production DSP](../sermon-dubbing-poc/web/fingerprint-core.mjs)，不改 matcher、阈值、麦克风、控制器或 golden。

## 1. 无素材、无网络的工具自检

需要 Python 3.10+、项目已有依赖 `jsonschema` 和 Node 20+。不安装模型或转码器；本目录不会请求网络、调用供应商、录音、上传或发布。

从仓库根目录执行：

```sh
python3 -m unittest discover -s experiments/field-fingerprint-benchmark -p 'test_*.py' -v
node apps/tongxing-ios/scripts/generate-published-fingerprint-golden.mjs --check
```

生成一次性本地合成数据和报告（新目录与新报告路径必须不存在）：

```sh
WORK=$(mktemp -d)
node experiments/field-fingerprint-benchmark/make_synthetic_fixture.mjs "$WORK/data"
python3 experiments/field-fingerprint-benchmark/run_benchmark.py \
  --manifest "$WORK/data/manifest.json" \
  --data-root "$WORK/data" \
  --report "$WORK/report.json"
```

生成器写出两份不同合成源、两个不相交 split，各有一个匹配和一个静音拒绝。source index 时间原点为 10 秒，查询真值为源录音 20 秒，刻意覆盖非零原点换算。PCM 和 index 仅在临时目录；不要提交生成内容。任何成功率数字都是这四个人造测试窗口的结果，不能作为声学效果比较。

现有 CI 没有自动发现本目录的 unittest；本次未改共享 CI。上述专用测试必须单独执行，现有 CI 绿色不替代它。

## 2. Manifest 合同和分组

[JSON Schema](../../schemas/sermon-field-benchmark-manifest-v1.schema.json) 是输入形状合同；runner 另外检查跨对象引用和 split 约束。拒绝未知字段、重复 JSON key、NaN/Infinity、重复 ID、未被 case 使用的源/会话以及仅有一个 split 的清单。输入上限 8 MiB、10,000 cases；没有自动发现目录或筛选“容易成功”的样本。

- `datasetKind`：`synthetic_only` 或 `authorized_recordings`。真实素材必须已经获得本地使用授权；设置字段不是征得录音/上传同意的流程
- `protocol`：实验前冻结的 `frozenAt`、定位容差（仅评分，**不改变匹配门槛**）与每例进程截止时间。报告绑定 manifest 原始字节 SHA-256；修改任一项就成为不同版本
- `sources[]`：`id` 指一份完整源录音，`familyId` 把同源的转码、剪辑等变体归到同一家族；`split` 为 `dev` / `holdout`。`recording` 必须给本地文件相对路径和 SHA-256。被用于 target 的 source 必須有 `index`；仅用作负例查询来源的 source 可以没有 index
- `sessions[]`：`id` 是本地 capture 文件记录；`captureSessionId` 是整次录制会话，不能因切片、重命名、换文件或多个源片段而改变。文件仍可按源拆分为多个记录，但所有记录须保留同一 `captureSessionId`。`sourceRecordingId` 记录查询来源，`recording` 绑定完整本地 capture 文件。每一会话还声明授权、粗粒度平台/系统版本、设备层级、route、声音条件
- `cases[]`：引用 capture 记录和目标 source。`captureStartSeconds` 和 `durationSeconds` 是 capture 文件窗口；正例 `expected.sourceStartSeconds` 是**完整源录音的绝对时间**，负例只有 `expected.kind: negative`。正例必须是同一 source 记录，负例可为无关源或不支持的变速/剪辑等

源家族、任何角色的相同文件 SHA、相同资产路径、整次 capture 会话均不能跨 split；case 的 target、查询来源及 capture 文件必须属于同一个 split。不同 split 的真实独立静音录音若碰巧字节完全相同也会保守拒绝，不要靠改 SHA 绕过。多个窗口只增加 `caseCount`；另列完整源、源家族、capture 文件和录制会话数量，`independentAcousticSampleCount` 永远为空。

人为错标家族/会话、把裁剪片段冒充完整源、从已看过的 holdout 重新挑窗口，不能单靠 hash 检出。数据维护者必须从原始来源和采集记录确认分组，并在首次评估前冻结案例、真值、容差和截止时间。工具记录冻结声明与哈希，**不证明预注册或盲测已经发生**；不得依据本报告反复调参再称同一 holdout 为未见数据。

## 3. 允许的本地资产与来源绑定

`--data-root` 是已授权素材所在本地目录。所有 manifest 路径必须相对于它，不接受 URL、绝对路径、`..` 或反斜线；解析符号链接后仍须留在该目录。只读取普通文件，不执行素材。源/capture 文件上限各 512 MiB，index 32 MiB；每例都重新读取并校验实际字节 SHA，避免跨例复用陈旧的 hash 结论。

- source 原文件只用于来源 hash，格式不限；工具不会转码/下载它
- capture 只支持 **RIFF/WAVE、PCM16、mono、4–192 kHz**，窗口需落在完整文件内并对齐到样本边界。其他格式保留为失败；不会偷偷转换输入
- target index 必须是 `sermon-landmark-index-v1` / `spectral-landmarks-v1`，8 kHz / hop 256 / FFT 1024，并有 `sourceSha256`、`sourceStartSeconds`、`sourceEndSeconds`、`durationSeconds` 和合法 postings。`sourceSha256` 必须与实际 source 文件一致；index 文件本身也须通过 SHA
- index 的相对定位加 `sourceStartSeconds` 得到完整源时间。正例真值窗口必须在 index 覆盖内；runner 不把负例真值塞给 matcher
- index hash 与来源字段匹配是身份绑定，不能独立证明制作者没有写错 index 内容或人工真值。工具不生成生产 index、不修改发布 page/track 绑定，也不验证页面发布权限

真实素材清单与报告必须留在受控本地目录，使用无身份含义的 `id` / `familyId` / `captureSessionId`；不要放姓名、地点、设备 ID、蓝牙名称、逐字稿或秘密。生成器也不构成开始收集真实录音的授权。

## 4. 全量保留、超时及指标口径

每个已通过清单验证的 case 都输出一行：`accepted` / `rejected` / `failed` / `timeout`。坏哈希、缺文件、坏 WAV、进程错误等不被排除，且仍计入分母。清单本身错误会在运行前拒绝，不产生可解释为有效测量的报告。

每例是独立 Node 子进程，截止时间包含启动、读取/校验、解码窗口和 DSP；超时终止并回收该进程，再执行下一例。没有重试至命中的选择偏差。超时观测标记 `timeoutRightCensored`：它是终止前耗时，不是成功完成耗时。机器调度/终止开销可能使 wall time 略超过配置预算。

按 `dev` / `holdout` 分开汇总，另按平台来源、系统版本、设备层级、route、条件交叉分层：

- `positiveCorrectWithinTolerance`：误差在预设容差内的已接受正例 / **全部计划正例**；拒绝、失败、超时仍在分母
- `positiveAcceptedOutsideTolerance`：接受但定位错误的正例 / 全部计划正例；`observedWrongJumpAllPlanned` 另计它们加负例误接受 / 全部计划例
- `negativeFalseAcceptAllPlanned`：负例误接受 / 全部计划负例，同时给 `negativeFalseAcceptObserved`（分母只含已完成接受/拒绝）与 `negativeUnresolvedCount`。失败/超时不是正确拒绝；未解决例存在时，前一比率不能解释为完整误跳风险
- `negativeCorrectRejectionAllPlanned`：正确拒绝 / 全部计划负例
- `positiveAcceptedAbsoluteLocalizationErrorSeconds`：仅已接受正例的绝对定位误差 P50/P95，**包括错误定位**；逐例同时保留有符号误差
- `caseWallMsAllPlanned`：全部例的 wall time P50/P95，另给按 outcome 分布；`dspMsCompletedOnly` 明确只覆盖完成 DSP 的例。每个分布带 count，空集合及零分母使用 `null`

分位数统一 nearest-rank（排序后第 ceil(p×N) 个），不插值。计时是此离线 Node 主机的测量，含文件验证与冷进程开销；它不是 Safari/iOS 端到端性能、首次/二次命中、采音占麦时间、可听输出、字幕误差或峰值内存。这些状态均 `not_run`，即使 capture 来源标签写 `web_safari` 或 `ios_native`。

窗口有源/会话相关性，因此不从窗口数捏造独立试验置信区间；当前明确 `not_estimated_clustered_windows_are_not_independent`。零次观测误跳不代表真实误跳率为零。P0 门槛、真实最小设备、独立正负例数量和按源/会话的统计推断仍待后续授权实验。

## 5. 报告、退出码和隐私

报告绑定 manifest/schema、runner、worker、production DSP 的 SHA-256，以及逐例预期 source/index/capture SHA。只有输入已完成验证的例才有 `inputVerification: verified`；未解决例为 `incomplete`，预期 hash 不冒充已验证实际字节。代码在运行期间变更会拒绝有效报告。

输出采用新建独占文件，权限 `0600`，不覆盖旧证据；父目录需已存在。报告逐例只输出白名单字段，不输出原始音频、现场 landmark、路径、原始异常/子进程 stderr。ID 和 hash 仍可能关联私人素材，报告默认仅本地；导出/上传/分享需要另行授权。输入访问错误只显示固定原因码。

- `0`：所有例完成测量（**不表示全匹配或质量达标**）
- `1`：报告完整写出，但存在失败/超时，必须按报告保留全部例解释
- `2`：清单、路径、报告创建或工具完整性错误；不可作为有效测量

新 runner 和源 hash 检查可在 Linux 验证。当前没有运行 Swift、Xcode、iOS 模拟器、Safari 或真机，不能借用历史 golden 的 Swift 结果声称本次通过。这一批只准备未来经授权真实录音的测量入口，FIELD-09 声学资格仍待证据。
