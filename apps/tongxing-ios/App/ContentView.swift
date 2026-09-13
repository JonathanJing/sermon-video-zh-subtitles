import SwiftUI
import TongxingCore

// Explicitly select the iOS 17-compatible property wrapper; newer SDKs also
// export a State macro whose plugin is absent from Command Line Tools.
private typealias ViewState<Value> = SwiftUI.State<Value>

private struct ReadingIdentity: Hashable {
    let weekID: String
    let sourceID: String
    let sourceURL: String
    let trackID: String?
    let audioSHA256: String?

    init?(week: SermonWeek?, track: SermonTrack?) {
        guard let week else { return nil }
        weekID = week.id
        sourceID = week.sourceId
        sourceURL = week.sourceUrl
        trackID = track?.id
        audioSHA256 = track?.sha256
    }
}

struct ContentView: View {
    @ObservedObject private var localization = AppLocalization.shared
    @ObservedObject var model: AppModel
    @ObservedObject private var playback: PlaybackController
    @Environment(\.scenePhase) private var scenePhase
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @Environment(\.dynamicTypeSize) private var typeSize
    @Environment(\.verticalSizeClass) private var verticalSizeClass
    @Environment(\.horizontalSizeClass) private var horizontalSizeClass
    @ScaledMetric(relativeTo: .title2) private var readingSize: CGFloat = 26
    @ViewState private var sheet: ListeningSheet?
    @ViewState private var returnToCurrent = UUID()
    @ViewState private var outlineAnchor: Int?
    @ViewState private var transcriptAnchor: Int?
    @ViewState private var anchorSourceIdentity: ReadingIdentity?

    init(model: AppModel) {
        self.model = model
        self.playback = model.playback
        self._anchorSourceIdentity = ViewState(initialValue: ReadingIdentity(week: model.selectedWeek, track: model.selectedTrack))
    }

    var body: some View {
        GeometryReader { geometry in
            let expanded = geometry.size.width >= 840
                && horizontalSizeClass != .compact && !typeSize.isAccessibilitySize
            Group {
                if expanded {
                    NavigationSplitView(columnVisibility: .constant(.all)) {
                        readingPane
                            .navigationTitle(localization.text("阅读"))
                            .navigationSplitViewColumnWidth(min: 300, ideal: min(380, geometry.size.width * 0.38), max: 420)
                    } detail: {
                        listeningPage(expanded: true)
                            .navigationSplitViewColumnWidth(min: 420, ideal: geometry.size.width * 0.62)
                    }
                    .navigationSplitViewStyle(.balanced)
                } else {
                    NavigationStack { listeningPage(expanded: false) }
                }
            }
            .accessibilityElement(children: .contain)
            .accessibilityIdentifier(expanded ? "duo-layout" : "compact-layout")
            .sheet(item: $sheet) { destination in
                switch destination {
                case .weeks:
                    WeekSheet(model: model)
                        .presentationDetents([.medium, .large]).presentationDragIndicator(.visible)
                case .precision:
                    PrecisionSheet(model: model)
                        .presentationDetents(typeSize.isAccessibilitySize ? [.large] : [.medium, .large])
                        .presentationDragIndicator(.visible)
                case .reading:
                    // The expanded sidebar replaces this presentation. Do not
                    // render a second reading pane during sheet dismissal.
                    if !expanded {
                        NavigationStack {
                            readingPane
                                .navigationTitle(localization.text("阅读"))
                                .toolbar {
                                    ToolbarItem(placement: .confirmationAction) {
                                        Button(localization.text("完成")) { sheet = nil }
                                            .accessibilityIdentifier("close-reading-pane")
                                    }
                                }
                        }
                        .presentationDetents([.large]).presentationDragIndicator(.visible)
                    }
                case .about:
                    AboutSheet(model: model)
                        .presentationDetents([.large]).presentationDragIndicator(.visible)
                }
            }
            .onChange(of: expanded) { _, isExpanded in
                if isExpanded && sheet == .reading { sheet = nil }
            }
        }
        .environment(\.locale, localization.locale)
        .onChange(of: readingIdentity) { _, identity in
            // Reading anchors belong to one week/source, even without audio.
            // Layout and language changes leave these anchors alone.
            outlineAnchor = nil
            transcriptAnchor = nil
            anchorSourceIdentity = identity
        }
        .onChange(of: scenePhase) { _, phase in
            if phase != .active { playback.saveProgress() }
            else { localization.refreshSystemLanguage() }
        }
    }

