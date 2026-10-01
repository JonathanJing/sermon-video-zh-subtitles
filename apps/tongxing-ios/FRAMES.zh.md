# Frames：截图与录屏展示素材

[viticci/frames-cli](https://github.com/viticci/frames-cli) 给已有截图或录屏加 Apple 设备外框。同行将它作为可选的**素材后处理工具**，不是 UI 设计器、截图器、测试门禁或 App 运行依赖。

工作顺序：`make preview` 或已授权的真实截图／录屏 → 保留原始证据 → Frames 套框／拼图 → 人工核对展示素材。它不修改 SwiftUI、网页、播放器、内容生产、Xcode 工程、CI 或发布设置。未安装 Frames 不阻塞原有开发与验收。

## 1. 一次性安装（开发机，显式执行）

使用独立目录和 Python 虚拟环境，不改项目的生产依赖，也不下载或提交设备素材到 Git。以下命令供首次安装使用；目录已存在时先检查其 revision 和本地修改，不覆盖已有安装。

```sh
export TONGXING_FRAMES_HOME="$HOME/.local/share/tongxing-tools/frames-cli"
export TONGXING_FRAMES_VENV="$HOME/.local/share/tongxing-tools/frames-venv"
mkdir -p "$(dirname "$TONGXING_FRAMES_HOME")"
git clone https://github.com/viticci/frames-cli.git "$TONGXING_FRAMES_HOME"
git -C "$TONGXING_FRAMES_HOME" checkout --detach 2a62a0c9b77d3d8582f5d1a41d97a80677664e0f
python3 -m venv "$TONGXING_FRAMES_VENV"
. "$TONGXING_FRAMES_VENV/bin/activate"
python -m pip install Pillow
export TONGXING_FRAMES_BIN="$TONGXING_FRAMES_HOME/frames"
"$TONGXING_FRAMES_BIN" --version
"$TONGXING_FRAMES_BIN" setup
"$TONGXING_FRAMES_BIN" doctor --json
```

使用 Python 3.10+ 运行本仓库入口。上面的上游 commit 是本次接入时读取的 `main`，固定代码 revision，**不等于已在本机完成安装／渲染验证**；Pillow、FFmpeg 与素材包不在此锁定。后续升级先核对上游变更并重新执行小样验证，不在每次套框时自动拉取最新代码。

上游 `setup` 会交互下载 MacStories 外框素材，并写入 `~/.config/frames/config.json`。录屏另需 `ffmpeg`／`ffprobe` 5.1+；macOS 上 `setup` 可能提议通过 Homebrew 安装，需明确同意。只做 PNG 时不需要视频依赖。`doctor` 进程退出零不一定表示就绪，要检查 JSON 的 `ok` 和问题列表。详见[上游使用说明](https://github.com/viticci/frames-cli/blob/2a62a0c9b77d3d8582f5d1a41d97a80677664e0f/README.md)。

新终端重新激活上面的虚拟环境并设置 `TONGXING_FRAMES_BIN`；也可使用已配置好且位于 PATH 的 `frames`。wrapper 不修改 shell 配置、不安装软件、不触发交互下载。已有素材可通过 wrapper 的 `--assets /实际/素材目录` 或上游 `FRAMES_ASSETS` 环境变量指定。

## 2. 跟现有预览流程配合

从仓库根目录执行，先按 [PREVIEW.zh.md](PREVIEW.zh.md) 生成视图：

```sh
make preview FILES=ContentView.swift
python3 apps/tongxing-ios/scripts/frames.py --help
```

从**本轮成功**的 preview manifest 取得实际 PNG 路径，设置 `SHOT`；不要猜一个旧目录或抓取通配符中最新的图片。下例的路径是占位，必须换成已存在的文件：

```sh
SHOT="/实际路径/preview-ContentView-light.png"
python3 apps/tongxing-ios/scripts/frames.py --dry-run "$SHOT"
python3 apps/tongxing-ios/scripts/frames.py "$SHOT"
```

`--dry-run` 验证输入与参数并显示命令，不执行上游工具、不写文件，未安装 Frames 也可运行；它**不能证明**素材、编码器或设备匹配有效。真实运行会检查上游退出码、JSON 错误及非空输出；失败保留本轮日志与已有产物，不把失败算成功。

Frames 通常按截图尺寸匹配设备；相同分辨率可能对应不同代际。发布或前后对照图优先显式指定与源截图一致的机型和颜色，并保留相同素材版本。先查实际名称，不硬编码某款手机作为所有预览的默认值：

```sh
"$TONGXING_FRAMES_BIN" list
"$TONGXING_FRAMES_BIN" info "$SHOT"
# DEVICE_NAME 设置为上面查到且与源截图匹配的完整机型名。
"$TONGXING_FRAMES_BIN" list-colors "$DEVICE_NAME"
python3 apps/tongxing-ios/scripts/frames.py --device "$DEVICE_NAME" "$SHOT"
```

测试渲染图没有 SpringBoard 状态栏，局部组件处于测试容器中。套框不会把它变成真实设备截图；对外展示时标注“SwiftUI 测试渲染 + 设备外框”，核对合成内容、设备比例、圆角、刘海／挖孔与裁切。已裁切、缩放或尺寸不匹配的图不要强行套框伪装成真机结果。

## 3. 常用命令

以下输入文件同样必须换成实际存在的本地文件；带空格的路径分别加引号。多个 PNG 不带 `--merge` 时逐张输出，带 `--merge` 时按输入顺序横向拼接：

```sh
# 首页、播放器分别套框
python3 apps/tongxing-ios/scripts/frames.py home.png player.png

# 固定顺序的页面展示／前后对照；原图仍单独保留
python3 apps/tongxing-ios/scripts/frames.py --merge before.png after.png

# 已有操作录屏；默认 balanced，不进行录制
python3 apps/tongxing-ios/scripts/frames.py --video --preset compact demo.mp4

# 两段录屏并排，并按左到右依次播放
python3 apps/tongxing-ios/scripts/frames.py --video --merge --playback-offset one.mp4 two.mp4
```

`--color` 接受上游颜色名；`--assets` 指定已有素材。相同 basename 的独立输出会被拒绝（含大小写差异），以免覆盖；可给输入副本改名、分别执行，或使用合并模式。PNG 与视频不要混在一次调用中。

视频单独输出保留上游音轨规则；顺序合并连接音轨，默认同时合并不混音。wrapper 只封装常用 PNG／MP4 路径；透明视频、旋转或其他高级参数直接按上游文档使用 `frames video`，并显式输出到新的忽略目录。透明 HEVC 需兼容的 macOS 编码器和播放端，不作为默认验收格式。

## 4. 输出、隐私与证据

每次实际运行创建独立目录，不覆盖原图或上一轮结果：

```text
artifacts/tongxing-ios/<日期>/frames/run-<唯一值>/
  *_framed.png / *_framed.mp4 / merged_framed.*
  receipt.json          # presentation_only、命令、源／输出路径与 SHA-256、真实状态
  frames-result.json    # 上游 stdout，失败时也保留原文
  run.log               # 上游 stderr
```

这些目录已由仓库根 `.gitignore` 忽略。receipt 是素材处理记录，**不是原始 App commit、预览测试、人工审核或发布批准的替代品**；保留并关联源 preview manifest，或真实录屏的来源、App revision、设备、语言、外观与操作说明。机器／个人路径留在本地，分享前复核日志和画面中的姓名、通知、账号、后台地址与未发布内容。

UI 评审继续使用同条件的**原始截图 + 批注 + 交互证据**，套框图只是辅助展示。不要让设备边框掩盖布局差异；不要将素材生成写成真机、音频、现场或 App Store 验收通过。任何上传、发布、TestFlight、网页部署仍单独按授权处理；本入口不执行这些动作。上游 CLI 与设备 artwork 的来源、许可和品牌使用条件分别核对，不因代码开放就假设素材可任意再分发。

## 5. 验证与升级

无需 Xcode、Pillow、FFmpeg 或真实素材即可执行 wrapper 定向测试：

```sh
python3 -m py_compile apps/tongxing-ios/scripts/frames.py
python3 -m unittest discover -s apps/tongxing-ios/scripts/tests -p test_frames.py -v
git diff --check
```

测试使用替身 CLI，覆盖参数校验、空格路径、dry-run 无副作用、缺失依赖、退出码／JSON 错误、独立输出、源文件哈希与视频拼接参数；**不证明上游渲染、Apple 素材或 macOS 编码器可用**。

开发机安装或升级后的实际小样验证：从成功预览取一张 PNG，执行 dry-run 后套框，读取实际结果并核对裁切／设备匹配及原图 SHA-256；需要视频时另取一段经授权的短录屏，核对尺寸、时长、音轨与可播放性。记录上游 revision、`frames --version`、`python -m pip show Pillow`、FFmpeg 版本与素材来源。未执行项写 `not_run`，不要以替身测试代替真实渲染。
