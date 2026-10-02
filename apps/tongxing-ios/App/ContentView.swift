import AVKit
import CryptoKit
import SwiftUI
import TongxingCore
import TongxingInfrastructure
import WebKit

// Explicitly select the iOS 17-compatible property wrapper; newer SDKs also
// export a State macro whose plugin is absent from Command Line Tools.
private typealias ViewState<Value> = SwiftUI.State<Value>

private struct ToolbarVerticalEdgeReader<Content: View>: View {
    let content: (HorizontalEdge?) -> Content

    var body: some View {
        #if os(iOS) && canImport(SwiftUI, _version: 8.0.85)
        if #available(iOS 27.1, macOS 27.1, *) {
            CurrentToolbarVerticalEdge(content: content)
        } else {
            content(nil)
        }
        #else
        content(nil)
        #endif
    }
}

#if os(iOS) && canImport(SwiftUI, _version: 8.0.85)
@available(iOS 27.1, macOS 27.1, *)
private struct CurrentToolbarVerticalEdge<Content: View>: View {
    @Environment(\.toolbarVerticalEdge) private var edge
    let content: (HorizontalEdge?) -> Content

    var body: some View { content(edge) }
}
#endif

struct ContentView: View {
    @ObservedObject private var localization = AppLocalization.shared
    @ObservedObject var model: AppModel
    @ObservedObject private var playback: PlaybackController
    @Environment(\.scenePhase) private var scenePhase
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @Environment(\.dynamicTypeSize) private var typeSize
    @Environment(\.verticalSizeClass) private var verticalSizeClass
    @ScaledMetric(relativeTo: .title2) private var readingSize: CGFloat = 26
    @ViewState private var sheet: ListeningSheet?
    @ViewState private var returnToCurrent = UUID()
    @ViewState private var locateConfirmation: Double?
    @ViewState private var showingPlaybackMore = false
    @ViewState private var showingAlignmentFailure = false
    @ViewState private var playbackMoreButtonFrame: CGRect = .null
    @ViewState private var playbackMorePanelSize = CGSize(width: 320, height: 176)
    @ViewState private var playbackMorePlacement: PlaybackDockPlacement = .bottom

    init(model: AppModel) {
        self.model = model
        self.playback = model.playback
    }

    var body: some View {
        GeometryReader { geometry in
            let controlRegion = dockControlRegion(in: geometry)
            listeningNavigation(
                controlRegion: controlRegion,
                usesTrailingDock: controlRegion.width >= 700 && controlRegion.height < 700
            )
            .overlay { playbackMoreOverlay }
        }
        .environment(\.locale, localization.locale)
        .task(id: model.publishedTranscriptSelectionKey) {
            await model.loadSelectedPublishedTranscript()
        }
        .task(id: locateConfirmation) {
            guard locateConfirmation != nil else { return }
            try? await Task.sleep(for: .seconds(4))
            guard !Task.isCancelled else { return }
            locateConfirmation = nil
        }
        .onChange(of: model.alignmentFailure?.id) { _, failure in
            if failure != nil { showingPlaybackMore = false }
            updateAlignmentFailurePresentation()
        }
        .onChange(of: sheet) { _, destination in
            if destination != nil { showingAlignmentFailure = false }
        }
        .alert(localization.text("听音对齐未完成"), isPresented: $showingAlignmentFailure,
               presenting: model.alignmentFailure) { _ in
            Button(localization.text("按英文找位置")) {
                model.dismissAlignmentFailure()
                DispatchQueue.main.async { sheet = .locate }
            }
            if model.alignmentAvailable {
                Button(localization.text("重试对齐")) { model.startAlignment() }
            }
            Button(localization.text("关闭"), role: .cancel) { model.dismissAlignmentFailure() }
        } message: { failure in Text(localization.text(failure.message)) }
        .onChange(of: model.selectedPageID) { _, _ in locateConfirmation = nil }
        .onChange(of: scenePhase) { _, phase in
            if phase != .active { playback.saveProgress() }
            else { localization.refreshSystemLanguage() }
            updateAlignmentFailurePresentation()
        }
    }

    private func updateAlignmentFailurePresentation() {
        showingAlignmentFailure = model.alignmentFailure != nil && sheet == nil && scenePhase == .active
    }