    private var readingIdentity: ReadingIdentity? {
        ReadingIdentity(week: model.selectedWeek, track: model.selectedTrack)
    }

    private var readingPane: some View {
        ReadingPane(model: model, playback: playback,
                    outlineAnchor: sourceAnchor($outlineAnchor), transcriptAnchor: sourceAnchor($transcriptAnchor),
                    returnToCurrent: returnToCurrent)
            .id(readingIdentity)
    }

    private func sourceAnchor(_ binding: Binding<Int?>) -> Binding<Int?> {
        let identity = readingIdentity
        return Binding(get: {
            anchorSourceIdentity == identity ? binding.wrappedValue : nil
        }, set: { value in
            // Ignore delayed scroll callbacks from the previous source's view.
            guard readingIdentity == identity, anchorSourceIdentity == identity else { return }
            binding.wrappedValue = value
        })
    }

    private func listeningPage(expanded: Bool) -> some View {
        ScrollViewReader { proxy in
            ScrollView {
                VStack(alignment: .leading, spacing: verticalSizeClass == .compact ? 12 : 16) {
                    if let week = model.selectedWeek {
                        sermonHeading(week, expanded: expanded).id("top")
                        if let notice = model.catalogNotice {
                            Label(localization.text(notice), systemImage: "wifi.slash")
                                .font(.footnote).foregroundStyle(.secondary)
                                .accessibilityIdentifier("catalog-notice")
                        }
                        if let error = model.errorMessage {
                            Label(localization.text(error), systemImage: "exclamationmark.circle").font(.footnote)
                        }
                        if let track = model.selectedTrack {
                            if let saved = playback.resumePosition { resumeCard(saved) }
                            currentSubtitle(track).id("current-subtitle-card")
                            AlignmentControls(model: model)
                                .padding(16).frame(maxWidth: .infinity, alignment: .leading)
                                .background(Brand.surface, in: RoundedRectangle(cornerRadius: 24, style: .continuous))
                            downloadControl
                        } else {
                            ContentUnavailableView(localization.text("本周音频尚未准备好"), systemImage: "waveform", description: Text(localization.text("可以先阅读证道大纲。")))
                        }
                        footer(week)
                    } else if model.isLoading {
                        ProgressView(localization.text("正在读取本周证道…")).frame(maxWidth: .infinity, minHeight: 320)
                    } else {
                        ContentUnavailableView {
                            Label(localization.text("暂时无法读取证道"), systemImage: "wifi.exclamationmark")
                        } description: {
                            Text(localization.text(model.errorMessage ?? "首次使用需要网络，下载后可离线收听。"))
                        } actions: {
                            Button(localization.text("重新加载")) { Task { await model.refresh() } }.buttonStyle(.borderedProminent)
                        }.frame(minHeight: 320)
                    }
                }
                .padding(.horizontal, 20)
                .padding(.top, verticalSizeClass == .compact ? 0 : 8).padding(.bottom, 24)
                .frame(maxWidth: 720).frame(maxWidth: .infinity)
            }
            .accessibilityIdentifier("listening-scroll")
            .refreshable { await model.refresh() }
            .onChange(of: returnToCurrent) { _, _ in
                withAnimation(reduceMotion ? nil : .easeInOut(duration: 0.25)) {
                    proxy.scrollTo("current-subtitle-card", anchor: .top)
                }
            }
        }
        .background(Brand.background)
        .listeningBottomBar {
            if model.selectedTrack != nil {
                PlaybackDock(playback: playback, isPreparing: model.isPreparing,
                             precision: { sheet = .precision }, current: { returnToCurrent = UUID() })
                    .accessibilityElement(children: .contain)
                    .accessibilityIdentifier("playback-dock")
            }
        }
        .toolbar {
            ToolbarItem(placement: .principal) { BrandTitle() }
            ToolbarItemGroup(placement: .primaryAction) {
                Button(localization.text("选择证道周次"), systemImage: "calendar") { sheet = .weeks }
                    .labelStyle(.iconOnly).accessibilityIdentifier("choose-sermon")
                Button(localization.text("更多选项"), systemImage: "ellipsis.circle") { sheet = .about }
                    .labelStyle(.iconOnly).accessibilityIdentifier("more-options")
            }
        }
        #if os(iOS)
        .navigationBarTitleDisplayMode(.inline)
        #endif
    }

