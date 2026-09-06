import SwiftUI
import TongxingCore

// Explicitly select the iOS 17-compatible property wrapper; newer SDKs also
// export a State macro whose plugin is absent from Command Line Tools.
private typealias ViewState<Value> = SwiftUI.State<Value>

struct ContentView: View {
    @ObservedObject var model: AppModel
    @ObservedObject private var playback: PlaybackController
    @Environment(\.scenePhase) private var scenePhase
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @Environment(\.dynamicTypeSize) private var typeSize
    @Environment(\.verticalSizeClass) private var verticalSizeClass
    @ScaledMetric(relativeTo: .title2) private var readingSize: CGFloat = 26
    @ViewState private var sheet: ListeningSheet?
    @ViewState private var returnToCurrent = UUID()

    init(model: AppModel) {
        self.model = model
        self.playback = model.playback
    }

    var body: some View {
        NavigationStack {
            ScrollViewReader { proxy in
                ScrollView {
                    VStack(alignment: .leading, spacing: verticalSizeClass == .compact ? 12 : 16) {
                        if let week = model.selectedWeek {
                            sermonHeading(week).id("top")
                            if let notice = model.catalogNotice {
                                Label(notice, systemImage: "wifi.slash")
                                    .font(.footnote).foregroundStyle(.secondary)
                                    .accessibilityIdentifier("catalog-notice")
                            }
                            if let error = model.errorMessage {
                                Label(error, systemImage: "exclamationmark.circle").font(.footnote)
                            }
                            if let track = model.selectedTrack {
                                if let saved = playback.resumePosition {
                                    resumeCard(saved)
                                }
                                Picker("收听内容", selection: $model.display) {
                                    ForEach(AppModel.ListeningDisplay.allCases, id: \.self) { Text($0.rawValue).tag($0) }
                                }.pickerStyle(.segmented).accessibilityIdentifier("listening-display")
                                if model.display == .current { currentSubtitle(track) }
                                else { transcript(track) }
                                downloadControl
                            } else {
                                ContentUnavailableView("本周音频尚未准备好", systemImage: "waveform", description: Text("可以先阅读证道大纲。"))
                            }
                            footer(week)
                        } else if model.isLoading {
                            ProgressView("正在读取本周证道…").frame(maxWidth: .infinity, minHeight: 320)
                        } else {
                            ContentUnavailableView {
                                Label("暂时无法读取证道", systemImage: "wifi.exclamationmark")
                            } description: {
                                Text(model.errorMessage ?? "首次使用需要网络，下载后可离线收听。")
                            } actions: {
                                Button("重新加载") { Task { await model.refresh() } }.buttonStyle(.borderedProminent)
                            }.frame(minHeight: 320)
                        }
                    }
                    .padding(.horizontal, 20)
                    .padding(.top, verticalSizeClass == .compact ? 0 : 8).padding(.bottom, 24)
                    .frame(maxWidth: verticalSizeClass == .compact ? 920 : 720)
                    .frame(maxWidth: .infinity)
                }
                .accessibilityIdentifier("listening-scroll")
                .refreshable { await model.refresh() }
                .onChange(of: returnToCurrent) { _, _ in
                    if model.display == .transcript,
                       let index = model.selectedTrack?.cues.firstIndex(where: { $0.start <= playback.position && playback.position < $0.end }) {
                        withAnimation(reduceMotion ? nil : .easeInOut(duration: 0.25)) {
                            proxy.scrollTo("cue-\(index)", anchor: .center)
                        }
                    } else {
                        model.display = .current
                        withAnimation(reduceMotion ? nil : .easeInOut(duration: 0.25)) {
                            proxy.scrollTo("top", anchor: .top)
                        }
                    }
                }
            }
            .background(Brand.background)
            .listeningBottomBar {
                if model.selectedTrack != nil {
                    PlaybackDock(playback: playback, isPreparing: model.isPreparing,
                                 precision: { sheet = .precision }, current: { returnToCurrent = UUID() })
                }
            }
            .toolbar {
                ToolbarItem(placement: .principal) { BrandTitle() }
                ToolbarItemGroup(placement: .primaryAction) {
                    Button("选择证道周次", systemImage: "calendar") { sheet = .weeks }
                        .labelStyle(.iconOnly).accessibilityIdentifier("choose-sermon")
                    Button("更多选项", systemImage: "ellipsis.circle") { sheet = .about }
                        .labelStyle(.iconOnly).accessibilityIdentifier("more-options")
                }
            }
            #if os(iOS)
            .navigationBarTitleDisplayMode(.inline)
            #endif
            .sheet(item: $sheet) { destination in
                switch destination {
                case .weeks:
                    WeekSheet(model: model)
                        .presentationDetents([.medium, .large]).presentationDragIndicator(.visible)
                case .precision:
                    PrecisionSheet(playback: playback)
                        .presentationDetents(typeSize.isAccessibilitySize ? [.large] : [.medium, .large])
                        .presentationDragIndicator(.visible)
                case .outline:
                    OutlineSheet(week: model.selectedWeek, playback: playback)
                        .presentationDetents([.large]).presentationDragIndicator(.visible)
                case .about:
                    AboutSheet(model: model)
                        .presentationDetents([.large]).presentationDragIndicator(.visible)
                }
            }
        }
        .onChange(of: scenePhase) { _, phase in
            if phase != .active { playback.saveProgress() }
        }
    }