    private func listeningNavigation(controlRegion: CGRect, usesTrailingDock: Bool) -> some View {
        NavigationStack {
            ToolbarVerticalEdgeReader { verticalBarEdge in
                let usesSystemVerticalBar = verticalBarEdge != nil
                return ScrollViewReader { proxy in
                ScrollView {
                    VStack(alignment: .leading, spacing: verticalSizeClass == .compact ? 12 : 16) {
                        if model.selectedWeek == nil && model.selectedMultilingualPage == nil {
                            HStack { Spacer(); appLanguageMenu }
                        }
                        if let week = model.selectedWeek {
                            sermonHeading(week).id("top")
                            if let notice = model.catalogNotice {
                                Label(localization.text(notice), systemImage: "wifi.slash")
                                    .font(.footnote).foregroundStyle(.secondary)
                                    .accessibilityIdentifier("catalog-notice")
                            }
                            if let error = model.errorMessage {
                                Label(localization.text(error), systemImage: "exclamationmark.circle").font(.footnote)
                            }
                            if let track = model.selectedTrack {
                                if let saved = playback.resumePosition {
                                    resumeCard(saved)
                                }
                                playbackStatusDetail
                                Picker(localization.text("收听内容"), selection: $model.display) {
                                    ForEach(AppModel.ListeningDisplay.allCases, id: \.self) { Text(localization.text($0.rawValue)).tag($0) }
                                }.pickerStyle(.segmented).accessibilityIdentifier("listening-display")
                                if model.display == .current {
                                    currentSubtitle(track)
                                }
                                else { transcript(track) }
                                locateConfirmationView
                                Text(localization.text(model.alignmentDisplayStatus, ["time": model.alignmentPosition.map(PlaybackTime.format) ?? ""]))
                                    .font(.footnote).foregroundStyle(.secondary)
                                    .fixedSize(horizontal: false, vertical: true)
                                    .accessibilityIdentifier("alignment-status")
                                englishLocateEntry
                                downloadControl
                            } else {
                                ContentUnavailableView(localization.text("本周音频尚未准备好"), systemImage: "waveform", description: Text(localization.text("可以先阅读证道大纲。")))
                            }
                            footer(week)
                        } else if let page = model.selectedMultilingualPage {
                            VStack(alignment: .leading, spacing: verticalSizeClass == .compact ? 8 : 12) {
                                HStack {
                                    Text(localization.text("已发布页面"))
                                        .font(.caption.weight(.medium)).foregroundStyle(.secondary)
                                    Spacer(minLength: 8)
                                    appLanguageMenu
                                }
                                SermonHeadingView(heading: model.heading(for: page), date: page.date,
                                                  titleFont: .largeTitle.bold(), identifier: "published-page")
                                languageButton
                                if model.fullVideoURL != nil || model.selectedAudioLanguageName != nil {
                                    if typeSize.isAccessibilitySize {
                                        VStack(alignment: .leading, spacing: 4) {
                                            publishedVideoButton
                                                .frame(maxWidth: .infinity, alignment: .leading)
                                            publishedAudioLocaleLabel
                                        }
                                    } else {
                                        HStack(spacing: 12) {
                                            publishedVideoButton
                                            Spacer(minLength: 8)
                                            publishedAudioLocaleLabel
                                        }
                                        .frame(maxWidth: .infinity, alignment: .leading)
                                        .frame(minHeight: 44)
                                    }
                                }
                                if model.selectedAudioLanguageName == nil,
                                   model.selectedContentTarget?.audioStatus == "human_reviewed" {
                                    if let error = model.publishedAudioError {
                                        HStack(spacing: 8) {
                                            Label(localization.text(error), systemImage: "exclamationmark.circle")
                                                .font(.footnote)
                                            Spacer(minLength: 8)
                                            Button(localization.text("重新加载当前音频")) {
                                                Task { await model.prepareSelectedPublishedAudio() }
                                            }
                                            .accessibilityIdentifier("retry-published-audio")
                                        }
                                    } else {
                                        ProgressView(localization.text("正在准备音频…"))
                                            .accessibilityIdentifier("preparing-published-audio")
                                    }
                                }
                                if playback.publishedPositionRestoreFailed {
                                    Button(localization.text("重新加载当前音频")) {
                                        Task { await model.prepareSelectedPublishedAudio() }
                                    }.accessibilityIdentifier("retry-published-position")
                                }
                                if model.selectedAudioLocale != nil {
                                    if let saved = playback.resumePosition { resumeCard(saved) }
                                    if shouldShowPlaybackStatusDetail { playbackStatusDetail }
                                }
                                if model.usesNativePublishedReader { publishedReading }
                            }
                            .frame(maxWidth: .infinity, alignment: .leading)
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
                    .frame(maxWidth: verticalSizeClass == .compact ? 920 : 720)
                    .frame(maxWidth: .infinity)
                }
                .accessibilityIdentifier("listening-scroll")
                .refreshable { await model.refresh() }
                .onChange(of: model.display) { _, display in
                    guard display == .transcript, playback.isPlaying,
                          let track = model.selectedTrack else { return }
                    // Let the transcript enter the layout before resolving its row.
                    // This runs only when opening it, so reading never follows playback.
                    DispatchQueue.main.async {
                        guard model.display == .transcript, playback.isPlaying,
                              model.selectedTrack?.id == track.id,
                              !track.cues.isEmpty else { return }
                        let index = track.cues.firstIndex {
                            $0.start <= playback.position && playback.position < $0.end
                        } ?? track.cues.lastIndex { $0.start <= playback.position } ?? 0
                        withAnimation(reduceMotion ? nil : .easeInOut(duration: 0.25)) {
                            proxy.scrollTo("cue-\(index)", anchor: .center)
                        }
                    }
                }
                .onChange(of: returnToCurrent) { _, _ in
                    if model.display == .transcript,
                       let index = model.selectedTrack?.cues.firstIndex(where: { $0.start <= playback.position && playback.position < $0.end }) {
                        withAnimation(reduceMotion ? nil : .easeInOut(duration: 0.25)) {
                            proxy.scrollTo("cue-\(index)", anchor: .center)
                        }
                    } else {
                        model.display = .current
                        withAnimation(reduceMotion ? nil : .easeInOut(duration: 0.25)) {
                            proxy.scrollTo(model.usesNativePublishedReader ? "published-current-card" : "top", anchor: .top)
                        }
                    }
                }
            }
            .background(Brand.background)
            .listeningPlayerDock(atTrailingEdge: usesTrailingDock,
                                 inSystemBar: usesSystemVerticalBar) {
                if usesTrailingDock && !usesSystemVerticalBar {
                    VStack(spacing: 12) {
                        trailingNavigationActions
                        if model.selectedTrack != nil || model.selectedAudioLocale != nil {
                            listeningPlaybackDock(placement: .trailing)
                        }
                    }
                    .frame(width: 80)
                    .frame(maxHeight: .infinity, alignment: .top)
                    .padding(.top, 8)
                } else {
                    if model.selectedTrack != nil || model.selectedAudioLocale != nil {
                        HStack(spacing: 0) {
                            Color.clear.frame(width: controlRegion.minX, height: 0)
                            listeningPlaybackDock(placement: .bottom)
                                .frame(width: controlRegion.width)
                            Spacer(minLength: 0)
                        }
                        .frame(maxWidth: .infinity)
                    }
                }
            }
            .toolbar {
                ToolbarItem(placement: .principal) { BrandTitle() }
                if !usesTrailingDock || usesSystemVerticalBar {
                    ToolbarItemGroup(placement: .primaryAction) {
                        Button(localization.text("选择证道周次"), systemImage: "calendar") { sheet = .weeks }
                            .labelStyle(.iconOnly).accessibilityIdentifier("choose-sermon")
                        Button(localization.text("更多选项"), systemImage: "ellipsis.circle") { sheet = .about }
                            .labelStyle(.iconOnly).accessibilityIdentifier("more-options")
                    }
                }
                #if os(iOS) && canImport(SwiftUI, _version: 8.0.85)
                if #available(iOS 27.1, macOS 27.1, *), usesSystemVerticalBar,
                   model.selectedTrack != nil || model.selectedAudioLocale != nil {
                    ToolbarItem(placement: .primaryAction) {
                        listeningPlaybackDock(placement: .trailing, inSystemBar: true)
                    }
                    .axisBehavior(.verticalPreferred)
                    .visibilityPriority(.high)
                }
                #endif
            }
            #if os(iOS)
            .navigationBarTitleDisplayMode(.inline)
            #endif
            .sheet(item: $sheet, onDismiss: {
                playback.setVideoPresented(false)
                updateAlignmentFailurePresentation()
            }) { destination in
                switch destination {
                case .weeks:
                    WeekSheet(model: model)
                        .environment(\.dynamicTypeSize, typeSize)
                        .presentationDetents(typeSize.isAccessibilitySize ? [.large] : [.medium, .large])
                        .presentationDragIndicator(.visible)
                case .languages:
                    TargetLanguageSheet(model: model)
                        .presentationDetents([.medium, .large]).presentationDragIndicator(.visible)
                case .precision:
                    PrecisionSheet(model: model)
                        .presentationDetents(typeSize.isAccessibilitySize ? [.large] : [.medium, .large])
                        .presentationDragIndicator(.visible)
                case .outline:
                    OutlineSheet(week: model.selectedWeek, playback: playback)
                        .presentationDetents([.large]).presentationDragIndicator(.visible)
                case .about:
                    AboutSheet(model: model)
                        .environment(\.dynamicTypeSize, typeSize)
                        .presentationDetents([.large]).presentationDragIndicator(.visible)
                case .locate:
                    EnglishLocateSheet(model: model) {
                        model.display = .current
                        returnToCurrent = UUID()
                        locateConfirmation = playback.position
                    }
                    .presentationDetents([.large]).presentationDragIndicator(.visible)
                case .video:
                    if let url = model.fullVideoURL { FullVideoSheet(url: url) }
                }
            }
            }
        }
    }

    private var playbackStatusDetail: some View {
        Text(localization.text(model.isPreparing || model.isPreparingPublishedAudio
                               ? "正在准备音频…" : playback.message))
            .font(.footnote)
            .foregroundStyle(.secondary)
            .fixedSize(horizontal: false, vertical: true)
            .accessibilityIdentifier("playback-status-detail")
    }

    private var shouldShowPlaybackStatusDetail: Bool {
        model.isPreparing || model.isPreparingPublishedAudio || playback.message != "音频就绪 · 可以播放"
    }

    private func listeningPlaybackDock(placement: PlaybackDockPlacement,
                                       inSystemBar: Bool = false) -> some View {
        PlaybackDock(
            playback: playback,
            isPreparing: model.isPreparing || model.isPreparingPublishedAudio,
            alignmentModel: model,
            locate: { sheet = .locate },
            precision: model.selectedTrack == nil ? nil : { sheet = .precision },
            current: model.selectedTrack == nil ? nil : { returnToCurrent = UUID() },
            placement: placement,
            inSystemBar: inSystemBar,
            onMoreTap: {
                playbackMorePlacement = placement
                showingPlaybackMore = true
            },
            onMoreDismiss: { showingPlaybackMore = false },
            onMoreFrameChange: { playbackMoreButtonFrame = $0 }
        )
    }

    private func playbackMoreControls(width: CGFloat) -> some View {
        PlaybackMoreControls(
            playback: playback,
            isPreparing: model.isPreparing || model.isPreparingPublishedAudio,
            alignmentModel: model,
            locate: { sheet = .locate },
            precision: model.selectedTrack == nil ? nil : { sheet = .precision },
            current: model.selectedTrack == nil ? nil : { returnToCurrent = UUID() },
            onClose: { showingPlaybackMore = false },
            width: width
        )
    }

    @ViewBuilder private var playbackMoreOverlay: some View {
        if showingPlaybackMore && !playbackMoreButtonFrame.isNull {
            GeometryReader { proxy in
                Color.clear
                    .contentShape(Rectangle())
                    .onTapGesture { showingPlaybackMore = false }
                    .accessibilityHidden(true)
                playbackMoreControls(width: min(320, max(0, proxy.size.width - 24)))
                    .listeningGlassSurface()
                    .onGeometryChange(for: CGSize.self, of: { $0.size }) { size in
                        playbackMorePanelSize = size
                    }
                    .position(playbackMorePosition(in: proxy))
            }
        }
    }

    private func playbackMorePosition(in proxy: GeometryProxy) -> CGPoint {
        let root = proxy.frame(in: .global)
        let button = playbackMoreButtonFrame.offsetBy(dx: -root.minX, dy: -root.minY)
        let width = min(320, max(0, proxy.size.width - 24))
        let height = playbackMorePanelSize.height
        let proposedX = playbackMorePlacement == .trailing
            ? button.minX - width - 10 : button.midX - width / 2
        let proposedY = playbackMorePlacement == .trailing
            ? button.midY - height / 2 : button.minY - height - 8
        let x = min(max(proposedX, 12), max(12, proxy.size.width - width - 12))
        let y = min(max(proposedY, 12), max(12, proxy.size.height - height - 12))
        return CGPoint(x: x + width / 2, y: y + height / 2)
    }

    private var trailingNavigationActions: some View {
        VStack(spacing: 0) {
            Button { sheet = .weeks } label: {
                Image(systemName: "calendar")
                    .frame(width: 56, height: 52)
                    .contentShape(Rectangle())
            }
            .accessibilityLabel(localization.text("选择证道周次"))
            .accessibilityIdentifier("choose-sermon")

            Button { sheet = .about } label: {
                Image(systemName: "ellipsis.circle")
                    .frame(width: 56, height: 52)
                    .contentShape(Rectangle())
            }
            .accessibilityLabel(localization.text("更多选项"))
            .accessibilityIdentifier("more-options")
        }
        .font(.title3.weight(.medium))
        .buttonStyle(.plain)
        .foregroundStyle(Brand.accent)
        .padding(6)
        .listeningGlassSurface()
        .padding(.horizontal, 6)
    }

    private func dockControlRegion(in geometry: GeometryProxy) -> CGRect {
        let bounds = CGRect(origin: .zero, size: geometry.size)
        #if os(iOS) && canImport(SwiftUI, _version: 8.0.85)
        if #available(iOS 27.1, macOS 27.1, *) {
            let divisions = geometry.reservedRegions(kind: .division)
                .filter(\.isActive)
                .map(\.frame)
            return PlaybackControlRegion.resolve(in: bounds, excluding: divisions)
        }
        #endif
        return bounds
    }

    @ViewBuilder private func sermonHeading(_ week: SermonWeek) -> some View {
        if verticalSizeClass == .compact {
            HStack(spacing: 16) {
                VStack(alignment: .leading, spacing: 4) {
                    SermonHeadingView(heading: SermonHeading(title: week.title, series: week.series, speaker: week.speaker),
                                      date: week.date, titleFont: .headline, identifier: "sermon")
                    Text(reviewLabel).font(.caption).foregroundStyle(Brand.accent)
                }
                Spacer(minLength: 8)
                appLanguageMenu
                compactLanguageButton
                Button(localization.text("证道大纲"), systemImage: "list.bullet.rectangle") { sheet = .outline }
                    .buttonStyle(.plain).font(.subheadline).frame(minHeight: 44)
            }
        } else {
            regularSermonHeading(week)
        }
    }

    private func regularSermonHeading(_ week: SermonWeek) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack {
                Text(localization.text("证道")).font(.caption.weight(.medium)).foregroundStyle(.secondary)
                Spacer()
                appLanguageMenu
            }
            SermonHeadingView(heading: SermonHeading(title: week.title, series: week.series, speaker: week.speaker),
                              date: week.date, titleFont: .largeTitle.bold(), identifier: "sermon")
            Text(week.scripture).font(.footnote).foregroundStyle(.secondary)
            languageButton
            if model.selectedContentLocale != "zh-Hans", model.selectedContentTarget != nil {
                Text(localization.text("所选语言在独立发布页面中打开；原生播放器继续保留当前已验证的中文音轨。"))
                    .font(.caption).foregroundStyle(.secondary)
                    .accessibilityIdentifier("published-language-routing-note")
            }
            HStack {
                Text(reviewLabel).font(.caption.weight(.medium))
                    .foregroundStyle(Brand.accent)
                    .padding(.horizontal, 10).padding(.vertical, 6)
                    .background(Brand.accent.opacity(0.10), in: Capsule())
                Spacer()
                Button(localization.text("证道大纲"), systemImage: "list.bullet.rectangle") { sheet = .outline }
                    .font(.subheadline.weight(.medium)).frame(minHeight: 44)
                    .buttonStyle(.plain).foregroundStyle(.primary)
            }
        }
    }

    private var appLanguageMenu: some View {
        Menu {
            Picker(localization.text("界面语言"), selection: Binding(
                get: { localization.preference },
                set: { localization.setPreference($0) })) {
                Text(localization.text("跟随系统")).tag(AppLanguage.system)
                Text("简体中文").tag(AppLanguage.simplifiedChinese)
                Text("English").tag(AppLanguage.english)
                Text("한국어").tag(AppLanguage.korean)
                Text("Español").tag(AppLanguage.spanish)
                Text("Tiếng Việt").tag(AppLanguage.vietnamese)
            }
        } label: {
            Text(localization.language.shortLabel).font(.caption.weight(.bold))
                .frame(minWidth: 44, minHeight: 44)
        }
        .accessibilityLabel(localization.text("界面语言"))
        .accessibilityValue(localization.language.shortLabel)
        .accessibilityIdentifier("app-language-menu")
    }

    private var languageButton: some View {
        Button { sheet = .languages } label: {
            Label("\(model.selectedContentLanguageName) · \(localization.text(model.selectedContentCapabilitySummary))",
                  systemImage: "globe")
        }
        .buttonStyle(.bordered)
        .font(.subheadline.weight(.medium))
        .frame(minHeight: 44)
        .accessibilityLabel(localization.text("选择证道语言"))
        .accessibilityValue("\(model.selectedContentLanguageName)，\(localization.text(model.selectedContentCapabilitySummary))")
        .accessibilityIdentifier("choose-content-language")
    }

    private var compactLanguageButton: some View {
        Button { sheet = .languages } label: { Image(systemName: "globe") }
            .font(.title3).frame(minWidth: 44, minHeight: 44)
            .accessibilityLabel(localization.text("选择证道语言"))
            .accessibilityValue("\(model.selectedContentLanguageName)，\(localization.text(model.selectedContentCapabilitySummary))")
            .accessibilityIdentifier("choose-content-language")
    }

    @ViewBuilder private var publishedVideoButton: some View {
        if model.fullVideoURL != nil {
            Button {
                playback.setVideoPresented(true)
                sheet = .video
            } label: {
                Label(localization.text("观看完整视频"), systemImage: "play.rectangle")
            }
            .buttonStyle(.plain)
            .font(.subheadline.weight(.medium))
            .frame(minHeight: 44, alignment: .leading)
            .accessibilityIdentifier("watch-full-video")
        }
    }

    @ViewBuilder private var publishedAudioLocaleLabel: some View {
        if let audioLanguage = model.selectedAudioLanguageName {
            Text("\(localization.text("音频语言")) · \(audioLanguage)")
                .font(.footnote.weight(.medium))
                .accessibilityIdentifier("published-audio-locale")
        }
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

    @ViewBuilder private var publishedReading: some View {
        if model.isLoadingPublishedTranscript {
            ProgressView(localization.text("正在读取本周证道…"))
        } else if let error = model.publishedTranscriptError {
            Text(localization.text(error)).font(.footnote)
            Button(localization.text("重新加载")) { Task { await model.loadSelectedPublishedTranscript() } }
        } else if let transcript = model.publishedTranscript {
            Picker(localization.text("收听内容"), selection: $model.display) {
                ForEach(AppModel.ListeningDisplay.allCases, id: \.self) {
                    Text(localization.text($0.rawValue)).tag($0)
                }
            }.pickerStyle(.segmented).accessibilityIdentifier("listening-display")
            if model.display == .current {
                let cue = transcript.captions.first { $0.start <= playback.position && playback.position < $0.end }
                    ?? (playback.position < (transcript.captions.first?.start ?? 0) ? transcript.captions.first : nil)
                VStack(alignment: .leading, spacing: 12) {
                    Text(localization.text("当前字幕")).font(.subheadline).foregroundStyle(Brand.accent)
                    sourceText(cue?.text ?? localization.text("等待下一段字幕…"), language: model.selectedContentLocale)
                        .font(.system(size: readingSize, weight: .medium)).lineSpacing(6)
                        .fixedSize(horizontal: false, vertical: true)
                        .accessibilityIdentifier("published-current-subtitle")
                    if let english = cue?.english {
                        sourceText(english, language: "en").font(.body).foregroundStyle(.secondary)
                            .fixedSize(horizontal: false, vertical: true)
                            .accessibilityIdentifier("published-current-english")
                    }
                }.padding(16).frame(maxWidth: .infinity, alignment: .leading)
                    .background(Brand.surface, in: RoundedRectangle(cornerRadius: 28))
                    .id("published-current-card")
                locateConfirmationView
            } else {
                publishedRows(transcript.captions, prefix: "published-caption")
            }
            DisclosureGroup(localization.text("完整文稿 · 英文对照")) {
                publishedRows(transcript.fullText, prefix: "published-full")
            }.accessibilityIdentifier("published-full-transcript")
            englishLocateEntry
            if model.alignmentAvailable || model.alignmentBusy || model.hasAlignmentFeedback {
                Text(localization.text(model.alignmentDisplayStatus, ["time": model.alignmentPosition.map(PlaybackTime.format) ?? ""]))
                    .font(.footnote).foregroundStyle(.secondary)
                    .accessibilityIdentifier("alignment-status")
            }
        }
    }

    @ViewBuilder private var locateConfirmationView: some View {
        if let position = locateConfirmation {
            HStack {
                Text(localization.text("已定位 {time}", ["time": PlaybackTime.format(position)]))
                    .accessibilityIdentifier("locate-confirmation")
                Spacer(minLength: 8)
                if playback.undoPosition != nil {
                    Button(localization.text("撤销")) {
                        playback.undo()
                        locateConfirmation = nil
                    }.frame(minHeight: 44).accessibilityIdentifier("locate-undo")
                }
            }.font(.subheadline).foregroundStyle(Brand.accent)
        }
    }

    private var englishLocateEntry: some View {
        Button { sheet = .locate } label: {
            HStack {
                Label(localization.text("没跟上现场？按英文找位置"), systemImage: "text.magnifyingglass")
                    .fixedSize(horizontal: false, vertical: true)
                Spacer(minLength: 8)
                Image(systemName: "chevron.right").font(.caption.weight(.semibold))
            }.frame(minHeight: 44).contentShape(Rectangle())
        }
        .buttonStyle(.plain).font(.subheadline).foregroundStyle(Brand.accent)
        .accessibilityIdentifier("open-english-locate")
    }

    private func publishedRows(_ rows: [PublishedTranscriptCue], prefix: String) -> some View {
        LazyVStack(alignment: .leading, spacing: 20) {
            ForEach(rows, id: \.id) { cue in
                let audioCue = model.publishedCaptionsByID[cue.id]
                VStack(alignment: .leading, spacing: 10) {
                    TranscriptTimeButton(title: PlaybackTime.format(audioCue?.start ?? cue.start)) {
                        if let audioCue { playback.jump(to: audioCue.start) }
                    }
                        .disabled(!playback.isReady || audioCue == nil)
                        .accessibilityIdentifier("\(prefix)-time-\(cue.id)")
                        .accessibilityAddTraits(audioCue.map { $0.start <= playback.position && playback.position < $0.end } == true ? .isSelected : [])
                    sourceText(cue.text, language: model.selectedContentLocale)
                        .font(.title3).lineSpacing(7).textSelection(.enabled)
                        .fixedSize(horizontal: false, vertical: true)
                        .accessibilityIdentifier("\(prefix)-text-\(cue.id)")
                    if let english = cue.english {
                        sourceText(english, language: "en").font(.body).lineSpacing(5)
                            .foregroundStyle(.secondary).textSelection(.enabled)
                            .fixedSize(horizontal: false, vertical: true)
                            .accessibilityIdentifier("\(prefix)-english-\(cue.id)")
                    }
                }.padding(16).frame(maxWidth: .infinity, alignment: .leading)
                    .background(Brand.surface, in: RoundedRectangle(cornerRadius: 20))
                    .id("\(prefix)-\(cue.id)")
            }
        }
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
                Text("\(Text(localization.text("接下来"))) · \(sourceText(next.text, language: "zh-Hans"))")
                    .font(.body).foregroundStyle(.secondary)
                    .lineLimit(2).lineSpacing(4)
            }
            Text(localization.text("字幕随中文音频更新")).font(.caption2).foregroundStyle(.secondary)
        }.padding(20).frame(maxWidth: .infinity, alignment: .leading)
            .background(Brand.surface, in: RoundedRectangle(cornerRadius: 28, style: .continuous))
    }

    private func transcript(_ track: SermonTrack) -> some View {
        let bilingual = model.bilingualRows
        let rows = bilingual?.rows ?? []
        return LazyVStack(alignment: .leading, spacing: 22) {
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
            ForEach(rows) { row in
                let cue = row.cue
                VStack(alignment: .leading, spacing: 8) {
                    TranscriptTimeButton(title: PlaybackTime.format(cue.start)) { playback.jump(to: cue.start) }
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
                .id("cue-\(row.index)")
            }
        }
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

/// Keep source passages in their supplied language, including accessibility.
func sourceText(_ value: String, language: String) -> Text {
    var text = AttributedString(value)
    text.languageIdentifier = language
    return Text(text)
}

struct AlignmentControls: View {
    @State private var showingUnavailableReason = false
    var compact: Bool
    var locate: (() -> Void)?
    @ObservedObject var model: AppModel
    @ObservedObject private var playback: PlaybackController
    @ObservedObject private var localization = AppLocalization.shared

    init(model: AppModel, compact: Bool = false, locate: (() -> Void)? = nil) {
        self.locate = locate
        self.model = model
        self.playback = model.playback
        self.compact = compact
    }

    private var status: String {
        localization.text(model.alignmentDisplayStatus, ["time": model.alignmentPosition.map(PlaybackTime.format) ?? ""])
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            Button {
                if model.alignmentBusy { model.cancelAlignment() }
                else if model.alignmentAvailable { model.startAlignment() }
                else { showingUnavailableReason = true }
            } label: {
                Label(localization.text(model.alignmentBusy ? "取消对齐" : "听现场并对齐"),
                      systemImage: model.alignmentBusy ? "stop.circle" : "mic")
                    .fixedSize(horizontal: false, vertical: true)
                    .frame(maxWidth: .infinity, minHeight: 44)
                    .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
            .font(.subheadline.weight(.semibold))
            .foregroundStyle(Brand.accent)
            .accessibilityIdentifier("align-live-audio")
            .accessibilityHint(status)
            .alert(localization.text("现场自动对齐暂不可用"), isPresented: $showingUnavailableReason) {
                if let locate { Button(localization.text("按英文找位置"), action: locate) }
                Button(localization.text("刷新目录")) { Task { await model.refresh() } }
                Button(localization.text("关闭"), role: .cancel) {}
            } message: { Text(status) }
            if !compact || model.alignmentBusy || model.hasAlignmentFeedback {
                Text(status)
                    .font(.footnote).foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
                    .accessibilityIdentifier("alignment-status")
            }
        }
    }
}

private enum ListeningSheet: String, Identifiable {
    case weeks, languages, precision, outline, about, video, locate
    var id: String { rawValue }
}

private struct FullVideoSheet: View {
    @ObservedObject private var localization = AppLocalization.shared
    @Environment(\.dismiss) private var dismiss
    @ViewState private var player: AVPlayer

    init(url: URL) { _player = ViewState(initialValue: AVPlayer(url: url)) }

    var body: some View {
        NavigationStack {
            VStack(spacing: 16) {
                VideoPlayer(player: player)
                    .aspectRatio(16 / 9, contentMode: .fit)
                    .accessibilityIdentifier("native-full-video-player")
                Text(localization.text("原始英文视频"))
                    .font(.footnote).foregroundStyle(.secondary)
                    .accessibilityIdentifier("native-full-video")
                Spacer(minLength: 0)
            }
            .padding()
            .navigationTitle(localization.text("观看完整视频"))
            .toolbar { ToolbarItem(placement: .confirmationAction) { Button(localization.text("完成")) { dismiss() } } }
        }
        .onDisappear { player.pause() }
    }
}

private struct TargetLanguageSheet: View {
    @ObservedObject private var localization = AppLocalization.shared
    @ObservedObject var model: AppModel
    @Environment(\.dismiss) private var dismiss
    @ViewState private var verifiedPage: VerifiedLanguagePage?

    var body: some View {
        NavigationStack {
            Group {
                if let verifiedPage {
                    VerifiedLanguagePageView(page: verifiedPage)
                } else {
                    languageList
                }
            }
            .navigationTitle(localization.text("选择证道语言"))
            .toolbar {
                if verifiedPage != nil {
                    ToolbarItem(placement: .cancellationAction) {
                        Button(localization.text("选择证道语言"), systemImage: "chevron.left") { verifiedPage = nil }
                            .labelStyle(.iconOnly)
                            .accessibilityIdentifier("return-to-content-languages")
                    }
                }
                ToolbarItem(placement: .confirmationAction) { Button(localization.text("完成")) { dismiss() } }
            }
        }
        .environment(\.locale, localization.locale)
        #if os(macOS)
        .frame(minWidth: 430, minHeight: 560)
        #endif
    }

    private var languageList: some View {
        List {
            if model.availableContentLanguages.isEmpty {
                ContentUnavailableView(
                    localization.text("尚无可选择的语言版本"),
                    systemImage: "globe.badge.chevron.backward",
                    description: Text(localization.text(model.multilingualNotice ?? "发布目录尚未提供已人工审核的目标语言。"))
                )
            } else {
                Section {
                    ForEach(model.availableContentLanguages, id: \.locale) { option in
                        Button {
                            Task {
                                if model.usesNativePublishedReader {
                                    model.selectPublishedContentLanguage(option.locale)
                                    dismiss()
                                } else {
                                    guard let page = await model.selectContentLanguage(option.locale) else { return }
                                    verifiedPage = page
                                }
                            }
                        } label: {
                            HStack(spacing: 14) {
                                VStack(alignment: .leading, spacing: 5) {
                                    Text(AppModel.languageName(option.locale)).font(.headline)
                                    Text(capabilitySummary(option.target))
                                        .font(.caption).foregroundStyle(.secondary)
                                }
                                Spacer()
                                if model.isSelectingLanguage && model.selectedContentLocale != option.locale {
                                    ProgressView().controlSize(.small)
                                } else if model.selectedContentLocale == option.locale {
                                    Image(systemName: "checkmark").foregroundStyle(Brand.accent)
                                }
                            }
                            .frame(maxWidth: .infinity, minHeight: 54, alignment: .leading)
                            .contentShape(Rectangle())
                        }
                        .buttonStyle(.plain)
                        .disabled(model.isSelectingLanguage)
                        .accessibilityIdentifier("content-language-\(option.locale)")
                        .accessibilityValue(localization.text(model.selectedContentLocale == option.locale ? "已选择" : "未选择"))
                    }
                } header: {
                    Text(localization.text("证道语言"))
                } footer: {
                    Text(localization.text(model.usesNativePublishedReader ? "选择语言后，在 App 内阅读并准备对应配音。" : "选择后打开该语言自己的已发布页面。界面语言和证道音频语言不会被静默更改。"))
                }
            }
            if let error = model.languageSelectionError {
                Section { Label(localization.text(error), systemImage: "exclamationmark.circle") }
            }
        }
    }

    private func capabilitySummary(_ target: PageTarget) -> String {
        var values = [localization.text(target.audioStatus == "human_reviewed" ? "文字" : "仅文字")]
        if target.capabilities.contains(.captions) { values.append(localization.text("字幕")) }
        if target.audioStatus == "human_reviewed" { values.append(localization.text("音频")) }
        if target.capabilities.contains(.download) { values.append(localization.text("可下载")) }
        return values.joined(separator: " · ")
    }
}

private struct VerifiedLanguagePageView: View {
    let page: VerifiedLanguagePage

    var body: some View {
        VerifiedHTMLView(html: page.html)
            .accessibilityIdentifier("verified-content-page")
            .ignoresSafeArea(edges: .bottom)
    }
}

/// The release page is rendered from verified bytes. Restrict the document to
/// inline styles and data images so it cannot fetch mutable linked content.
private struct VerifiedHTMLView {
    let html: String

    var restrictedHTML: String {
        let policy = "<meta http-equiv=\"Content-Security-Policy\" content=\"default-src 'none'; style-src 'unsafe-inline'; img-src data:; font-src data:; form-action 'none'; base-uri 'none'\">"
        let injected = html.replacingOccurrences(of: "(?i)(<head(?:\\s[^>]*)?>)", with: "$1\(policy)", options: .regularExpression)
        return injected == html ? policy + html : injected
    }

    func configuredView() -> WKWebView {
        let configuration = WKWebViewConfiguration()
        configuration.defaultWebpagePreferences.allowsContentJavaScript = false
        let view = WKWebView(frame: .zero, configuration: configuration)
        view.navigationDelegate = navigationGuard
        return view
    }

    private var navigationGuard: VerifiedPageNavigationGuard { VerifiedPageNavigationGuard.shared }
}

private final class VerifiedPageNavigationGuard: NSObject, WKNavigationDelegate {
    static let shared = VerifiedPageNavigationGuard()

    func webView(_ webView: WKWebView, decidePolicyFor action: WKNavigationAction,
                 decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
        let url = action.request.url
        decisionHandler(url == nil || url?.scheme == "about" ? .allow : .cancel)
    }
}

#if os(iOS)
extension VerifiedHTMLView: UIViewRepresentable {
    func makeUIView(context: Context) -> WKWebView { configuredView() }
    func updateUIView(_ view: WKWebView, context: Context) {
        guard context.coordinator.loadedHTML != html else { return }
        context.coordinator.loadedHTML = html
        view.loadHTMLString(restrictedHTML, baseURL: nil)
    }
    func makeCoordinator() -> Coordinator { Coordinator() }
    final class Coordinator { var loadedHTML: String? }
}
#else
extension VerifiedHTMLView: NSViewRepresentable {
    func makeNSView(context: Context) -> WKWebView { configuredView() }
    func updateNSView(_ view: WKWebView, context: Context) {
        guard context.coordinator.loadedHTML != html else { return }
        context.coordinator.loadedHTML = html
        view.loadHTMLString(restrictedHTML, baseURL: nil)
    }
    func makeCoordinator() -> Coordinator { Coordinator() }
    final class Coordinator { var loadedHTML: String? }
}
#endif

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

/// The same hierarchy on the listening page and in the picker. A line break
/// separates title/series; only the short date/speaker pair needs a middle dot.
private struct SermonHeadingView: View {
    @ObservedObject private var localization = AppLocalization.shared
    let heading: SermonHeading
    let date: String
    let titleFont: Font
    let identifier: String

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(heading.title).font(titleFont)
                .accessibilityAddTraits(.isHeader)
                .accessibilityIdentifier("\(identifier)-title")
            if let series = heading.series {
                Text(series).font(.subheadline).foregroundStyle(.secondary)
                    .accessibilityIdentifier("\(identifier)-series")
            }
            ViewThatFits(in: .horizontal) {
                Text(heading.details(date: date)).fixedSize()
                    .accessibilityIdentifier("\(identifier)-details")
                // At large type, separate complete fields rather than leaving
                // a separator stranded at the end or start of a line.
                Text([date, heading.speaker].compactMap { $0 }.joined(separator: "\n"))
                    .fixedSize(horizontal: false, vertical: true)
                    .accessibilityLabel(heading.details(date: date))
                    .accessibilityIdentifier("\(identifier)-details")
            }
            .font(.subheadline).foregroundStyle(.secondary)
            if let edition = heading.edition {
                Text(localization.text(edition)).font(.caption).foregroundStyle(.secondary)
            }
        }
        .fixedSize(horizontal: false, vertical: true)
        .frame(maxWidth: .infinity, alignment: .leading)
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
                    if !model.independentPages.isEmpty {
                        Text(localization.text("已发布页面"))
                            .font(.footnote.weight(.semibold)).foregroundStyle(.secondary)
                            .frame(maxWidth: .infinity, alignment: .leading)
                            .padding(.horizontal, 20).padding(.top, 18)
                        ForEach(model.independentPages.sorted { $0.date > $1.date }) { page in
                            Button {
                                model.selectPublishedPage(page)
                                dismiss()
                            } label: {
                                HStack {
                                    SermonHeadingView(heading: model.heading(for: page), date: page.date,
                                                      titleFont: .headline, identifier: "picker-\(page.id)")
                                    Spacer()
                                    if page.id == model.selectedPageID { Image(systemName: "checkmark") }
                                }
                                .padding(20).frame(maxWidth: .infinity, minHeight: 72, alignment: .leading)
                                .contentShape(Rectangle())
                            }
                            .buttonStyle(.plain)
                            .accessibilityIdentifier("published-page-\(page.id)")
                            .task(id: model.publishedHeadingKey(page)) { await model.loadPublishedHeading(page) }
                            Divider().padding(.horizontal, 20)
                        }
                    }
                    ForEach(model.weeks) { week in
                        Button {
                            dismiss()
                            Task { await model.select(week: week) }
                        } label: {
                            HStack {
                                SermonHeadingView(heading: SermonHeading(title: week.title, series: week.series, speaker: week.speaker),
                                                  date: week.date, titleFont: .headline, identifier: "picker-\(week.id)")
                                Spacer()
                                if week.id == model.selectedWeek?.id { Image(systemName: "checkmark") }
                            }
                            .padding(20).frame(maxWidth: .infinity, minHeight: 72, alignment: .leading)
                            .contentShape(Rectangle())
                        }
                        .buttonStyle(.plain)
                        .accessibilityIdentifier("legacy-week-\(week.id)")
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

private struct OutlineSheet: View {
    @ObservedObject private var localization = AppLocalization.shared
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
                    Text(week?.contentReview ?? localization.text("AI 整理，供个人跟读参考"))
                        .font(.caption).foregroundStyle(.secondary)
                }.padding(22).frame(maxWidth: 680)
            }.navigationTitle(localization.text("证道大纲"))
                .toolbar { ToolbarItem(placement: .confirmationAction) { Button(localization.text("完成")) { dismiss() } } }
                .listeningBottomBar { PlaybackDock(playback: playback) }
        }
        .environment(\.locale, localization.locale)
        #if os(macOS)
        .frame(minWidth: 430, minHeight: 630)
        #endif
    }
}