    @ViewBuilder private func sermonHeading(_ week: SermonWeek, expanded: Bool) -> some View {
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
                if !expanded { readingButton }

            }
        } else {
            regularSermonHeading(week, expanded: expanded)
        }
    }

    private func regularSermonHeading(_ week: SermonWeek, expanded: Bool) -> some View {
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
                if !expanded { readingButton }
            }
        }
    }

    private var readingButton: some View {
        Button(localization.text("阅读"), systemImage: "book") {
            if playback.isPlaying, localization.readingMode == .transcript,
               let track = model.selectedTrack {
                transcriptAnchor = track.cues.firstIndex { $0.start <= playback.position && playback.position < $0.end }
            }
            sheet = .reading
        }
            .font(.subheadline.weight(.medium)).frame(minHeight: 44)
            .buttonStyle(.plain).foregroundStyle(.primary)
            .accessibilityIdentifier("open-reading-pane")
    }

    private var reviewLabel: String {
        switch model.selectedTrack?.scope {
        case "full_reviewed": return localization.text("已审校音频")
        case "full_candidate": return localization.text("整篇试听 · 待现场验收")
        default: return localization.text("中文片段试听")
        }
    }

    @ViewBuilder private var downloadControl: some View {
        HStack(spacing: 10) {
            switch model.currentDownload {
            case .downloading:
                ProgressView().controlSize(.small)
                Text(localization.text("正在下载，请保持 App 打开")).font(.footnote)
                Spacer()
                Button(localization.text("取消")) { model.cancelDownload() }.frame(minHeight: 44)
            case .checking:
                ProgressView().controlSize(.small)
                Text(localization.text("正在检查离线音频…")).font(.footnote)
            case .ready:
                Label(localization.text(model.usingOfflineAudio ? "正在使用已下载音频" : "已下载，可离线收听"), systemImage: "checkmark.circle.fill")
                    .font(.footnote).foregroundStyle(Brand.accent)
                    .accessibilityIdentifier("download-status")
                Spacer()
                if !model.usingOfflineAudio {
                    Button(localization.text("使用离线版")) { Task { await model.retryAudio() } }.font(.footnote).frame(minHeight: 44)
                        .accessibilityIdentifier("use-offline-audio")
                }
            case .absent:
                Label(localization.text("提前下载，现场可离线收听"), systemImage: "arrow.down.circle").font(.footnote)
                Spacer()
                Button(localization.text("下载本篇")) { model.downloadSelected() }.buttonStyle(.bordered).frame(minHeight: 44)
                    .accessibilityIdentifier("download-audio")
            case .failed(let reason):
                VStack(alignment: .leading, spacing: 4) {
                    Label(localization.text("尚未完成下载"), systemImage: "exclamationmark.circle").font(.footnote)
                    Text(localization.text(reason)).font(.caption).foregroundStyle(.secondary)
                }
                Spacer()
                Button(localization.text("重新下载")) { model.downloadSelected() }.frame(minHeight: 44)
                    .accessibilityIdentifier("download-audio")
            }
        }.padding(16).frame(maxWidth: .infinity, alignment: .leading)
            .background(Brand.surface, in: RoundedRectangle(cornerRadius: 24, style: .continuous))
    }

    private func resumeCard(_ saved: ResumePosition) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            Label(localization.text("上次听到 {time}", ["time": PlaybackTime.format(saved.position)]), systemImage: "clock.arrow.circlepath")
                .font(.headline)
                .accessibilityIdentifier("resume-position")
            Text(localization.text("恢复位置与微调后，请按现场时间手动对齐。"))
                .font(.footnote).foregroundStyle(.secondary)
            HStack {
                Button(localization.text("恢复位置")) { playback.restore() }.buttonStyle(.borderedProminent)
                    .accessibilityIdentifier("restore-position")
                Button(localization.text("从头开始")) { playback.restart() }.buttonStyle(.bordered)
            }.disabled(!playback.isReady)
        }.padding(18).frame(maxWidth: .infinity, alignment: .leading)
            .background(Brand.surface, in: RoundedRectangle(cornerRadius: 24, style: .continuous))
    }

    private func currentSubtitle(_ track: SermonTrack) -> some View {
        let cue = track.cue(at: playback.position) ?? (playback.position < (track.cues.first?.start ?? 0) ? track.cues.first : nil)
        let next = track.cues.first { $0.start > max(playback.position, cue?.start ?? -1) }
        return VStack(alignment: .leading, spacing: 20) {
            HStack {
                Label(localization.text(playback.isPlaying ? "正在收听" : "当前字幕"), systemImage: "waveform")
                    .font(.subheadline.weight(.semibold)).foregroundStyle(Brand.accent)
                Spacer()
                if let cue, let index = track.cues.firstIndex(of: cue) {
                    Text("\(index + 1) / \(track.cues.count)")
                        .font(.caption.monospacedDigit()).foregroundStyle(.secondary)
                }
            }
            sourceText(cue?.text ?? localization.text(playback.position >= playback.duration ? "已收听完毕" : "等待下一段字幕…"),
                       language: cue == nil ? localization.language.rawValue : "zh-Hans")
                .font(.system(size: readingSize, weight: .medium)).lineSpacing(readingSize * 0.24)
                .frame(maxWidth: .infinity, alignment: .leading)
                .fixedSize(horizontal: false, vertical: true)
                .accessibilityLabel(localization.text("当前字幕"))
                .accessibilityValue(sourceText(cue?.text ?? localization.text("暂无字幕"), language: cue == nil ? localization.language.rawValue : "zh-Hans"))
                .accessibilityIdentifier("current-subtitle")
            if let next {
                (Text(localization.text("接下来")) + Text(" · ") + sourceText(next.text, language: "zh-Hans"))
                    .font(.body).foregroundStyle(.secondary)
                    .lineLimit(2).lineSpacing(4)
            }
            Text(localization.text("字幕随中文音频更新")).font(.caption2).foregroundStyle(.secondary)
        }.padding(20).frame(maxWidth: .infinity, alignment: .leading)
            .background(Brand.surface, in: RoundedRectangle(cornerRadius: 28, style: .continuous))
    }

    private func footer(_ week: SermonWeek) -> some View {
        VStack(alignment: .leading, spacing: 12) {
            Text(localization.text("请戴好耳机，在约定的证道起点开始播放；中途加入请用“定位 / 精调”手动对齐。"))
            Text(localization.text("AI 合成中文配音与整理文字 · 独立个人项目"))
            DisclosureGroup(localization.text("来源与内容说明")) {
                VStack(alignment: .leading, spacing: 12) {
                    if let notice = week.audioNotice { Text(notice) }
                    Text(localization.text("与 Mariners Church 无隶属或背书关系。"))
                    if let url = URL(string: week.sourceUrl) {
                        Link(localization.text("英文原视频 ↗"), destination: url).frame(minHeight: 44)
                    }
                }.padding(.top, 10).frame(maxWidth: .infinity, alignment: .leading)
            }
        }.font(.caption).foregroundStyle(.secondary).lineSpacing(4)
    }
}

