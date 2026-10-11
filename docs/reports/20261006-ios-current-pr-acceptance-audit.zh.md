# 近期 iOS PR 与真机验收核对

日期：2026-10-06。核对远端而非本地旧main：`main=b9f9e1efb49b1c3d161a196fe534372cdcd2a6a8`，`dev=1e0959bdb57e2c706903244cd721bc20b7c86661`。本轮接续已推送的集成分支 `codex/ios-pr251-255-beta` / `4a1446901e3e3d848ec2e5ed3cda503c9e4d2e4e`；未覆盖原main工作树的四个未提交生产脚本/测试文件，也未更新其他活动分支。GitHub最新PR列表未发现该集成分支已有PR。

## 当前状态

| PR | 状态与依赖 | 本轮判断 |
| --- | --- | --- |
| [244](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/244) | OPEN → dev | 全文跟随、返回当前句已在后续Beta继承；暂停/VoiceOver/真机待验收 |
| [246](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/246) | OPEN → 244分支 | 分发工具已继承；一条未解决review在现行代码仍存在，本轮修复版本/Build碰撞守卫 |
| [247](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/247) | OPEN → 246分支 | 内容、大纲、系统播放和Activity状态已继承；不能把旧“实时锁屏字幕”承诺当作当前能力 |
| [249](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/249) | OPEN → 247分支 | 前台反馈、最近同步字幕和stale降级已继承；系统岛恢复仍缺真机证据 |
| [251](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/251) | OPEN → main | 早停及预算/资源/晚到结果修复已在Beta56集成 |
| [252](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/252) | OPEN → main | 圆形玻璃、紧凑、大字与编译修复已集成 |
| [253](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/253) | OPEN → main | Duo布局/避让已集成；真实hinge与多窗口待验收 |
| [254](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/254) | OPEN → 253分支 | 收起/展开与三入口overlay已集成并修复入口 |
| [255](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/255) | OPEN → 254分支 | 忙碌观察、有限后台assertion、VO确认已集成并修复编译/过期处理 |

GitHub reviewThreads新鲜读取：246存在上述未解决thread；247、249、251–255均无inline thread。没有把旧报告中的所有问题推定仍存在。251–253的promotion-policy失败是main只接受dev或release/YYYY-Www的现行规则；本轮不修改规则。新集成Draft以dev为目标，保留原PR引用，不合并任何PR。

## 最新Beta与已有验证

仓库GitHub Releases当前为空；App分发以 [Beta 1.26.15（56）记录](../../apps/tongxing-ios/BETA-RELEASE-1.26.15.zh.md) 为依据。该记录绑定冻结源码 `8c71c02cc983cb7aea9e2a9bcd9d5bc8ff603f08`、IPA哈希与2026-10-06 16:18:05 UTC Apple `VALID / IN_BETA_TESTING`读回，不沿用Beta55，不以口述数字推测版本。本轮未重新访问Apple账号、上传、归档或分发；私有receipt路径保留在原记录，未伪装为本机重新执行。

[Beta56整合报告](20261006-ios-pr251-255-beta56.zh.md)已有Xcode27.1构建/归档、iOS27/17采音、面板与assertion、Storage和26张模拟器截图证据。本轮复核对应代码与测试已存在，未重复编写原已修复功能。真实声学、权限、锁屏/岛、耳机/来电、断网冷启动、后台系统到期、VO和Duo真实保留区/多窗口均不能由这些证据关闭。

## 本轮可执行修复与验证

