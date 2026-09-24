# 多语言四层周更：合并 main 前检查

检查日期：2026-09-23。目标是本周六／周日的新证道经过 Layer 1–4，在 Firebase Production Hosting 提供中文、韩语和西班牙语页面。本文区分已验证样片、可重复代码和尚未发生的周更生产。

[本次本地演练与线上基线证据](evidence/2026-09-23-production-readiness/README.zh.md)。

Firebase Dev 的 Production 布局预演、发布核验和旧内容保留结果见[Dev 预演收据](evidence/2026-09-23-production-readiness/DEV-PREVIEW.zh.md)。它使用已审样片做端到端预览，不把新一周尚未发生的 Layer 1–3 标为通过。

## 当前事实

- Firebase Dev 的 2026-09-20 正式样片有三语文字、配音、同步人工审核与发布后 HTTP 证据；仅覆盖原录像 35:09.16–38:07.32。[收据](evidence/2026-09-20-formal-release/README.zh.md)不批准下周整篇。
- Firebase Dev 的 Production 布局首页已发布；完整 121 文件 HTTP/SHA/Content-Type、三条音轨 Range 206、三语深链及真实浏览器短时播放通过。旧六句实验入口和九周中文入口仍可访问。这是已审 2:58 样片的 Dev 验收，不能代替新一周 Production 发布或实体设备验收。
- 只读线上核对：Production /weekly.json 是 sermon-weekly-catalog-v1，共 9 个中文周次；Production /multilingual-v2.json 返回 404。本地 registry head 的 weekly.json 与线上字节 SHA-256 相同：6b7bbd018e1df2d39ea5287c9e6a3114ee6a6a0c953e2f39cdc4d3d3244204bf。三语尚未发布到 Production。
- 原生 iOS Release 仍读取 Production 的中文目录。多语言目前通过已验证的网页页面提供；iOS 的原生跨语言播放、下载、历史和现场定位仍见 [Layer 4 backlog](multilingual-layer-4-delivery-app-backlog.zh.md)。

## 本分支准备的候选

1. 新 Layer 3 job 可以用 render_formal_target_language_speech.py --track-format mp3，把同一 1 倍速排程的 PCM track 编码成 64 kbps 单声道 MP3。manifest 绑定实际 MP3 hash 和解码时长。已有 WAV job、音轨及人审收据不改；新 MP3 仍须完整 ASR、听审和视频同步审核。
2. 正式资源准备器、严格 staging 和网页播放器接受同 locale 的已审 MP3 或 WAV。网页完整哈希读取上限为 64 MiB；整篇音轨超限时必须停止并调整受审核交付格式，不跳过哈希。下载文件扩展名跟随真实格式。
3. assemble_multilingual_hosting.py 从完整旧 Hosting public 和已审 stage 生成新候选目录：复算收据、发布包和正式资源 SHA；保留旧文件；拒绝同 ID 覆盖与路径冲突；保存完整文件清单、基线哈希和旧 catalog 回滚副本。--production-reader 增加独立三语页面入口；--promote-home 把它设为首页，旧中文 App 保留在 /legacy-reader.html，旧海报的 /?week= 链接自动转入旧页。按旧发行报告保留反馈 API 转发，旧 weekly.json 字节不变。连续周更会更新新默认页并保留上一周三语文件。状态始终为 validated_not_deployed。
4. verify_multilingual_hosting.py 的 --preflight-baseline 逐文件比对候选旧快照与 Production；deploy_multilingual_hosting.py 仅接受绑定本候选且 30 分钟内的新收据，限定 Firebase 项目、站点、deploy target 和反馈路由；--execute 才真正发布。发布后同一核验器逐文件 GET/SHA，检查音频 Range 206 和三语深链，HTTP 收据不升级设备/现场状态。
5. Production 本地重放以 registry head rel_cbd3c91f6e220482fe00acbc 的 9 周旧站点和已审 9 月 20 日三语样片构建候选。旧首页、9 周列表与 PDF 下载入口可见；新增韩语页显示 44 组且音轨播放到 00:02。该重放只证明本地叠加与浏览器路径，不证明下周整篇、Firebase rewrite、正式域名或实体设备。

## 本周正式发布硬门槛

| 阶段 | 必须新取得的证据 | 当前状态 |
| --- | --- | --- |
| Layer 1 | 完整归档媒体、人工批准的证道窗口、词时间与英文审核收据；English Source Package ready_for_translation | 本周新来源尚未生成 |
| Layer 2 | 同一英文身份的中、韩、西正式候选；经文、术语、独立模型复核和全文人工批准 | 仅样片通过 |
| Layer 3 | 三条同 locale MP3、完整解码与哈希、全组 ASR 筛查／裁决、全文听审与原视频 1 倍速同步审核 | 整篇未生成；MP3 只有合成测试 |
| Layer 4 | 同 locale Release Package、旧站点快照、候选校验、Production 部署、逐文件 GET/SHA、音频 Range、三语深链与真实播放 | 已审样片的 Dev Production 布局已部署、HTTP 和浏览器短时播放通过；新整篇及 Production 未部署 |
| 设备／现场 | 实体设备与现场验收分别留证；iOS 原生多语言若列入范围须另验收 | 未执行 |