    @ViewBuilder private func sermonHeading(_ week: SermonWeek) -> some View {
        if verticalSizeClass == .compact {
            HStack(spacing: 16) {
                VStack(alignment: .leading, spacing: 4) {
                    Text(week.title).font(.headline).accessibilityAddTraits(.isHeader)
                        .accessibilityIdentifier("sermon-title")
                    Text("\(week.scripture) · \(week.speaker) · \(week.date)")
                        .font(.caption).foregroundStyle(.secondary)
                }
                Spacer(minLength: 8)
                Text(reviewLabel).font(.caption).foregroundStyle(Brand.accent)
                Button("证道大纲", systemImage: "list.bullet.rectangle") { sheet = .outline }
                    .buttonStyle(.plain).font(.subheadline).frame(minHeight: 44)
            }
        } else {
            regularSermonHeading(week)
        }
    }

    private func regularSermonHeading(_ week: SermonWeek) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(week.date).font(.caption.weight(.medium)).foregroundStyle(.secondary)
            Text(week.title).font(.largeTitle.bold()).fixedSize(horizontal: false, vertical: true)
                .accessibilityAddTraits(.isHeader)
                .accessibilityIdentifier("sermon-title")
            Text("\(week.scripture) · \(week.speaker)")
                .font(.subheadline).foregroundStyle(.secondary)
            HStack {
                Text(reviewLabel).font(.caption.weight(.medium))
                    .foregroundStyle(Brand.accent)
                    .padding(.horizontal, 10).padding(.vertical, 6)
                    .background(Brand.accent.opacity(0.10), in: Capsule())
                Spacer()
                Button("证道大纲", systemImage: "list.bullet.rectangle") { sheet = .outline }
                    .font(.subheadline.weight(.medium)).frame(minHeight: 44)
                    .buttonStyle(.plain).foregroundStyle(.primary)
            }
        }
    }

    private var reviewLabel: String {
        switch model.selectedTrack?.scope {
        case "full_reviewed": return "已审校音频"
        case "full_candidate": return "整篇试听 · 待现场验收"
        default: return "中文片段试听"
        }
    }

    @ViewBuilder private var downloadControl: some View {
        HStack(spacing: 10) {
            switch model.currentDownload {
            case .downloading:
                ProgressView().controlSize(.small)
                Text("正在下载，请保持 App 打开").font(.footnote)
                Spacer()
                Button("取消") { model.cancelDownload() }.frame(minHeight: 44)
            case .checking:
                ProgressView().controlSize(.small)
                Text("正在检查离线音频…").font(.footnote)
            case .ready:
                Label(model.usingOfflineAudio ? "正在使用已下载音频" : "已下载，可离线收听", systemImage: "checkmark.circle.fill")
                    .font(.footnote).foregroundStyle(Brand.accent)
                    .accessibilityIdentifier("download-status")
                Spacer()
                if !model.usingOfflineAudio {
                    Button("使用离线版") { Task { await model.retryAudio() } }.font(.footnote).frame(minHeight: 44)
                        .accessibilityIdentifier("use-offline-audio")
                }
            case .absent:
                Label("提前下载，现场可离线收听", systemImage: "arrow.down.circle").font(.footnote)
                Spacer()
                Button("下载本篇") { model.downloadSelected() }.buttonStyle(.bordered).frame(minHeight: 44)
                    .accessibilityIdentifier("download-audio")
            case .failed(let reason):
                VStack(alignment: .leading, spacing: 4) {
                    Label("尚未完成下载", systemImage: "exclamationmark.circle").font(.footnote)
                    Text(reason).font(.caption).foregroundStyle(.secondary)
                }
                Spacer()
                Button("重新下载") { model.downloadSelected() }.frame(minHeight: 44)
                    .accessibilityIdentifier("download-audio")
            }
        }.padding(16).frame(maxWidth: .infinity, alignment: .leading)
            .background(Brand.surface, in: RoundedRectangle(cornerRadius: 24, style: .continuous))
    }

    private func resumeCard(_ saved: ResumePosition) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            Label("上次听到 \(PlaybackTime.format(saved.position))", systemImage: "clock.arrow.circlepath")
                .font(.headline)
                .accessibilityIdentifier("resume-position")
            Text("恢复位置与微调后，请按现场时间手动对齐。")
                .font(.footnote).foregroundStyle(.secondary)
            HStack {
                Button("恢复位置") { playback.restore() }.buttonStyle(.borderedProminent)
                    .accessibilityIdentifier("restore-position")
                Button("从头开始") { playback.restart() }.buttonStyle(.bordered)
            }.disabled(!playback.isReady)
        }.padding(18).frame(maxWidth: .infinity, alignment: .leading)
            .background(Brand.surface, in: RoundedRectangle(cornerRadius: 24, style: .continuous))
    }

    private func currentSubtitle(_ track: SermonTrack) -> some View {
        let cue = track.cue(at: playback.position) ?? (playback.position < (track.cues.first?.start ?? 0) ? track.cues.first : nil)
        let next = track.cues.first { $0.start > max(playback.position, cue?.start ?? -1) }
        return VStack(alignment: .leading, spacing: 20) {
            HStack {
                Label(playback.isPlaying ? "正在收听" : "当前字幕", systemImage: "waveform")
                    .font(.subheadline.weight(.semibold)).foregroundStyle(Brand.accent)
                Spacer()
                if let cue, let index = track.cues.firstIndex(of: cue) {
                    Text("\(index + 1) / \(track.cues.count)")
                        .font(.caption.monospacedDigit()).foregroundStyle(.secondary)
                }
            }
            Text(cue?.text ?? (playback.position >= playback.duration ? "已收听完毕" : "等待下一段字幕…"))
                .font(.system(size: readingSize, weight: .medium)).lineSpacing(readingSize * 0.24)
                .frame(maxWidth: .infinity, alignment: .leading)
                .fixedSize(horizontal: false, vertical: true)
                .accessibilityLabel("当前字幕")
                .accessibilityValue(cue?.text ?? "暂无字幕")
                .accessibilityIdentifier("current-subtitle")
            if let next {
                Text("接下来 · \(next.text)").font(.body).foregroundStyle(.secondary)
                    .lineLimit(2).lineSpacing(4)
            }
            Text("字幕随中文音频更新").font(.caption2).foregroundStyle(.secondary)
        }.padding(20).frame(maxWidth: .infinity, alignment: .leading)
            .background(Brand.surface, in: RoundedRectangle(cornerRadius: 28, style: .continuous))
    }

    private func transcript(_ track: SermonTrack) -> some View {
        LazyVStack(alignment: .leading, spacing: 22) {
            Text("点击时间定位；正文可直接阅读。")
                .font(.footnote).foregroundStyle(.secondary)
            ForEach(Array(track.cues.enumerated()), id: \.offset) { index, cue in
                VStack(alignment: .leading, spacing: 8) {
                    Button(PlaybackTime.format(cue.start)) { playback.jump(to: cue.start) }
                        .font(.caption.monospacedDigit()).buttonStyle(.bordered)
                        .frame(minHeight: 44)
                        .accessibilityLabel("跳转至 \(PlaybackTime.format(cue.start))")
                        .accessibilityIdentifier("subtitle-cue-\(index)")
                        .disabled(!playback.isReady)
                    Text(cue.text).font(.title3).lineSpacing(7).textSelection(.enabled)
                        .fixedSize(horizontal: false, vertical: true)
                }
                .padding(18).frame(maxWidth: .infinity, alignment: .leading)
                .background(cue.start <= playback.position && playback.position < cue.end ? Brand.accent.opacity(0.13) : Color.clear,
                            in: RoundedRectangle(cornerRadius: 22, style: .continuous))
                .id("cue-\(index)")
            }
        }
    }

    private func footer(_ week: SermonWeek) -> some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("请戴好耳机，在约定的证道起点开始播放；中途加入请用“定位 / 精调”手动对齐。")
            Text("AI 合成中文配音与整理文字 · 独立个人项目")
            DisclosureGroup("来源与内容说明") {
                VStack(alignment: .leading, spacing: 12) {
                    if let notice = week.audioNotice { Text(notice) }
                    Text("与 Mariners Church 无隶属或背书关系。")
                    if let url = URL(string: week.sourceUrl) {
                        Link("英文原视频 ↗", destination: url).frame(minHeight: 44)
                    }
                }.padding(.top, 10).frame(maxWidth: .infinity, alignment: .leading)
            }
        }.font(.caption).foregroundStyle(.secondary).lineSpacing(4)
    }
}

