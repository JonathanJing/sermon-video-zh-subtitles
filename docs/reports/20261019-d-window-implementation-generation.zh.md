# D 窗口实现身份代记录：删除 23 个必须保留的门面

> 2026-10-19（洛杉矶日期）；只记录代码、身份与本地测试。三语付费复验（文字 QC、校准、音频 QC）在合并后另行运行，各有收据和运行报告；本文不是发布批准，`humanApproval=false` 不变。

## 依据与范围

- 用户决定（2026-10-19，原话）：「准备 D 批闭包窗口（先开草稿，一起合并），合并后授权在 post-G1 测试片段上做三语付费复验：文字预留上限每语约 $2.3，音频二级 ASR 每语不超过 $2.025」。
- 计划：[门面退出计划](../design/facade-removal-plan.zh.md) §3.3 与 §4 第 4 步。做法照 [G1 代记录](20261017-g1-implementation-generation.zh.md)：一个窗口一起合并，只重新校准一次。
- 删除的 23 个门面在 `origin/dev@cb99733c` 上用附录 A 重跑确认，A+B 批合并后在 `dev@a5bd24df` 上再跑一次：清单与计划 §3.3 相同（W 20 个，含与 T／计分／语速重叠的部分；预览 1 个；worker argv 3 个，其中 `sermon_workflow_jobs` 与 W 重叠）。删除后附录 A 在本分支得 `{'after': 165}`，必须保留为 0。
- 前置：[#1134](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/1134)（`tools/ops/run.py` 入口）与 [#1138](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/1138)（A+B 批）已合入 `dev@a5bd24df`。下面的“D 窗口”值在以它为基的 D 窗口代码 PR 分支头上计算；合并后按文末命令在真实 `dev` 上读回，值不同就以读回为准并补记。

## 入站基线不是 G1 的 W

G1 结束时 W 为 `df299eca0e9f`。[#1056](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/1056)（2026-10-19 19:10Z 合并）改了 `scripts/language_review_plugins/auto_qc_text_common.py`，它在 W 与语速闭包里，所以 D 窗口开始前 `dev` 的 W 已经是 `51e2b9cae580`，即 15030286 生产运行从冻结检出使用的那一代。下表的“入站”指 `dev@a5bd24df`（含 #1056、#1134、#1138；后两者不改四个身份和预览绑定）。

## 身份值

| 身份 | 入站 `dev@a5bd24df` | D 窗口 |
|---|---|---|
| W（`review.waiver.implementation_sha256`） | `51e2b9cae5804344684d11a52d7872ce84a4a434f4aea17adce9708c467c0d55` | `1c28f4aa38c05b9287db01cc8668995e10ba31c21d9d05fbaa508474a8a19961` |
| T（`compute.qc_audio_transports`） | `0c58ef32ea8005566fd350dfd2a1e3337ce163e2754cc497bdae3dfe8988a8c4` | `8ec15fe1556ba0ff5e3b64c9ff5d2f82896216f06bb2c25495385feaf4f5a851` |
| 计分（`audio.screening`） | `40bc41198d5f8c332061eae99eda0e9fa5f1be18c9901cca4b5bead5e6562689` | `9f2ff8077671b22a29d1846e30cdfb8c7c9999d30054bd67e7c4b50fa2c20310` |
| 语速（`audio.predicted_schedule.rate_implementation_sha256`） | `88cfb1d8aa030283c0c67b22afb4a5d8448b2a263868ecb3ed83a8dc303bb185` | `8f50c233e07bf130d569e15b91abeb35a231f26d18b3e3874b2c7de3581ed9f2` |
| 预览执行绑定 `previewExecutionBindingSha256` | `ca586cd70ffdd31a016c8ed007eb354aab63a35203831012095a3b4179b3d594` | `794bb5f1c7ac87bbddbd75b27633958835373b1d71c6c01a3b3355e7aa9c9de9` |
| `RENDERER_SOUND_IDENTITY_SHA256` | `fef7604882470137f46f1b01fbd06c7c3c9a07166da91003243608785fa47f0b` | `fef7604882470137f46f1b01fbd06c7c3c9a07166da91003243608785fa47f0b`（不变） |
| L2 `text.controller.code_identity()` | `3a22f8b23b1c5416cbbb5ef5701eaa4acf575637a5ad0700a393f9e23b6809dc` | `b00992e39d6fcc69ba5749c7366465e6cdf6c8c27fff1b4db0d2392c46913c58` |

物理清单：W 仍是 28 个逻辑键，物理文件 50 → 30；T 12 → 7，计分 9 → 8，语速 13 → 10。W 逐文件映射的规范 JSON 校验值 `a88e08308d35…` → `ac453ba815da1a731122f3c81ea96b6b14de9ab9f78901edd00dfff6c18339b0`。L2 代码身份的入站值已含 #1134、#1138 两次变化。

### 为什么变

- `path_aliases.physical_closure_paths()` 不再把已迁移键的 `scripts/` 门面路径放进闭包，只放 `resolve(key)` 指向的实现文件和解析器本身。逻辑键（`IMPLEMENTATION_FILES` 等）和它们的别名查找不变，冻结记录仍能用旧名找到新位置。
- `audio/renderer.py` 的 `preview_execution_binding_sha256()` 去掉门面 `scripts/render_speculative_target_language_speech.py` 一项，仍哈希 `audio/speculative.py`、`path_aliases.py`、`audio/hosted.py`、`audio/backend.py` 和 `scripts/tongxing_host.py`。
- 闭包内仍在的 9 个文件字节改变：`path_aliases.py`、`renderer.py`、`tongxing_host.py`、`ko_spoken_numerals.py` 有代码改动（见下）；`waiver.py`、`screening.py`、`qc_audio_transports.py`、`predicted_schedule.py`、`implementation_freeze.py` 只改注释，与入站版本的 AST（去掉文档字符串）逐一相同。

### 声音身份不变的证明

- `RENDERER_SOUND_IDENTITY_SHA256` 是 `audio/renderer.py` 里的常量，入站与 D 窗口相同（上表）。
- `renderer.py` 与入站版本相比，去掉 `preview_execution_binding_sha256` 函数后 AST 完全相同；另一处改动是一行注释。合成、单元指令、排程与 MP3 编码的代码没有改动。
- 预览缓存与正式复用随新的预览执行绑定失效（计划 §3.3 已写明）；声音语义身份不变，已渲染的声音按原规则判断复用。

## W 的逐文件物理字节

统计：21 个相同，9 个改变，20 个移出闭包（门面已删）。入站值来自 `dev@a5bd24df` 的 `implementation_freeze.file_hashes()`（与 `c03b9416` 逐文件相同），D 窗口值来自分支头。

| 仓库相对路径 | 入站物理 SHA-256 | D 窗口物理 SHA-256 | 结果 |
|---|---|---|---|
| `packages/production/src/tongxing_production/audio/backend.py` | `572115a3ee84444694987a9da2b7bec31cba0518df1f9a83cc1946f361d378e5` | `572115a3ee84444694987a9da2b7bec31cba0518df1f9a83cc1946f361d378e5` | 字节相同 |
| `packages/production/src/tongxing_production/audio/hosted.py` | `8101835f9897a1abe5be1eeadda4dcff9f49676b2bd4ce8ed36b79b4589ebc29` | `8101835f9897a1abe5be1eeadda4dcff9f49676b2bd4ce8ed36b79b4589ebc29` | 字节相同 |
| `packages/production/src/tongxing_production/audio/predicted_schedule.py` | `90411cd4f52f14131b142979f84894af7a0a007469bfb1e40aee4713f2dae334` | `287ae92bff58b5d6492f36d10e1cf4ada3c5f9933fc916b57d58b42d53e76fd6` | 字节改变 |
| `packages/production/src/tongxing_production/audio/renderer.py` | `44323070a68d412171cbfc01036b95c7eedee425d300fe0c7ea56396dba6b9e6` | `7ab4613e14802e890440b472c9196e00256cc71f4450107fdc9af8bded31fcb8` | 字节改变 |
| `packages/production/src/tongxing_production/audio/screening.py` | `872b48e40af43de343d0be86dce5142bc7e0bc554d479d6573c96b0284dd4347` | `e80bd3fc41be2a324d4310b4f10344e38d8c429b23923c6b7a0cbf542d929b44` | 字节改变 |
| `packages/production/src/tongxing_production/compute/openai_runtime.py` | `9b77113543b721e24e9f532bf9cfb23f9fe75f0582411155aab0c7a1b4620a0a` | `9b77113543b721e24e9f532bf9cfb23f9fe75f0582411155aab0c7a1b4620a0a` | 字节相同 |
| `packages/production/src/tongxing_production/compute/qc_audio_transports.py` | `b17d4adfacac74e2639b8da298e8d60d200fb78d9b5ac88ff5bd0ae43737a44c` | `0f681e26af0524b5d185fb69d19dcb12758c1b9d689d756072d36c693b3d7d8d` | 字节改变 |
| `packages/production/src/tongxing_production/compute/transcription_request.py` | `b7c73b648388414a290701bdb02b4da02b275e45ed197ca885d9ecafd0700471` | `b7c73b648388414a290701bdb02b4da02b275e45ed197ca885d9ecafd0700471` | 字节相同 |
| `packages/production/src/tongxing_production/orchestration/jobs.py` | `3d48ac09c6a6580daf98a5a86e8f8feede910039b3c03eda0107fd4ee2c07f15` | `3d48ac09c6a6580daf98a5a86e8f8feede910039b3c03eda0107fd4ee2c07f15` | 字节相同 |
| `packages/production/src/tongxing_production/path_aliases.py` | `1dc934a52e18e3ca290abd066d7f321237efec9fd997aa4a64ff761be1fabf3f` | `f96b722e627bb4792c6c2387f6bb3105408d017bb786d08b85361d269cc5d31a` | 字节改变 |
| `packages/production/src/tongxing_production/review/audio_qc.py` | `325ff8c949e0349fd3e30b0ad04e9560f36d9da5c334ed7adf442d7e33dd2b91` | `325ff8c949e0349fd3e30b0ad04e9560f36d9da5c334ed7adf442d7e33dd2b91` | 字节相同 |
| `packages/production/src/tongxing_production/review/backend.py` | `c3efeae0d156537a18588898c6673d3d365f83835ca96c68c07a6e12b71b3e6b` | `c3efeae0d156537a18588898c6673d3d365f83835ca96c68c07a6e12b71b3e6b` | 字节相同 |
| `packages/production/src/tongxing_production/review/condensation.py` | `9491d8a3fd8c1d5c70a4e210688565ece704ae16a36b2e59c8bed5d3d36cc486` | `9491d8a3fd8c1d5c70a4e210688565ece704ae16a36b2e59c8bed5d3d36cc486` | 字节相同 |
| `packages/production/src/tongxing_production/review/implementation_freeze.py` | `f647b110ee31806216e2667c66f835b21fdefe89a46377ee5516262406ebefb6` | `d81cd607570a7ed5304b68cd85d704c8b3eaf3a9df1489fd1f6bb5fe87cc577b` | 字节改变 |
| `packages/production/src/tongxing_production/review/qc_audio_run.py` | `44b39e2979f6ee5f987d4efd3761a85d643a6ce582a88cf3d48e7a6cf06f3b43` | `44b39e2979f6ee5f987d4efd3761a85d643a6ce582a88cf3d48e7a6cf06f3b43` | 字节相同 |
| `packages/production/src/tongxing_production/review/qc_budget_authorization.py` | `e8fbfe11f0037ac055d8502dd0f72bf0b57589f40c077f65308c7c6c3867745a` | `e8fbfe11f0037ac055d8502dd0f72bf0b57589f40c077f65308c7c6c3867745a` | 字节相同 |
| `packages/production/src/tongxing_production/review/qc_text_run.py` | `71dd800c0563bee936ee0f714e3fb13197d0e6ada940c86e5bbe0e8b99a07cad` | `71dd800c0563bee936ee0f714e3fb13197d0e6ada940c86e5bbe0e8b99a07cad` | 字节相同 |
| `packages/production/src/tongxing_production/review/release_basis.py` | `710f2c2666e6709ad033fe4358888418bbe366d66854332e099e5e733b9411e0` | `710f2c2666e6709ad033fe4358888418bbe366d66854332e099e5e733b9411e0` | 字节相同 |
| `packages/production/src/tongxing_production/review/repair_ledger.py` | `bb4bd1691196b93c007e391cf6f0b205a20ad2376a464bc3ca71060abdf0a8c0` | `bb4bd1691196b93c007e391cf6f0b205a20ad2376a464bc3ca71060abdf0a8c0` | 字节相同 |
| `packages/production/src/tongxing_production/review/seeded_errors.py` | `d8d11bafed281ef617f32c80974a9b160a894364cbdd6f2d9fac6f30cbb31cc7` | `d8d11bafed281ef617f32c80974a9b160a894364cbdd6f2d9fac6f30cbb31cc7` | 字节相同 |
| `packages/production/src/tongxing_production/review/text_qc.py` | `4097104c65f85f558bbc390a4f2d900981500bbeeaa0db0f12ac6986da902e9c` | `4097104c65f85f558bbc390a4f2d900981500bbeeaa0db0f12ac6986da902e9c` | 字节相同 |
| `packages/production/src/tongxing_production/review/unmoved.py` | `d5d7cc18f94c1eb51ec6b7765e97fa2b3d0beae76e835eaf71a048d0f83b4e22` | `d5d7cc18f94c1eb51ec6b7765e97fa2b3d0beae76e835eaf71a048d0f83b4e22` | 字节相同 |
| `packages/production/src/tongxing_production/review/waiver.py` | `e9d86121c8a2592823c6fc131f6eddf1d5151f062f2ab5f70bcebed19a1dd817` | `c19bbb53ad2884990ddaa65570b87d483ae29e2c5faf786c6f8cd078545e4e3e` | 字节改变 |
| `packages/production/src/tongxing_production/source/budget.py` | `560426b6aa364ecdd78c836fcc1aa29025e3fdfddaed7025fe41c0a2340d8f5b` | `560426b6aa364ecdd78c836fcc1aa29025e3fdfddaed7025fe41c0a2340d8f5b` | 字节相同 |
| `packages/production/src/tongxing_production/source/sentence_interpretation.py` | `5aa19b0580febb3652f9b694cf2ac9f1cbba1c241320c02396a99f0a63a439c1` | `5aa19b0580febb3652f9b694cf2ac9f1cbba1c241320c02396a99f0a63a439c1` | 字节相同 |
| `packages/production/src/tongxing_production/storage/files.py` | `c497b0a81bd7e5787cb34df6536ce9d3e7c1269b59c584b59fc078cbf674ea80` | `c497b0a81bd7e5787cb34df6536ce9d3e7c1269b59c584b59fc078cbf674ea80` | 字节相同 |
| `scripts/auto_qc_seeded_errors.py` | `e955cc373331dda5a2645664d6f0d668a12ebb8b43cc180332fefb551da5fb4e` | — | 移出闭包（门面已删） |
| `scripts/implementation_freeze.py` | `7c1edea310360b13256cb494c79b69df712c794d7d2a01f2a488eb82b605796b` | — | 移出闭包（门面已删） |
| `scripts/ko_spoken_numerals.py` | `f68f6e6a05fb756d16a89ce3161c34f0b2561fcd835232d6be8897bf5765f5bb` | `e31f5b24cf3a05d33821ec67a0a52bdc1da0e73329352b22b526c228eb1c9187` | 字节改变 |
| `scripts/language_review_plugins/auto_qc_text_common.py` | `0766409a9688f83b0af666e730b3ce389c068d351082f54df1af166f1822699c` | `0766409a9688f83b0af666e730b3ce389c068d351082f54df1af166f1822699c` | 字节相同 |
| `scripts/language_review_plugins/common.py` | `bed66c6245610450b27874e39c47eed32fbc757abf94d199fe9d476fdf5d68ea` | `bed66c6245610450b27874e39c47eed32fbc757abf94d199fe9d476fdf5d68ea` | 字节相同 |
| `scripts/machine_qc_audio_transports.py` | `d72bedf445bde7539435b199900532a6f1817223c64214099b05e60d54494e76` | — | 移出闭包（门面已删） |
| `scripts/machine_qc_budget_authorization.py` | `51e62b9e4048555d6aafa6f8ccd498fa2a27676ac8c1db1429ad7aaa466073ca` | — | 移出闭包（门面已删） |
| `scripts/machine_quality_release_basis.py` | `3e23a02408af326f6c0b49568b4b43edcbd77189556671605ec67447a07f8ab7` | — | 移出闭包（门面已删） |
| `scripts/machine_quality_waiver.py` | `19f964290f9267bc2284a8c2d6058c19b15519c39c66564b376278668f4f3871` | — | 移出闭包（门面已删） |
| `scripts/machine_repair_ledger.py` | `cf97581b376649ff98ab84a59df517991431036a840c37c95d70515aa3717727` | — | 移出闭包（门面已删） |
| `scripts/render_formal_target_language_speech.py` | `e8220e66083b0d557d394def9ec1639131ead5469b805a5ab5391d6c39031a32` | — | 移出闭包（门面已删） |
| `scripts/run_machine_qc_audio_test.py` | `9302098ba166358ddd2c81ced422e9ebf5e098cc3db52f0fc5057928e9fdba3d` | — | 移出闭包（门面已删） |
| `scripts/run_machine_qc_clip_test.py` | `a521b9ae55b26cd2b423c0a44983d775840e6477c844ae523f7d1b6c85f1736f` | — | 移出闭包（门面已删） |
| `scripts/screen_target_language_audio_units.py` | `b1926922da8e2a99c49eea33810354d445dd5f0d42a4f9ed6bd48c6b348c3f73` | — | 移出闭包（门面已删） |
| `scripts/sermon_openai_runtime.py` | `90f7444edf8c8318861119fe851d1a553e35e4a378a4ef23c79878ace4034fdc` | — | 移出闭包（门面已删） |
| `scripts/sermon_sentence_interpretation.py` | `a086e253fdb63212c43c3123959c15f16b8cfc12d5733a41a282bcd4afb983e6` | — | 移出闭包（门面已删） |
| `scripts/sermon_source_budget.py` | `3535ce654bf43a1f65432d902309d6d1e19fc5ab99f4b23177b5435004272d2f` | — | 移出闭包（门面已删） |
| `scripts/sermon_transcription_request.py` | `166f7804f586be1102347ab7ce6d3127e24985281a551982096e9016ab681852` | — | 移出闭包（门面已删） |
| `scripts/sermon_workflow_jobs.py` | `48c2300f8e2b417a0bd7d0f20036ff5df0b25e0dcec28b38e90760e3300c5b30` | — | 移出闭包（门面已删） |
| `scripts/spoken_condensation.py` | `f196e323cb08418825f7dda13f85f1a1ab8aa95f8f3a0a7c462b6e9f4cd421d9` | — | 移出闭包（门面已删） |
| `scripts/target_audio_auto_qc.py` | `d85ac8c8b77fbf9ea8fe4aad5ac9b1f2c989acced5be50ee01ed5f92a9f3b7f0` | — | 移出闭包（门面已删） |
| `scripts/target_audio_predicted_schedule.py` | `b88df58718f4095866e6b747261e2837b8ee967bd111c305ed900431e1e7ac84` | — | 移出闭包（门面已删） |
| `scripts/target_text_auto_qc.py` | `4146b2f6dcef36f633479e01bee115116c83d77dd8dffb9b9cbbe6cbb5bd6519` | — | 移出闭包（门面已删） |
| `scripts/tongxing_host.py` | `8748785b02fac434a5379f872ce3186b96f03dc41a5aaf0db0991153d87f6dd7` | `8f69b29d53405e9fa6544dfb303c0eadfcf6369faea94c85ade2edd04391e18f` | 字节改变 |

T 移出：`scripts/machine_qc_audio_transports.py`、`scripts/machine_qc_budget_authorization.py`、`scripts/sermon_source_budget.py`、`scripts/sermon_transcription_request.py`、`scripts/sermon_workflow_jobs.py`。计分移出：`scripts/screen_target_language_audio_units.py`。语速移出：`scripts/render_formal_target_language_speech.py`、`scripts/sermon_sentence_interpretation.py`、`scripts/target_audio_predicted_schedule.py`。三者都没有新增路径。

## 其他绑定的变化

- **durable worker argv。** `scripts/tongxing_host.py` 的三个 `worker_command` 改为 `[python, tools/ops/run.py, text.controller | delivery.app_workflow | orchestration.jobs, …]`。旧 argv 记录的 job 不再与新请求逐字节相等；`reopen-repair` 按宿主当前前缀取参数位置，旧 argv 的失败 job 会以 `original_execution_binding_changed` 拒绝，不在同一 job root 混用新旧 argv。
- **Spark 容器命令。** `scripts/clip_e2e_spark.py` 的 render、screen、audio-qc 改为 `{code}/tools/ops/run.py audio.renderer | audio.screening | review.qc_audio_run`，挂载、环境和镜像不变；started 标记的 `commandSha256` 随之改变。`spark_exclusive_session.process_role()` 把 `run.py audio.renderer` 仍识别为 worker。
- **Layer 1 producer compatibility v11。** `scripts/sermon_diagnostic_context.py` 与 `scripts/sermon_fresh_diagnostic_source.py` 只把锚点生成器的导入从已删门面改为 `tongxing_production.source.sentence_interpretation`（同一模块对象）。新增精确迁移 `d-window-closure-facade-removal-v11`：历史侧等于 v10 当前表，只这两个文件变，只读复用原 Source，零新 ASR/MFA，`productionEligible=false`。
- **执行身份。** `EAGER_PRODUCER_IMPORTS` 与 `sermon_fresh_diagnostic.preload_execution_modules` 改用包内模块名；`loadedProjectCodeSha256` 按模块文件记录，加载的文件集合不变。

## 需要重新校准的语言

在主检出 `artifacts/` 里按完整哈希检索（只读）：

- **入站 W `51e2b9cae580`：** 15030286 生产运行的 text-qc 与 audio-qc（es、ko、zh-Hans）。es、ko 已发布；zh-Hans 有 `prepared-zh-v1`，未见 prod 发布产物。该运行按冻结检出续跑，不在当前 `dev` 上续跑，所以不受本窗口影响；若改在 `dev` 上续跑 zh-Hans，需要按新 W 重新校准。同一运行的 TTS render 记录绑定 T `0c58ef32ea80`，规则相同。
- **G1 的 W `df299eca0e9f`：** 只有 post-G1 测试片段 `artifacts/opus-e2e-dev216-20261014-g/post-g1-qc-20261017`（es、ko、zh-Hans）及其计划。#1056 合并时它们已经与 `dev` 不符；本窗口合并后的付费复验就在这个片段上对三语重新校准。
- **预览执行绑定 `ca586cd70ffd`：** `artifacts/local-runs/20261019-grp005-*` 两个 A/B 实验目录。实验已结束；它们的预览缓存不再能复用。
- 入站计分 `40bc41198d5f` 与语速 `88cfb1d8aa03` 只出现在 15030286 运行里（同上）。

## 验证

本地（CI 自 2026-10-19 关闭）：完整 unittest 十个分片、pytest 风格文件、§5.5 测试 ID 清单、`git diff --check`、15 个包内命令的 `--help` 与旧门面对比。结果见[运行报告 #1145](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/1145)：十个分片 5980 个用例中 1 个失败，是 `test_layer2_large_fan_in` 在高负载下的时钟不连续诊断，单独重跑两次通过，此前两次完整运行也通过；pytest 风格 1110 通过，1 个失败在干净 `dev` 上同样失败；测试 ID 5982 → 5979（6 个改名、3 个门面同一性测试删除、新增 v11 测试 1 个）。这仍是代码测试，不是三语真实校准。

## 合并后读回

```bash
.venv/bin/python -c "from scripts import tongxing_host; from tongxing_production.review import waiver; from tongxing_production.compute import qc_audio_transports as t; from tongxing_production.audio import screening, predicted_schedule as p, renderer as r; from tongxing_production.text import controller as c; print(waiver.implementation_sha256(), t.implementation_sha256(), screening.implementation_sha256(), p.rate_implementation_sha256(), r.preview_execution_binding_sha256(), r.RENDERER_SOUND_IDENTITY_SHA256, c.code_identity())"
```