Dev 经文授权声明和样片页面／音频审核不能自动覆盖 Production 的许可范围与署名要求；正式发布前核对适用条款并落实署名。样片收据不能复制给整篇。

## 周六操作顺序

1. 按[本地生产 runbook](codex-local-production-runbook.zh.md)完成来源、窗口和英文批准。仅在 Layer 1 ready_for_translation 后启动三语 Layer 2。
2. 分别完成文字审核，再用 --track-format mp3 渲染三条新整篇音轨，逐语言完成 ASR、全文听审和视频同步。任一语言未通过时保留候选，不加入正式 catalog；本周要求三语音频齐全，整页等待。
3. 使用 build_formal_dev_release_assets.py 与 stage_formal_multilingual_dev.py 准备同一新 page ID 的三语 stage。修订建立新身份，不能覆盖旧发布包。
4. 在完整、已核验的 Production registry head 上执行：

       .venv/bin/python scripts/assemble_multilingual_hosting.py \
         --base-public /absolute/path/to/current-registry-head/public \
         --staged /absolute/path/to/reviewed-layer4-stage \
         --out /absolute/path/to/new-hosting-candidate \
         --production-reader --promote-home

5. 在发布窗口停止其他对同一 Hosting 站点的部署；逐文件核对线上旧站点与候选基线。若 registry head 或线上字节改变，废弃候选，从新 head 重建。保留旧完整 registry release 和候选的 rollback-multilingual-v2.json。

       .venv/bin/python scripts/verify_multilingual_hosting.py \
         --candidate /absolute/path/to/new-hosting-candidate \
         --origin https://ai-for-god-sermon-audio.web.app \
         --preflight-baseline --out /absolute/path/to/preflight.json

6. 审核 firebase.json、.firebaserc、build-report.json 的目标站点、反馈转发及修改文件清单。使用以下显式发布入口；先不加 --execute 可生成部署计划，真正发布须另用新的输出文件加 --execute：

       .venv/bin/python scripts/deploy_multilingual_hosting.py \
         --candidate /absolute/path/to/new-hosting-candidate \
         --preflight /absolute/path/to/preflight.json \
         --out /absolute/path/to/deployment.json --execute

7. 发布后立即执行完整 GET/SHA、音频 Range 206、三语深链检查，并在真实浏览器／手机分别听播；不要从 HTTP 收据推断设备验收。之后按[海报交付流程](tongxing-weekly-release.zh.md#每周海报交付)制作本周海报。

       .venv/bin/python scripts/verify_multilingual_hosting.py \
         --candidate /absolute/path/to/new-hosting-candidate \
         --origin https://ai-for-god-sermon-audio.web.app \
         --out /absolute/path/to/http-verification.json

首次切换的回退源是切换前的完整 legacy registry release；本次只读调用 `deploy_firebase.verify_release` 已通过其 58 个文件及反馈配置的本地校验。若实际切换后需回退，应先把该不可变发行复制到新的回退目录，再按既有 `experiments/sermon-dubbing-poc/deploy_firebase.py --release ... --project ai-for-god-caption-dev --site ai-for-god-sermon-audio --execute` 重新发布，并用 `verify_weekly_release.py` 完整核验。不能修改 registry 原件，不能把本地可回退判定冒充一次实际回退演练。后续多语言版本间的回退仍需专门流程。

## 合并 main 前仍需解决

- P0：本周新整篇实跑。来源、三语人审、完整音轨和移动浏览器听播尚不存在；2:58 样片不能代替。
- P0：真实发布与回退演练。部署和 HTTP 核验入口已有定向测试，旧 legacy 发行可通过现有部署器静态验证，但尚未在 Production 执行回退；Firebase 版本切换无原子 CAS，需冻结同站点发布窗口并保留旧发行。不要把本地报告标为发布通过。
- P0：旧发行器衔接。后续 legacy 中文发行可能覆盖多语言首页；每次周更必须以当时完整 registry head 重新叠加。长期需把 v2 保留与回滚纳入 registry 合同；新中文周更应同时可从旧页访问。
- P1：若本周包含原生 iOS/TestFlight，需完成跨语言音轨、locale/hash 下载与历史、实体 iPhone 验收；网页候选不满足。
- P1：单 locale 回滚与内容修订。当前拒绝同 ID 覆盖，以免静默修改已发布资产；尚需受审核的新版本路径和 CAS 单语言回滚。

本分支不部署 Production、不合并 main，也不修改用户主工作树的未提交内容。