private struct AboutSheet: View {
    @ObservedObject private var localization = AppLocalization.shared
    @ObservedObject var model: AppModel
    @Environment(\.dismiss) private var dismiss
    @ViewState private var demoVideo: DemoVideo?
    var body: some View {
        NavigationStack {
            Form {
                Section {
                    NavigationLink { PrivacySupportView(playback: model.playback) } label: {
                        Label(localization.text("隐私与支持"), systemImage: "hand.raised")
                    }
                    .accessibilityIdentifier("privacy-support-link")
                }
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
                Section {
                    VoiceDemoSection(model: model, presentVideo: { demoVideo = DemoVideo(url: $0) })
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
                        Text("한국어").tag(AppLanguage.korean)
                        Text("Español").tag(AppLanguage.spanish)
                        Text("Tiếng Việt").tag(AppLanguage.vietnamese)
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
                    Link(localization.text("打开网页版"), destination: model.mediaOrigin)
                }
            }.formStyle(.grouped).navigationTitle(localization.text("更多选项"))
                .toolbar { ToolbarItem(placement: .confirmationAction) { Button(localization.text("完成")) { dismiss() } } }
        }
        .sheet(item: $demoVideo, onDismiss: { model.playback.setVideoPresented(false) }) {
            DemoVideoSheet(url: $0.url)
        }
        .environment(\.locale, localization.locale)
        #if os(macOS)
        .frame(minWidth: 430, minHeight: 630)
        #endif
    }
}
