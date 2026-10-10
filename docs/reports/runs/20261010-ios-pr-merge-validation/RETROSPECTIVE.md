# iOS PR 合并验证复盘

本轮只验证 Layer 4 原生客户端及目录更新工具。未运行 L1–L3、模型、正式内容生产、Spark、归档、TestFlight 或内容发布；真机与现场验收均 not_run。

结果：Core 实际 16 项通过、2 项真实 fixture 条件测试跳过（Swift Testing 的18项汇总含跳过）；Python 11项通过；网页54项通过；两个不同 UI 场景通过，一项 hosted 播放模型测试通过。类别刷新前后截图在本地 xcresult 附件中，确认类别文本改变且保持暂停、00:02位置。

首次 UI 刷新测试因在“更多”Form中使用收听页面的滚动边界而失败；改用已有Form定位方法后重跑失败场景与hosted回归，两项通过。修复提交96547b00；保留初次失败与复验记录，未把重试算作新增场景。构建成功；Core最终编译4.19秒，复验hosted1.093秒、UI22.966秒，未作性能比较。

未使用Spark资源；版本号、Apple build分配及外部部署均未改变。唯一预检改进是按当前视图容器选择测试定位方法。原始日志、xcresult及截图保留在忽略目录，稍后清理临时worktree前应先复制产物。

本轮代码在#261；旧发行分支的合并保留当前1.26.18配置。海报/APNs及类别架构的既有反馈记录在docs/ios-pr-history-integration-20261010.zh.md，关闭历史PR线程不表示这些问题已经修复。云端CI及最终合并回执另以GitHub PR为准；本报告仅为本地测试结果。

#263 追加兼容修复：v2网页读取器接受并严格校验类别元数据；`node --test tests/test_formal_dev_adapter.mjs` 11项通过，提交5d254a8b。报告日志副本去除行尾空格以满足文档检查，manifest中的SHA仍绑定原始运行文件。

最终审核在96547b00发现非默认语言标题被误加的defaultTargetLocale条件过滤；79bc3ec4移除该限制，新增中/韩不同标题的hash绑定fixture及hosted回归。新测试首次因未调用视图负责的文稿load而超时，补显式load后1项通过；前后日志与outcome均保留。最终hosted唯一场景为2项，最终合并CI以79bc3ec4为准。