private struct ReadingPane: View {
    @ObservedObject private var localization = AppLocalization.shared
    @ObservedObject var model: AppModel
    @ObservedObject var playback: PlaybackController
    @Binding var outlineAnchor: Int?
    @Binding var transcriptAnchor: Int?
    let returnToCurrent: UUID

    private var mode: Binding<AppReadingMode> {
        Binding(get: { localization.readingMode }, set: { value in
            // Opening transcript while playing locates once. Playback updates
            // never write the reading anchor, so manual reading stays put.
            if value == .transcript, localization.readingMode != .transcript, playback.isPlaying {
                showCurrentCue()
            }
            localization.setReadingMode(value)
        })
    }

    var body: some View {
        VStack(spacing: 12) {
            Picker(localization.text("阅读内容"), selection: mode) {
                Text(localization.text("证道大纲")).tag(AppReadingMode.outline)
                Text(localization.text("字幕全文")).tag(AppReadingMode.transcript)
            }
            .pickerStyle(.segmented)
            .accessibilityIdentifier("reading-mode-picker")
            .padding(.horizontal, 20).padding(.top, 12)
            if let warning = localization.readingStorageWarning {
                Text(localization.text(warning)).font(.footnote).foregroundStyle(.secondary)
            }
            if localization.readingMode == .outline {
                ScrollViewReader { proxy in
                    ScrollView {
                        outline
                            .padding(20).frame(maxWidth: 680, alignment: .leading)
                            .frame(maxWidth: .infinity, alignment: .leading)
                    }
                    .scrollPosition(id: preservedAnchor($outlineAnchor), anchor: .top)
                    .accessibilityIdentifier("outline-reading-scroll")
                    .task {
                        await Task.yield()
                        guard !Task.isCancelled else { return }
                        restoreReadingAnchor(outlineAnchor, using: proxy)
                    }
                }
            } else {
                VStack(spacing: 0) {
                    Button(localization.text("回到当前句"), systemImage: "text.line.first.and.arrowtriangle.forward") {
                        showCurrentCue()
                    }
                    .font(.footnote).frame(minHeight: 44)
                    .accessibilityIdentifier("reader-current-cue")
                    .disabled(model.selectedTrack == nil)
                    ScrollViewReader { proxy in
                        ScrollView {
                            if let track = model.selectedTrack {
                                transcript(track)
                                    .padding(20).frame(maxWidth: 680, alignment: .leading)
                                    .frame(maxWidth: .infinity, alignment: .leading)
                            }
                        }
                        .scrollPosition(id: preservedAnchor($transcriptAnchor), anchor: .top)
                        .accessibilityIdentifier("transcript-reading-scroll")
                        .task {
                            await Task.yield()
                            guard !Task.isCancelled else { return }
                            restoreReadingAnchor(transcriptAnchor, using: proxy)
                        }
                    }
                }
            }
        }
        .background(Brand.background)
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("reading-pane")
        .onChange(of: returnToCurrent) { _, _ in
            if localization.readingMode == .transcript { showCurrentCue() }
        }
    }

