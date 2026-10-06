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
- 本机没有完整Xcode；CommandLineTools的Swift/SDK版本不匹配，Core manifest编译失败，未执行Core测试，不计通过。本轮未运行模拟器或Accessibility Inspector。保留本地日志 `../evidence/core.log`，不能用旧Xcode receipt声称本轮构建成功。

## CI实际执行边界

已读取job和step，而非只看绿色汇总。251/252/253对应Tongxing iOS runs [37418025990](https://github.com/JonathanJing/sermon-video-zh-subtitles/actions/runs/37418025990)、[37424537468](https://github.com/JonathanJing/sermon-video-zh-subtitles/actions/runs/37424537468)、[37425922394](https://github.com/JonathanJing/sermon-video-zh-subtitles/actions/runs/37425922394) 的 `contract-validation` 和 `ios-validation` 全部 skipped；只有变化检测及required汇总执行。246/247/249/254/255当前无status checks，堆叠分支目标不在workflow触发范围。244的contract-validation运行，但ios-validation跳过。绿色native-client不等于构建、播放器或UI测试通过。

集成PR为Draft，现行workflow会跳过原生检查；为本次精确head另行dispatch现有Tongxing iOS workflow，用job/step终态报告结果。CI结果与最终remoteSHA记录在PR，若托管工具链/权限阻塞，明确保留阻塞；不改workflow规则、不把skip算通过。现场和真机所有未执行项保持not_run。