- 新增 [19项真机验收表](../../apps/tongxing-ios/DEVICE-ACCEPTANCE-1.26.15.zh.md)，含每项步骤、通过标准、待验收结果及证据栏；补版本/设备/内容/网络/辅助功能记录，保留系统锁屏快照和Book活动折痕边界；从Beta说明链接该表。
- 修复246遗留分发身份碰撞：首次upload遇到Apple已有同版本/Build必须失败；只有同IPA、归档哈希、源码与App身份的既有upload attempt才允许显式retry对账。清除继承的绕过环境变量；wait/distribute也校验既有绑定attempt，单纯preflight不算上传证据。已分发Beta56不变；新守卫属于源码工具修复，不在已冻结IPA中。
- 补齐255新加的定位忙碌状态及展开/收起操作提示的en/ko/es/vi翻译，避免非中文VoiceOver回退中文；3个key×4语种及占位符一致性检查通过。该资源修复尚未进入已分发Beta56；真实播报与焦点仍待验收。
- 本机离线单元验证：`python3 -m unittest tests.test_ios_testflight_release tests.test_xcode_cloud_archive_admission`：27通过、0跳过；覆盖真实Ruby lane的已占号拒绝/合法对账、不同IPA/归档/源码拒绝，以及wrapper环境变量清理/绑定重试。`ruby -c apps/tongxing-ios/fastlane/Fastfile`、Python语法与`git diff --check`通过。所有Apple/fastlane动作由fake替代，未调用外部上传。
- 本机没有完整Xcode。默认CLT执行先因缓存目录权限失败并伴随SDK诊断；改用任务内隔离module cache后Core源码可编译，`swift build --disable-sandbox --package-path apps/tongxing-ios/Core`通过。完整Core测试编译仍因CLT缺少TestingMacros插件失败，未执行测试，不计通过；日志保留于 `../evidence/merged-core-build.log` / `merged-core-final.log`。AppModel仅本机语法parse通过，不冒充iOS类型检查。本轮没有本机模拟器或Accessibility Inspector证据。

## CI实际执行边界