    private func restoreReadingAnchor(_ anchor: Int?, using proxy: ScrollViewProxy) {
        guard let anchor else { return }
        // Restore once after yielding out of the mounting update. Synchronous
        // onAppear can run before the scroll view resolves its layout targets.
        proxy.scrollTo(anchor, anchor: .top)
    }

    // During replacement of the sheet by a column, ScrollView can emit nil as
    // its targets disappear. That teardown event must not erase a saved anchor.
    private func preservedAnchor(_ binding: Binding<Int?>) -> Binding<Int?> {
        Binding(get: { binding.wrappedValue }, set: { value in
            if let value { binding.wrappedValue = value }
        })
    }

    private func showCurrentCue() {
        guard let track = model.selectedTrack,
              let index = track.cues.firstIndex(where: { $0.start <= playback.position && playback.position < $0.end }) else { return }
        transcriptAnchor = index
    }

    private var outline: some View {
        LazyVStack(alignment: .leading, spacing: 24) {
            if let summary = model.selectedWeek?.summary {
                Text(summary).font(.body).lineSpacing(6).textSelection(.enabled)
                    .id(-1)
            }
            if model.selectedWeek?.outline?.isEmpty != false {
                Text(localization.text("本篇暂无大纲")).font(.body).foregroundStyle(.secondary)
                    .id(-2)
            }
            ForEach(Array((model.selectedWeek?.outline ?? []).enumerated()), id: \.offset) { index, section in
                VStack(alignment: .leading, spacing: 10) {
                    Text(section.title).font(.headline).accessibilityAddTraits(.isHeader)
                    ForEach(Array(section.points.enumerated()), id: \.offset) { _, point in
                        Text(point).font(.body).lineSpacing(6).textSelection(.enabled)
                    }
                }
                .accessibilityElement(children: .contain)
                .accessibilityIdentifier("outline-section-\(index)")
            }
            Text(model.selectedWeek?.contentReview ?? localization.text("AI 整理，供个人跟读参考"))
                .font(.caption).foregroundStyle(.secondary).id(-3)
        }
        .scrollTargetLayout()
    }