private enum ListeningSheet: String, Identifiable {
    case weeks, precision, outline, about
    var id: String { rawValue }
}

private struct BrandTitle: View {
    var body: some View {
        HStack(spacing: 9) {
            Text("同").font(.system(size: 20, weight: .medium, design: .serif))
                .foregroundStyle(Brand.sage).frame(width: 32, height: 32)
                .background(Brand.ink, in: RoundedRectangle(cornerRadius: 9))
            VStack(alignment: .leading, spacing: 1) {
                Text("同行").font(.headline)
                Text("证道中文听译").font(.caption2).foregroundStyle(.secondary)
            }
        }.accessibilityElement(children: .combine)
    }
}

private struct WeekSheet: View {
    @ObservedObject var model: AppModel
    @Environment(\.dismiss) private var dismiss
    var body: some View {
        NavigationStack {
            ScrollView {
                LazyVStack(spacing: 0) {
                    ForEach(model.weeks) { week in
                        Button {
                            dismiss()
                            Task { await model.select(week: week) }
                        } label: {
                            HStack {
                                VStack(alignment: .leading, spacing: 7) {
                                    Text(week.title).font(.headline)
                                    Text("\(week.date) · \(week.speaker)").font(.subheadline).foregroundStyle(.secondary)
                                }
                                Spacer()
                                if week.id == model.selectedWeek?.id { Image(systemName: "checkmark") }
                            }
                            .padding(20).frame(maxWidth: .infinity, minHeight: 72, alignment: .leading)
                            .contentShape(Rectangle())
                        }
                        .buttonStyle(.plain)
                        .accessibilityLabel("\(week.title)，\(week.date)")
                        Divider().padding(.horizontal, 20)
                    }
                }
            }.navigationTitle("选择证道")
                .toolbar { ToolbarItem(placement: .confirmationAction) { Button("完成") { dismiss() } } }
        }
        #if os(macOS)
        .frame(minWidth: 400, minHeight: 480)
        #endif
    }
}