已读取job和step，而非只看绿色汇总。251/252/253对应Tongxing iOS runs [37418025990](https://github.com/JonathanJing/sermon-video-zh-subtitles/actions/runs/37418025990)、[37424537468](https://github.com/JonathanJing/sermon-video-zh-subtitles/actions/runs/37424537468)、[37425922394](https://github.com/JonathanJing/sermon-video-zh-subtitles/actions/runs/37425922394) 的 `contract-validation` 和 `ios-validation` 全部 skipped；只有变化检测及required汇总执行。246/247/249/254/255当前无status checks，堆叠分支目标不在workflow触发范围。244的contract-validation运行，但ios-validation跳过。绿色native-client不等于构建、播放器或UI测试通过。

集成PR为Draft，现行workflow会跳过原生检查；为本次精确head另行dispatch现有Tongxing iOS workflow，用job/step终态报告结果。CI结果与最终remoteSHA记录在PR，若托管工具链/权限阻塞，明确保留阻塞；不改workflow规则、不把skip算通过。现场和真机所有未执行项保持not_run。

## dev冲突补修（同日后续）

push前核对工作分支远端仍为本任务head `19e6ba532cbfb5e63cf4ae9e6133a30f62cc610b`，无新增并行写入；dev仍为上述 `1e0959bd`。按主会话明确授权将dev合入本工作分支，未把PR合入dev。仅AppModel与PublishedTranscript有文本冲突，逐段保留两侧语义：

- AppModel：保留当前验证的transcript selection key、同一音轨系统字幕/标题、前台反馈、后台assertion；加入dev的独立审核study加载/切篇清理与正式播放版edition。标题fallback与edition同时生效，异步结果仍通过request和selection key守卫。
- PublishedTranscript：保留reviewed summary/outline/questions与独立source/audio时钟、reviewMode与v3合同；custom decoder补齐可选学习字段CodingKeys/初始化，避免自动合并遗漏导致不能编译。
- 新增两条Core回归：reviewed study与独立音频时钟并存、来源ID标题fallback仍保留正式edition；现有study格式/错误身份、时钟合同、标题、Storage、播放器及UI回归由最终head检查覆盖。

合入dev带来既有祖先提交，未在本任务改写生产模型/成本/权限实现；最终PR相对dev的改动限定于iOS和对应测试/文档。Beta56分发源码仍是原冻结8c71c02，本次后续源码候选（分发身份守卫、四语文案、dev语义合并）未打包或上传；不能用Beta56真机结果证明后续源码候选已验收。原head的CI分别保留，最终SHA与终态在PR回填。

独立study资源合并后还补齐原“大纲与默想”入口：仅在当前transcript验证绑定成立时读取同一publishedStudies，展示原section标题/全文，不把默想正文冒充问题、不再错误显示旧字段缺项。现有四产品UI回归增加sheet与正文一致、缺项提示消失断言及截图附件；后续UI证据绑定新head，仍非Beta56已分发包证据。

多窗口代码复核确认单窗口scenePhase会错误清除共享定位反馈：已将前台标记交给App聚合scenePhase，保留所有窗口后台时suspendAlignment清除路径；新增重复前台通知保留当前反馈回归。实体双窗口监听仍待验收。手动native workflow新增受限scheme选项，默认正式身份不变，本候选使用TongxingBeta运行Beta专属反馈用例，逐项记录实际skip。Ruby YAML解析、Swift语法解析通过；本机仍缺完整Xcode/TestingMacros，native执行由精确head云端CI提供。

精确head209e的root-0 CI执行2032项（11skip）出现唯一失败：新增TestFlight测试依赖iOS，但Python native_contracts快速路线未列入。已补tests.test_ios_testflight_release调用；CI scope、iOS route、docs gate、TestFlight和archive admission共51项本地测试全部通过。root-1同head2316项（11skip）成功，另有统一交付合约67项/5子测试通过。旧失败保留；最终head结果在PR正文回填。

209e的Beta原生日志与xcresult已保存：116项App单元测试中15skip、1个本地WAV准备10秒超时；新增反馈过期/重复前台回归实际通过；新学习资料sheet UI回归通过。旧UI假设暴露紧凑/AX dock无可见clock、匿名页面安全标题及审核证道通知标题变化，修正测试读取现有Play可访问性时间值、使用当前句返回操作、按播放按钮边界限制阅读区域，标题期望改为现有安全标题。通知用例仍要求实际系统展示与verified landing，不把schedule视为通过。WAV准备上限与已有fixture一致改30秒；完整Beta套件超过原35分钟job边界，改45分钟，默认测试集和skip门禁未缩减。

真实209e模拟器附件（非真机、非最终head）：[大字紧凑dock](20261006-ios-current-pr-evidence/large-text-compact-dock-209e.png)证明可见clock省略而控件保留；[学习资料sheet](20261006-ios-current-pr-evidence/reviewed-study-sheet-209e.png)展示审核大纲/默想全文。由同一xcresult解压提取、未修改像素；原run取消终态与其中失败保留，后续验证绑定新head。

6b精确head的Python完整workflow成功：2032/2316两分片共4348项、22skip，原CI调用遗漏已关闭。Beta原生Core 97/Storage 53报告成功；App单元116项、15skip、0fail；Beta通知3项全通过并实际观察系统展示与verified landing。UI58项、8skip、6fail：两处收起断言误用了进度值回退查询，已改回直接检查可见clock元素；另外四处实际AX层级仅暴露工具栏“当前句”，外层accessibilityLabel的跟随/自由阅读状态被toolbar桥接丢失。把状态写入Button自身标题，按既有图标工具栏模式呈现，保留原状态UI断言；实体VoiceOver仍待验收。旧6b失败与实际层级证据保留，下一head重新核对。

完整原生suite改为三个fail-fast=false分片：App单元与全部非ListeningFlow UI类；6个字幕/收起回归；其余46个ListeningFlow方法。workflow从源码发现全部4个UI测试类及52个ListeningFlow方法，校验回归子集存在、6/46互斥且并集等于全部方法；未减少默认测试、未改变opt-in/skip验收门禁、未再加时。每组独立artifact，native-client依赖整个matrix成功。YAML/内嵌Python解析、只读分片计划验证及51项本地路由/守卫测试通过；分片计划不算实际模拟器执行。