    private func transcript(_ track: SermonTrack) -> some View {
        let bilingual = model.selectedWeek?.bilingualCueRows(for: track)
        let rows = bilingual?.rows ?? []
        return LazyVStack(alignment: .leading, spacing: 22) {
            VStack(alignment: .leading, spacing: 10) {
                Text(localization.text("点击时间定位；正文可直接阅读。"))
                    .font(.footnote).foregroundStyle(.secondary)
                if bilingual?.hasEnglish == true {
                    Text(localization.text("中文优先阅读；点击段末的「英文对照」展开参考。"))
                        .font(.footnote).foregroundStyle(.secondary)
                }
                if bilingual?.missingEnglish != false {
                    Text(localization.text(bilingual?.hasEnglish == true ? "部分段落未提供可关联的英文原文，保留中文显示。" : "英文原文暂缺，保留中文显示。"))
                        .font(.footnote).foregroundStyle(.secondary)
                        .accessibilityIdentifier("transcript-missing-english")
                }
            }.id(-1)
            ForEach(rows) { row in
                let cue = row.cue
                VStack(alignment: .leading, spacing: 8) {
                    Button(PlaybackTime.format(cue.start)) { playback.jump(to: cue.start) }
                        .font(.caption.monospacedDigit()).buttonStyle(.bordered)
                        .frame(minHeight: 44)
                        .accessibilityLabel(localization.text("跳转至 {time}", ["time": PlaybackTime.format(cue.start)]))
                        .accessibilityIdentifier("subtitle-cue-\(row.index)")
                        .disabled(!playback.isReady)
                    sourceText(cue.text, language: "zh-Hans").font(.title3).lineSpacing(7).textSelection(.enabled)
                        .fixedSize(horizontal: false, vertical: true)
                    if let english = row.english {
                        DisclosureGroup {
                            sourceText(english, language: "en").font(.body).lineSpacing(5).textSelection(.enabled)
                                .fixedSize(horizontal: false, vertical: true)
                                .environment(\.locale, Locale(identifier: "en"))
                                .accessibilityIdentifier("transcript-english-\(row.index)")
                        } label: {
                            Text(localization.text("英文对照"))
                                .font(.subheadline).frame(minHeight: 44)
                                .accessibilityIdentifier("transcript-english-toggle-\(row.index)")
                        }
                        .id("\(model.selectedWeek?.id ?? "")-\(track.id)-english-\(row.index)")
                        .foregroundStyle(.secondary).padding(.top, 6)
                    }
                }
                .padding(18).frame(maxWidth: .infinity, alignment: .leading)
                .background(cue.start <= playback.position && playback.position < cue.end ? Brand.accent.opacity(0.13) : Color.clear,
                            in: RoundedRectangle(cornerRadius: 22, style: .continuous))
            }
        }
        // Match scrollPosition's Int binding to ForEach's actual row identity.
        // A nested String .id does not replace the lazy layout's Int target ID.
        .scrollTargetLayout()
    }

}

/// Keep source passages in their supplied language, including accessibility.
private func sourceText(_ value: String, language: String) -> Text {
    var text = AttributedString(value)
    text.languageIdentifier = language
    return Text(text)
}