private struct PrecisionSheet: View {
    @ObservedObject var playback: PlaybackController
    @Environment(\.dismiss) private var dismiss
    @ViewState private var target = ""
    @ViewState private var validation: String?
    @ViewState private var slider = 0.0
    @ViewState private var dragging = false

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    Text("调整的是中文音频。本 App 不会自动跟随现场视频。")
                        .font(.footnote).foregroundStyle(.secondary)
                }
                Section("播放进度 · 松开后跳转") {
                    Slider(value: $slider, in: 0...max(1, playback.duration)) { editing in
                        dragging = editing
                        if !editing { playback.jump(to: slider) }
                    }.accessibilityLabel("播放进度")
                    Text(PlaybackTime.format(slider)).monospacedDigit()
                    HStack {
                        Button("后退 5 秒") { playback.nudge(-5) }
                        Spacer()
                        Button("前进 5 秒") { playback.nudge(5) }
                    }.buttonStyle(.bordered)
                }
                Section("跳至时间") {
                    HStack {
                        TextField("例如 10:05", text: $target).onSubmit(jump)
                            #if os(iOS)
                            .keyboardType(.numbersAndPunctuation)
                            #endif
                        Button("跳转", action: jump).buttonStyle(.borderedProminent)
                    }
                    if let validation { Text(validation).font(.footnote).foregroundStyle(.secondary) }
                }
                Section("细调四分之一秒") {
                    HStack {
                        Button("后退 0.25 秒") { playback.nudge(-0.25) }
                        Spacer()
                        Button("前进 0.25 秒") { playback.nudge(0.25) }
                    }.buttonStyle(.bordered)
                    Text("累计微调 \(playback.offset, specifier: "%+.2f") 秒").monospacedDigit()
                }
            }
            .formStyle(.grouped)
            .disabled(!playback.isReady)
            .navigationTitle("定位 / 精调")
            .toolbar { ToolbarItem(placement: .confirmationAction) { Button("完成") { dismiss() } } }
            .listeningBottomBar { PlaybackDock(playback: playback) }
        }
        .onAppear { slider = playback.position }
        .onChange(of: playback.position) { _, time in if !dragging { slider = time } }
        #if os(macOS)
        .frame(minWidth: 430, minHeight: 630)
        #endif
    }

    private func jump() {
        guard let seconds = PlaybackTime.parse(target), seconds <= playback.duration else {
            validation = "请输入音频范围内的分:秒，例如 10:05。"
            return
        }
        playback.jump(to: seconds)
        // The transport reports the confirmed position. Keep this field for
        // input errors so an old success label cannot disagree with a nudge.
        validation = nil
    }
}

