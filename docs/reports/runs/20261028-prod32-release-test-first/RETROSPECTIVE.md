# 复盘：20261028-prod32-release-test-first

脱敏日志与原文件哈希见同目录 `INDEX.md`、`manifest.json`。完整 xcresult 留在本机忽略目录。

## 结论先行

交付类型：iOS Release 定向测试。首次 `Tongxing / Release` 构建阶段失败，`xcodebuild` 退出码 65；测试用例未执行，不能计作测试断言失败或通过。

## 总时间

本轮无独立 journal 或阶段计时文件；保留命令起止记录，不估算模型耗时。

## 各层模型、耗时与速度

无模型调用；L1–L3 未运行。L4 为 Xcode Release 模拟器构建，未进入测试断言。

## 错误

Release 的 `Copy local weekly guides` 阶段复制插图时，Xcode 脚本沙盒拒绝向 App 包创建图片文件；工程只声明了 JSON 输出。随后在 `project.yml` 增补两张插图的输出声明并重新生成工程，使用独立 DerivedData 重跑。Swift 模块依赖错误与脚本失败同轮出现，需看重跑是否仍存在。

## 可以改进的地方

对需要复制的每个资源同时声明 Xcode 脚本输入和输出，以便带真实资源的 Release 构建能在归档前被定向验证。

## 实际覆盖范围

本轮只执行 Release 模拟器构建入口，未完成手册数据测试，也没有归档、上传或提交审核。

## 遗留状态

失败日志与 xcresult 保留在忽略目录；新 Build 号尚未用于 Apple 上传。

## 外部可见的变化

无。正式 App、设备与场地状态均未变化。
