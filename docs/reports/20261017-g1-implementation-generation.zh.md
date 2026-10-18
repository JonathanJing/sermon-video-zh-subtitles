# G1 实现身份代记录：最终 dev 读回

> 2026-10-17（洛杉矶日期）；仅记录代码合并、身份与测试。真实三语校准、签发、发布和设备验收仍须各自的收据。

## 合并与读回

- 入站基线 `dev@b6f62160194c9a4fdac52dd6133f306bbaa49b20`，底部三批合并后 `dev@fcc05e730e7835b508ff00ca516f21f4c02c3866`。
- [#568](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/568) → `36539d04a326135123c195fe66eb14f8399f7793`；[#569](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/569) → `32159e717ada3d7295735c858301c57ce0c50955`；[#570](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/570) → `fcc05e730e7835b508ff00ca516f21f4c02c3866`。
- [#579](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/579) → `9a35b20ec00626364228fcb7ba3d42e3bf4705e6`；[#588](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/588) → `44cad83e7280ec0dcd1aa04a56709b345c9735f1`；[#582](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/582) → `974862e6b85d7fa581240a6fa84f74da806f2391`。各 PR 头提交均已在远端 `dev` 读回为祖先。
- 最终真实检出 `dev@974862e6b85d7fa581240a6fa84f74da806f2391`；主工作区用户分支未用于计算这些值。

## 四个身份值

以下由各阶段实际 `dev` 检出的入口计算，按 W、传输 T、筛查计分、语速顺序给出完整 SHA-256。阶段间的数值变化属于同一 G1 合并窗口；没有在中间阶段重新校准或签发。

### 入站基线 `b6f62160194c`

- W：`acbe525679820292bdb3a3028006a4daa2e1e47b5408b1379aa3c217cbe2b125`
- T：`27025236239627f6d9917f275db1af821d0bae09842502dec307e2e9317bf9d0`
- 计分：`cb123c807a0306e34fd6143935bd1c1f0df5b9759ef00b0fa51a3953354f6458`
- 语速：`2e8ad1a69c4c9735b44b120d6476fedd304f402a4be0572543bcf9034ded4a66`

### 底部三批后 `fcc05e730e78`

- W：`ecd6e7405279b334ecdeccad103f7e563f30c4e00a1896d098622c39b9c218ae`
- T：`762d934f7ca35f993e22c96ad63e0c1ec699ed8e4d220dcc9f77bd4f6f86abe1`
- 计分：`c83db9e88b3c9652e973abb417939ca8c0b201cc5ad3d59e989582c39d027e25`
- 语速：`59682d0dd1af5970c338ba0183ae70121a64755897afe165c418b0d943174380`

### R3 后 `9a35b20ec006`

- W：`a428a06131f928ab5169b20f22ad725ef2e4e109347c38bc738731378dd9c57e`
- T：`5332f5e907835f5df0b2ddc3178d992ed2f6d0c260ee42f6b96f1ac0d60929b7`
- 计分：`1ca699549066a982a29b30533425ece680072443611f1661c2a984a322e6d86b`
- 语速：`8fedf68ebd3bec728a41f95fb403c6f0b7404ac009a3131fd71098a4c20e0126`

### A4 后 `44cad83e7280`

- W：`bee5a1f8fc0f80ba6613dbdf6fc87fcb5adf8079c45cca5ee7d0b5c34762369c`
- T：`db9e2350b92865531266f82b20ac07e96734d70af760ed15f32720afceaff9b9`
- 计分：`65723cc8d98b21062dfec906e55c744a457dbbfe2e9e6bbc2f6d3ab0645097f2`
- 语速：`9181b6099ce13b8ad3b558fe28e2f779aeabdc8e3ea88a00c8ef23c3fc7b4af2`

### R4 后最终 `974862e6b85d`

- W：`df299eca0e9f11689e7a88654b7b2616df1e10bd8cd60a9847e3561d5db41b10`
- T：`0c58ef32ea8005566fd350dfd2a1e3337ce163e2754cc497bdae3dfe8988a8c4`
- 计分：`38c7433cc876c09d013003671fba6014ff2f398fd46789c2d6994ca9a787d282`
- 语速：`38528da1ed21007b544ff00ea091de5b8853574ded04d38c8488c3e753bf4c4d`

最终 W 保留 28 个逻辑 `IMPLEMENTATION_FILES` 键，物理冻结清单为 50 个仓库相对路径；T／计分／语速分别覆盖 12／9／13 个物理路径。最终预览执行绑定 `previewExecutionBindingSha256` 为 `f4794a87a35ca9b4c8fd05b63722e356ca3dacf89c9a147764f5463b834296df`。W 的逐文件映射按路径与 SHA-256 的规范 JSON 计算校验值为 `905c74fc6ce900330feb9a4491defe7414177ff21bed136254e542c03fb6a63c`。

## W 的逐文件物理字节

下表的「入站物理 SHA」直接读取 `dev@b6f62160194c` 中该路径的 Git blob；「最终物理 SHA」来自 `dev@974862e6b85d` 的 `implementation_freeze.file_hashes()`。旧实现的 22 个 `file_hashes` 键是逻辑键，部分会解析到包内目标，因此**不能把旧键名下的哈希误称为同名旧脚本的物理字节**。下表统一按真实路径比较。

统计：16 个路径入站不存在、19 个改变、15 个相同；最终总计 50 个。入站 W 绑定的是 22 个逻辑键，最终 W 绑定上述 50 个实际文件；一个路径在入站存在，不表示当时受旧 W 保护。

| 仓库相对路径 | 入站物理 SHA-256 | 最终物理 SHA-256 | 结果 |
|---|---|---|---|
| `packages/production/src/tongxing_production/audio/backend.py` | `572115a3ee84444694987a9da2b7bec31cba0518df1f9a83cc1946f361d378e5` | `572115a3ee84444694987a9da2b7bec31cba0518df1f9a83cc1946f361d378e5` | 字节相同 |
| `packages/production/src/tongxing_production/audio/hosted.py` | — | `8101835f9897a1abe5be1eeadda4dcff9f49676b2bd4ce8ed36b79b4589ebc29` | 基线无此路径 |
| `packages/production/src/tongxing_production/audio/predicted_schedule.py` | — | `90411cd4f52f14131b142979f84894af7a0a007469bfb1e40aee4713f2dae334` | 基线无此路径 |
| `packages/production/src/tongxing_production/audio/renderer.py` | — | `44323070a68d412171cbfc01036b95c7eedee425d300fe0c7ea56396dba6b9e6` | 基线无此路径 |
| `packages/production/src/tongxing_production/audio/screening.py` | — | `872b48e40af43de343d0be86dce5142bc7e0bc554d479d6573c96b0284dd4347` | 基线无此路径 |
| `packages/production/src/tongxing_production/compute/openai_runtime.py` | `9b77113543b721e24e9f532bf9cfb23f9fe75f0582411155aab0c7a1b4620a0a` | `9b77113543b721e24e9f532bf9cfb23f9fe75f0582411155aab0c7a1b4620a0a` | 字节相同 |
| `packages/production/src/tongxing_production/compute/qc_audio_transports.py` | — | `b17d4adfacac74e2639b8da298e8d60d200fb78d9b5ac88ff5bd0ae43737a44c` | 基线无此路径 |
| `packages/production/src/tongxing_production/compute/transcription_request.py` | `b7c73b648388414a290701bdb02b4da02b275e45ed197ca885d9ecafd0700471` | `b7c73b648388414a290701bdb02b4da02b275e45ed197ca885d9ecafd0700471` | 字节相同 |
| `packages/production/src/tongxing_production/orchestration/jobs.py` | — | `3d48ac09c6a6580daf98a5a86e8f8feede910039b3c03eda0107fd4ee2c07f15` | 基线无此路径 |
| `packages/production/src/tongxing_production/path_aliases.py` | `79faea0ff957f2511ddd8840e69265edf4c2ab1cb755d29d368f8880824295bd` | `1dc934a52e18e3ca290abd066d7f321237efec9fd997aa4a64ff761be1fabf3f` | 字节改变 |
| `packages/production/src/tongxing_production/review/audio_qc.py` | — | `325ff8c949e0349fd3e30b0ad04e9560f36d9da5c334ed7adf442d7e33dd2b91` | 基线无此路径 |
| `packages/production/src/tongxing_production/review/backend.py` | `c3efeae0d156537a18588898c6673d3d365f83835ca96c68c07a6e12b71b3e6b` | `c3efeae0d156537a18588898c6673d3d365f83835ca96c68c07a6e12b71b3e6b` | 字节相同 |
| `packages/production/src/tongxing_production/review/condensation.py` | — | `9491d8a3fd8c1d5c70a4e210688565ece704ae16a36b2e59c8bed5d3d36cc486` | 基线无此路径 |
| `packages/production/src/tongxing_production/review/implementation_freeze.py` | — | `f647b110ee31806216e2667c66f835b21fdefe89a46377ee5516262406ebefb6` | 基线无此路径 |
| `packages/production/src/tongxing_production/review/qc_audio_run.py` | — | `44b39e2979f6ee5f987d4efd3761a85d643a6ce582a88cf3d48e7a6cf06f3b43` | 基线无此路径 |
| `packages/production/src/tongxing_production/review/qc_budget_authorization.py` | — | `e8fbfe11f0037ac055d8502dd0f72bf0b57589f40c077f65308c7c6c3867745a` | 基线无此路径 |
| `packages/production/src/tongxing_production/review/qc_text_run.py` | — | `71dd800c0563bee936ee0f714e3fb13197d0e6ada940c86e5bbe0e8b99a07cad` | 基线无此路径 |
| `packages/production/src/tongxing_production/review/release_basis.py` | — | `710f2c2666e6709ad033fe4358888418bbe366d66854332e099e5e733b9411e0` | 基线无此路径 |
| `packages/production/src/tongxing_production/review/repair_ledger.py` | `bb4bd1691196b93c007e391cf6f0b205a20ad2376a464bc3ca71060abdf0a8c0` | `bb4bd1691196b93c007e391cf6f0b205a20ad2376a464bc3ca71060abdf0a8c0` | 字节相同 |
| `packages/production/src/tongxing_production/review/seeded_errors.py` | — | `d8d11bafed281ef617f32c80974a9b160a894364cbdd6f2d9fac6f30cbb31cc7` | 基线无此路径 |
| `packages/production/src/tongxing_production/review/text_qc.py` | — | `4097104c65f85f558bbc390a4f2d900981500bbeeaa0db0f12ac6986da902e9c` | 基线无此路径 |
| `packages/production/src/tongxing_production/review/unmoved.py` | `b4df2c856bb2beeb7cf277cba36698a6a9f3cf9d91e4d9f7040a58b39ea5e28b` | `d5d7cc18f94c1eb51ec6b7765e97fa2b3d0beae76e835eaf71a048d0f83b4e22` | 字节改变 |
| `packages/production/src/tongxing_production/review/waiver.py` | — | `e9d86121c8a2592823c6fc131f6eddf1d5151f062f2ab5f70bcebed19a1dd817` | 基线无此路径 |
| `packages/production/src/tongxing_production/source/budget.py` | `560426b6aa364ecdd78c836fcc1aa29025e3fdfddaed7025fe41c0a2340d8f5b` | `560426b6aa364ecdd78c836fcc1aa29025e3fdfddaed7025fe41c0a2340d8f5b` | 字节相同 |
| `packages/production/src/tongxing_production/source/sentence_interpretation.py` | `5aa19b0580febb3652f9b694cf2ac9f1cbba1c241320c02396a99f0a63a439c1` | `5aa19b0580febb3652f9b694cf2ac9f1cbba1c241320c02396a99f0a63a439c1` | 字节相同 |
| `packages/production/src/tongxing_production/storage/files.py` | `9005638d609b9c52f555533ca25021489cb166d76d132b267a720606ad8854ee` | `c497b0a81bd7e5787cb34df6536ce9d3e7c1269b59c584b59fc078cbf674ea80` | 字节改变 |
| `scripts/auto_qc_seeded_errors.py` | `a08d0489b3c776189cff9a2821d3cf377a382337f5dbcf8e4b5acb05f9965dfa` | `e955cc373331dda5a2645664d6f0d668a12ebb8b43cc180332fefb551da5fb4e` | 字节改变 |
| `scripts/implementation_freeze.py` | `153871c66a3c8a6bcfc4b183af52ff1403788d45ee02868851652715c076e627` | `7c1edea310360b13256cb494c79b69df712c794d7d2a01f2a488eb82b605796b` | 字节改变 |
| `scripts/ko_spoken_numerals.py` | `f68f6e6a05fb756d16a89ce3161c34f0b2561fcd835232d6be8897bf5765f5bb` | `f68f6e6a05fb756d16a89ce3161c34f0b2561fcd835232d6be8897bf5765f5bb` | 字节相同 |
| `scripts/language_review_plugins/auto_qc_text_common.py` | `fe18e7266e7ba67f84960173021a18e22009a44c85f3b7e802d9d681ab51064d` | `fe18e7266e7ba67f84960173021a18e22009a44c85f3b7e802d9d681ab51064d` | 字节相同 |
| `scripts/language_review_plugins/common.py` | `bed66c6245610450b27874e39c47eed32fbc757abf94d199fe9d476fdf5d68ea` | `bed66c6245610450b27874e39c47eed32fbc757abf94d199fe9d476fdf5d68ea` | 字节相同 |
| `scripts/machine_qc_audio_transports.py` | `ee2cc4fbf4508443026e04a37a15d89e77e460405cf95651bbcd74e2e98032e6` | `d72bedf445bde7539435b199900532a6f1817223c64214099b05e60d54494e76` | 字节改变 |
| `scripts/machine_qc_budget_authorization.py` | `43c27b28f8c2291a5ac2bf7765ea67b4254a0b7ea33f4da0bbb92fa0c5be85bb` | `51e62b9e4048555d6aafa6f8ccd498fa2a27676ac8c1db1429ad7aaa466073ca` | 字节改变 |
| `scripts/machine_quality_release_basis.py` | `410988d188c495c69f8648f9467135d8038c25643137d61d01ad0c4ef7af8fc9` | `3e23a02408af326f6c0b49568b4b43edcbd77189556671605ec67447a07f8ab7` | 字节改变 |
| `scripts/machine_quality_waiver.py` | `da800566dd0c4a00349067f8e6c009460051ec5d651547cd1e0ba8999ad3f36b` | `19f964290f9267bc2284a8c2d6058c19b15519c39c66564b376278668f4f3871` | 字节改变 |
| `scripts/machine_repair_ledger.py` | `cf97581b376649ff98ab84a59df517991431036a840c37c95d70515aa3717727` | `cf97581b376649ff98ab84a59df517991431036a840c37c95d70515aa3717727` | 字节相同 |
| `scripts/render_formal_target_language_speech.py` | `55fb124180fa6f19d915b93fb660b39dc4899eddcad9a8a645b599bc56657e55` | `e8220e66083b0d557d394def9ec1639131ead5469b805a5ab5391d6c39031a32` | 字节改变 |
| `scripts/run_machine_qc_audio_test.py` | `5ab0db4954e170cb19080bbf91db7d4d2065dbe37e5a212037d8c628a467397b` | `9302098ba166358ddd2c81ced422e9ebf5e098cc3db52f0fc5057928e9fdba3d` | 字节改变 |
| `scripts/run_machine_qc_clip_test.py` | `4b4bf227c0e051fce8de158fdcbb3611d2ea5759756c16c3eb6408c1a7a24b6a` | `a521b9ae55b26cd2b423c0a44983d775840e6477c844ae523f7d1b6c85f1736f` | 字节改变 |
| `scripts/screen_target_language_audio_units.py` | `8005f9e3ee5b20c81ca0636fd24c38c29300cb128e25a84576703d887423f154` | `b1926922da8e2a99c49eea33810354d445dd5f0d42a4f9ed6bd48c6b348c3f73` | 字节改变 |
| `scripts/sermon_openai_runtime.py` | `90f7444edf8c8318861119fe851d1a553e35e4a378a4ef23c79878ace4034fdc` | `90f7444edf8c8318861119fe851d1a553e35e4a378a4ef23c79878ace4034fdc` | 字节相同 |
| `scripts/sermon_sentence_interpretation.py` | `a086e253fdb63212c43c3123959c15f16b8cfc12d5733a41a282bcd4afb983e6` | `a086e253fdb63212c43c3123959c15f16b8cfc12d5733a41a282bcd4afb983e6` | 字节相同 |
| `scripts/sermon_source_budget.py` | `3535ce654bf43a1f65432d902309d6d1e19fc5ab99f4b23177b5435004272d2f` | `3535ce654bf43a1f65432d902309d6d1e19fc5ab99f4b23177b5435004272d2f` | 字节相同 |
| `scripts/sermon_transcription_request.py` | `166f7804f586be1102347ab7ce6d3127e24985281a551982096e9016ab681852` | `166f7804f586be1102347ab7ce6d3127e24985281a551982096e9016ab681852` | 字节相同 |
| `scripts/sermon_workflow_jobs.py` | `2957a9d354bf4494f94440602988dacc7ef88c73bd32e90697efb6580cfae98d` | `48c2300f8e2b417a0bd7d0f20036ff5df0b25e0dcec28b38e90760e3300c5b30` | 字节改变 |
| `scripts/spoken_condensation.py` | `7328bdb1a74979836e5be3862cff2594041a6b9856af5636f045864a432a112a` | `f196e323cb08418825f7dda13f85f1a1ab8aa95f8f3a0a7c462b6e9f4cd421d9` | 字节改变 |
| `scripts/target_audio_auto_qc.py` | `03d0ee9475f1ba765a9f77f0901f7e678f4f47e71cbf3a2ab8273eca94be66d0` | `d85ac8c8b77fbf9ea8fe4aad5ac9b1f2c989acced5be50ee01ed5f92a9f3b7f0` | 字节改变 |
| `scripts/target_audio_predicted_schedule.py` | `868bae3172210144c8a67419259eb05d0cb96a9d386923ffa4faf13e7f75037d` | `b88df58718f4095866e6b747261e2837b8ee967bd111c305ed900431e1e7ac84` | 字节改变 |
| `scripts/target_text_auto_qc.py` | `8e8b0c5f0fa5dd72621a42ef89bed437db21b929288abd40e048dd7442877d57` | `4146b2f6dcef36f633479e01bee115116c83d77dd8dffb9b9cbbe6cbb5bd6519` | 字节改变 |
| `scripts/tongxing_host.py` | `af34c8f17830de6f150095b419e8585590e45c926dd8708d2b4cea5bcdcbcf2b` | `8748785b02fac434a5379f872ce3186b96f03dc41a5aaf0db0991153d87f6dd7` | 字节改变 |

## 验证与界限

- #579/#588/#582 各当前头的 Python CI 八分组和汇总 job 均成功；各自代码和安全审查通过，未解决线程为零。脱敏终态报告分别见 [#989](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/989)、[#990](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/990)、[#991](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/991)。
- 最终 `dev@974862e6b85d` 的八个相关模块本地复验 97/97 通过，退出码 0；独立脱敏报告见 [#992](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/992)。这仍是代码测试，不是三语真实校准。
- iOS 的手动检查与 Python 结果分开记录；截至本记录生成时，#579/#588/#582 的最终头 iOS 运行尚未全部取得终态。设备播放和场地验收均未执行。
- 历史冻结运行的 85 项未知结果与 4 项请求预留仍按早先清点保留为未对账状态。会话决定仅允许这些历史状态不阻断 G1 代码合并；它们不授权新的付费派发，也没有被改写成成功。
- 新的 es／ko／zh-Hans 机器质检、校准和豁免必须从最终实现身份、原冻结来源与当前预算政策重新生成计划并取得批准；旧 `implementationSha256` 收据不转签。

身份计算与闭包规则见 [review 注入设计](../design/review-layer-injection.zh.md)；测试报告与真实生产收据的区分见 [运行报告流程](../test-run-retrospective.zh.md)。