private struct OutlineSheet: View {
    let week: SermonWeek?
    @ObservedObject var playback: PlaybackController
    @Environment(\.dismiss) private var dismiss
    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 24) {
                    if let summary = week?.summary { Text(summary).font(.body).lineSpacing(6) }
                    ForEach(Array((week?.outline ?? []).enumerated()), id: \.offset) { _, section in
                        VStack(alignment: .leading, spacing: 10) {
                            Text(section.title).font(.headline)
                            ForEach(Array(section.points.enumerated()), id: \.offset) { _, point in
                                Text(point).font(.body).lineSpacing(6)
                            }
                        }
                    }
                    Text(week?.contentReview ?? "AI 整理，供个人跟读参考")
                        .font(.caption).foregroundStyle(.secondary)
                }.padding(22).frame(maxWidth: 680)
            }.navigationTitle("证道大纲")
                .toolbar { ToolbarItem(placement: .confirmationAction) { Button("完成") { dismiss() } } }
                .listeningBottomBar { PlaybackDock(playback: playback) }
        }
        #if os(macOS)
        .frame(minWidth: 430, minHeight: 630)
        #endif
    }
}

private struct AboutSheet: View {
    @ObservedObject var model: AppModel
    @Environment(\.dismiss) private var dismiss
    var body: some View {
        NavigationStack {
            Form {
                if let week = model.selectedWeek {
                    Section("音频版本") {
                        ForEach(week.tracks) { track in
                            Button {
                                dismiss()
                                Task { await model.select(week: week, track: track) }
                            } label: {
                                HStack {
                                    VStack(alignment: .leading, spacing: 5) {
                                        Text(track.label)
                                        Text(track.voiceLabel).font(.caption).foregroundStyle(.secondary)
                                    }
                                    Spacer()
                                    if track.id == model.selectedTrack?.id { Image(systemName: "checkmark") }
                                }
                            }
                            .accessibilityIdentifier("track-option-\(track.id)")
                            .accessibilityValue(track.id == model.selectedTrack?.id ? "已选择" : "未选择")
                        }
                    }
                    Section("内容说明") {
                        Text(week.audioNotice ?? "请以当前音频的审核状态为准。")
                        Text(week.contentReview ?? "AI 整理，供个人跟读参考。")
                    }
                }
                Section("播放与存储") {
                    Button("重新加载当前音频") { dismiss(); Task { await model.retryAudio() } }
                    Button("刷新证道目录") { dismiss(); Task { await model.refresh() } }
                    Text("收听位置保存在本机，按周次与音频版本区分，保留30天。已下载的音频可离线收听。")
                        .font(.footnote).foregroundStyle(.secondary)
                    if let warning = model.playback.storageWarning { Text(warning).font(.footnote) }
                }
                Section("关于同行") {
                    Text("一起听懂，一路同行。")
                    Text("独立个人项目，与 Mariners Church 无隶属或背书关系。AI 合成中文音频与整理文字仅供个人跟读参考。")
                        .font(.footnote).foregroundStyle(.secondary)
                    Link("打开网页版", destination: AppModel.contentOrigin)
                }
            }.formStyle(.grouped).navigationTitle("更多选项")
                .toolbar { ToolbarItem(placement: .confirmationAction) { Button("完成") { dismiss() } } }
        }
        #if os(macOS)
        .frame(minWidth: 430, minHeight: 630)
        #endif
    }
}