private struct AlignmentControls: View {
    @ObservedObject var model: AppModel
    @ObservedObject private var playback: PlaybackController
    @ObservedObject private var localization = AppLocalization.shared

    init(model: AppModel) {
        self.model = model
        self.playback = model.playback
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            Button {
                if model.alignmentBusy { model.cancelAlignment() }
                else { model.startAlignment() }
            } label: {
                Label(localization.text(model.alignmentBusy ? "取消对齐" : "听现场并对齐"),
                      systemImage: model.alignmentBusy ? "stop.circle" : "waveform.badge.mic")
                    .fixedSize(horizontal: false, vertical: true)
            }
            .buttonStyle(.bordered).frame(minHeight: 44)
            .disabled(!model.alignmentAvailable && !model.alignmentBusy)
            .accessibilityIdentifier("align-live-audio")
            Text(localization.text(model.alignmentStatus, ["time": model.alignmentPosition.map(PlaybackTime.format) ?? ""]))
                .font(.footnote).foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true)
                .accessibilityIdentifier("alignment-status")
        }
    }
}

private enum ListeningSheet: String, Identifiable {
    case weeks, precision, reading, about
    var id: String { rawValue }
}

private struct BrandTitle: View {
    @ObservedObject private var localization = AppLocalization.shared
    @Environment(\.colorScheme) private var colorScheme

    private var brandMark: Image {
        #if SWIFT_PACKAGE
        Image(colorScheme == .dark ? "BrandMark-dark" : "BrandMark", bundle: .module)
        #else
        Image("BrandMark")
        #endif
    }

    var body: some View {
        HStack(spacing: 9) {
            brandMark.resizable().interpolation(.high)
                .frame(width: 32, height: 32)
                .clipShape(RoundedRectangle(cornerRadius: 9))
                .accessibilityHidden(true)
            VStack(alignment: .leading, spacing: 1) {
                Text(localization.text("同行")).font(.headline)
                Text(localization.text("证道中文听译")).font(.caption2).foregroundStyle(.secondary)
            }
        }.accessibilityElement(children: .combine)
    }
}

private struct WeekSheet: View {
    @ObservedObject private var localization = AppLocalization.shared
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
            }.navigationTitle(localization.text("选择证道"))
                .toolbar { ToolbarItem(placement: .confirmationAction) { Button(localization.text("完成")) { dismiss() } } }
        }
        .environment(\.locale, localization.locale)
        #if os(macOS)
        .frame(minWidth: 400, minHeight: 480)
        #endif
    }
}

private struct PrecisionSheet: View {
    @ObservedObject private var localization = AppLocalization.shared
    @ObservedObject var model: AppModel
    @ObservedObject var playback: PlaybackController
    @Environment(\.dismiss) private var dismiss
    @ViewState private var target = ""
    @ViewState private var validation: String?
    @ViewState private var slider = 0.0
    @ViewState private var dragging = false

    init(model: AppModel) {
        self.model = model
        self.playback = model.playback
    }

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    Text(localization.text("调整的是中文音频。现场识别仅用于同一录音，每次识别成功后定位一次。"))
                        .font(.footnote).foregroundStyle(.secondary)
                }
                Section(localization.text("现场对齐")) { AlignmentControls(model: model) }
                Section(localization.text("播放进度 · 松开后跳转")) {
                    Slider(value: $slider, in: 0...max(1, playback.duration)) { editing in
                        dragging = editing
                        if !editing { playback.jump(to: slider) }
                    }.accessibilityLabel(localization.text("播放进度"))
                    Text(PlaybackTime.format(slider)).monospacedDigit()
                    HStack {
                        Button(localization.text("后退 5 秒")) { playback.nudge(-5) }
                        Spacer()
                        Button(localization.text("前进 5 秒")) { playback.nudge(5) }
                    }.buttonStyle(.bordered)
                }.disabled(!playback.isReady)
                Section(localization.text("跳至时间")) {
                    HStack {
                        TextField(localization.text("例如 10:05"), text: $target).onSubmit(jump)
                            #if os(iOS)
                            .keyboardType(.numbersAndPunctuation)
                            #endif
                        Button(localization.text("跳转"), action: jump).buttonStyle(.borderedProminent)
                    }
                    if let validation { Text(localization.text(validation)).font(.footnote).foregroundStyle(.secondary) }
                }.disabled(!playback.isReady)
                Section(localization.text("细调四分之一秒")) {
                    HStack {
                        Button(localization.text("后退 0.25 秒")) { playback.nudge(-0.25) }
                        Spacer()
                        Button(localization.text("前进 0.25 秒")) { playback.nudge(0.25) }
                    }.buttonStyle(.bordered)
                    Text(localization.text("累计微调 {seconds} 秒", ["seconds": String(format: "%+.2f", locale: localization.locale, playback.offset)])).monospacedDigit()
                }.disabled(!playback.isReady)
            }
            .formStyle(.grouped)
            .navigationTitle(localization.text("定位 / 精调"))
            .toolbar { ToolbarItem(placement: .confirmationAction) { Button(localization.text("完成")) { dismiss() } } }
            .listeningBottomBar { PlaybackDock(playback: playback) }
        }
        .environment(\.locale, localization.locale)
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

private struct AboutSheet: View {
    @ObservedObject private var localization = AppLocalization.shared
    @ObservedObject var model: AppModel
    @Environment(\.dismiss) private var dismiss
    var body: some View {
        NavigationStack {
            Form {
                if let week = model.selectedWeek {
                    Section(localization.text("音频版本")) {
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
                            .accessibilityValue(localization.text(track.id == model.selectedTrack?.id ? "已选择" : "未选择"))
                        }
                    }
                    Section(localization.text("内容说明")) {
                        Text(week.audioNotice ?? localization.text("请以当前音频的审核状态为准。"))
                        Text(week.contentReview ?? localization.text("AI 整理，供个人跟读参考。"))
                    }
                }
                Section(localization.text("播放与存储")) {
                    Button(localization.text("重新加载当前音频")) { dismiss(); Task { await model.retryAudio() } }
                    Button(localization.text("刷新证道目录")) { dismiss(); Task { await model.refresh() } }
                    Text(localization.text("收听位置保存在本机，按周次与音频版本区分，保留30天。已下载的音频可离线收听。"))
                        .font(.footnote).foregroundStyle(.secondary)
                    if let warning = model.playback.storageWarning { Text(localization.text(warning)).font(.footnote) }
                }
                Section(localization.text("界面语言")) {
                    Picker(localization.text("界面语言"), selection: Binding(get: { localization.preference }, set: { localization.setPreference($0) })) {
                        Text(localization.text("跟随系统")).tag(AppLanguage.system)
                        Text("简体中文").tag(AppLanguage.simplifiedChinese)
                        Text("English").tag(AppLanguage.english)
                    }
                    .accessibilityIdentifier("interface-language")
                    Text(localization.text("界面语言不会更换音轨；证道内容保留其提供的语言。"))
                        .font(.footnote).foregroundStyle(.secondary)
                    if let warning = localization.storageWarning {
                        Text(localization.text(warning)).font(.footnote).foregroundStyle(.secondary)
                    }
                }
                Section(localization.text("关于同行")) {
                    Text(localization.text("一起听懂，一路同行。"))
                    Text(localization.text("独立个人项目，与 Mariners Church 无隶属或背书关系。AI 合成中文音频与整理文字仅供个人跟读参考。"))
                        .font(.footnote).foregroundStyle(.secondary)
                    NavigationLink { PrivacySupportView() } label: {
                        Label(localization.text("隐私与支持"), systemImage: "hand.raised")
                    }.accessibilityIdentifier("privacy-support")
                    Link(localization.text("打开网页版"), destination: AppModel.contentOrigin)
                }
            }.formStyle(.grouped).navigationTitle(localization.text("更多选项"))
                .toolbar { ToolbarItem(placement: .confirmationAction) { Button(localization.text("完成")) { dismiss() } } }
        }
        .environment(\.locale, localization.locale)
        #if os(macOS)
        .frame(minWidth: 430, minHeight: 630)
        #endif
    }
}
