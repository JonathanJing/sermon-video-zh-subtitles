import AVKit
import SwiftUI
import TongxingCore

private typealias ViewState<Value> = SwiftUI.State<Value>

/// Auditions use the existing audio owner; each speaker compares one source clip.
struct VoiceDemoSection: View {
    @ObservedObject private var localization = AppLocalization.shared
    @ObservedObject var model: AppModel
    private let presentVideo: ((URL) -> Void)?
    @ObservedObject private var playback: PlaybackController
    @Environment(\.openURL) private var openURL
    @Environment(\.dynamicTypeSize) private var typeSize
    @ViewState private var expanded = false
    @ViewState private var expandedSpeaker: String?
    @ViewState private var selectedLocales: [String: String] = [:]
    @ViewState private var loading = false
    @ViewState private var catalog: VoiceDemoCatalog?
    @ViewState private var unavailable = false
    @ViewState private var demoError = false
    @ViewState private var busyAssetPath: String?
    @ViewState private var assetTask: Task<Void, Never>?
    @ViewState private var requestID = UUID()
    @ViewState private var video: DemoVideo?

    init(model: AppModel, fixture: VoiceDemoCatalog? = nil, presentVideo: ((URL) -> Void)? = nil) {
        self.model = model
        self.presentVideo = presentVideo
        _playback = ObservedObject(wrappedValue: model.playback)
        _catalog = ViewState(initialValue: fixture)
        _expanded = ViewState(initialValue: fixture != nil)
        _expandedSpeaker = ViewState(initialValue: fixture?.speakers.first?.id)
    }

    var body: some View {
        DisclosureGroup(isExpanded: $expanded) {
            Text(localization.text(catalog?.isSourceMatched == true
                ? "同一片段：先听英语原声，再比较中文、韩语和西班牙语。"
                : "旧版独立样音，文稿与英语原声不同；同片段对照正在准备。"))
                .font(.footnote).foregroundStyle(.secondary)
            if loading { ProgressView(localization.text("正在读取试听资料…")) }
            if unavailable {
                Button(localization.text("试听资料暂不可用，点击重试")) { Task { await load() } }
            }
            if demoError || (playback.isPreview && playback.previewLoadFailed) {
                Text(localization.text("试听加载失败，请检查网络后重试。"))
                    .font(.footnote).foregroundStyle(.secondary)
                    .accessibilityIdentifier("voice-demo-error")
            }
            if let catalog {
                ForEach(catalog.speakers) { speaker in
                    DisclosureGroup(isExpanded: Binding(get: { expandedSpeaker == speaker.id }, set: { value in
                        stopAudition()
                        expandedSpeaker = value ? speaker.id : nil
                    })) {
                        speakerContent(speaker, matched: catalog.isSourceMatched)
                    } label: {
                        Text(speaker.displayName)
                            .accessibilityIdentifier("voice-demo-speaker-\(speaker.id)")
                    }
                }
            }
        } label: {
            Text(localization.text("多语种音色试听 · Demo"))
                .accessibilityIdentifier("voice-demo-disclosure")
        }
        .onChange(of: expanded) { _, value in
            if value && catalog == nil && !loading { Task { await load() } }
            if !value { stopAudition() }
        }
        .sheet(item: $video, onDismiss: { playback.setVideoPresented(false) }) { item in DemoVideoSheet(url: item.url) }
        .onDisappear {
            stopAudition()
            if playback.isPreview {
                playback.clear()
                if let week = model.selectedWeek {
                    Task { await model.select(week: week, track: model.selectedTrack, force: true) }
                } else { model.restorePublishedAudioAfterPreview() }
            }
        }
    }

    @ViewBuilder private func speakerContent(_ speaker: VoiceDemoCatalog.Speaker, matched: Bool) -> some View {
        assetButton(speaker.original, title: localization.text("讲员原始英文片段"))
            .accessibilityIdentifier("voice-demo-original-\(speaker.id)")
        if let clip = speaker.video {
            Button {
                prepare(clip) { url in
                    playback.setVideoPresented(true)
                    if let presentVideo { presentVideo(url) }
                    else { video = DemoVideo(url: url) }
                }
            } label: {
                Label(localization.text("观看同片段视频"), systemImage: "play.rectangle")
            }
            .disabled(busyAssetPath != nil)
            .accessibilityIdentifier("voice-demo-video-\(speaker.id)")
        } else if let source = speaker.original.sourceUrl.flatMap(URL.init(string:)) {
            Button(localization.text("原声来源 · 完整视频")) { stopAudition(); openURL(source) }
                .font(.footnote)
        }
        ViewThatFits(in: .horizontal) {
            localeButtons(speaker, vertical: false)
            localeButtons(speaker, vertical: true)
        }
        if let sample = speaker.samples.first(where: { $0.locale == selectedLocale(speaker) }) {
            assetButton(sample, title: "\(languageName(sample.locale)) · \(localization.text("AI 合成样音"))")
                .accessibilityIdentifier("voice-demo-sample-\(speaker.id)-\(sample.locale ?? "")")
            DisclosureGroup(localization.text(matched ? "查看英文与译文" : "查看英文参考与独立样音文稿")) {
                VStack(alignment: .leading, spacing: 16) {
                    manuscript(speaker.original.text, locale: "en", title: "English · \(localization.text("机器转写参考"))")
                    manuscript(sample.text, locale: sample.locale ?? "", title: languageName(sample.locale))
                }
            }
            .id("\(speaker.id)-\(sample.locale ?? "")")
            .accessibilityIdentifier("voice-demo-transcript-\(speaker.id)")
        }
        if matched, let source = (speaker.source?.url).flatMap(URL.init(string:)) {
            Button(localization.text("原声来源")) { stopAudition(); openURL(source) }.font(.caption)
        }
        Text(localization.text("AI 合成样音待人工听审，仅供音色比较，并非正式证道音轨。"))
            .font(.footnote).foregroundStyle(.secondary)
    }

    private func selectedLocale(_ speaker: VoiceDemoCatalog.Speaker) -> String {
        selectedLocales[speaker.id] ?? "zh-Hans"
    }

    private func localeButtons(_ speaker: VoiceDemoCatalog.Speaker, vertical: Bool) -> some View {
        let layout = vertical ? AnyLayout(VStackLayout(alignment: .leading, spacing: 8))
            : AnyLayout(HStackLayout(spacing: 8))
        return layout {
            ForEach(["zh-Hans", "ko", "es"], id: \.self) { locale in
                Button {
                    guard selectedLocale(speaker) != locale else { return }
                    stopAudition()
                    selectedLocales[speaker.id] = locale
                } label: {
                    Text(languageName(locale)).font(.subheadline).fixedSize(horizontal: true, vertical: false)
                        .padding(.horizontal, 10).frame(minHeight: 44)
                        .background(selectedLocale(speaker) == locale ? Brand.accent.opacity(0.15) : Color.clear,
                                    in: RoundedRectangle(cornerRadius: 12))
                }
                .buttonStyle(.plain)
                .foregroundStyle(selectedLocale(speaker) == locale ? Brand.accent : .primary)
                .accessibilityIdentifier("voice-demo-locale-\(speaker.id)-\(locale)")
                .accessibilityValue(localization.text(selectedLocale(speaker) == locale ? "已选择" : "未选择"))
                .accessibilityAddTraits(selectedLocale(speaker) == locale ? [.isSelected] : [])
            }
        }
        .padding(.vertical, 4)
    }

    private func manuscript(_ text: String, locale: String, title: String) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(title).font(.caption).foregroundStyle(.secondary)
            sourceText(text, language: locale).font(.footnote).textSelection(.enabled)
        }
    }

    private func active(_ asset: VoiceDemoCatalog.Asset) -> Bool {
        playback.isPreview && playback.previewID == asset.path + ":" + asset.sha256
    }

    private func assetButton(_ asset: VoiceDemoCatalog.Asset, title: String) -> some View {
        let isActive = active(asset)
        let playing = isActive && (playback.isPlaying || playback.isWaiting)
        return Button {
            if isActive && playback.isReady { playback.toggle() }
            else { prepare(asset) { url in playback.loadPreview(url: url, title: title, previewID: asset.path + ":" + asset.sha256) } }
        } label: {
            Group {
                if typeSize.isAccessibilitySize {
                    VStack(alignment: .leading, spacing: 8) {
                        HStack(spacing: 10) { audioIcon(asset, active: isActive, playing: playing); Text(title).multilineTextAlignment(.leading) }
                        audioTime(asset, active: isActive)
                    }
                } else {
                    HStack(spacing: 10) {
                        audioIcon(asset, active: isActive, playing: playing)
                        Text(title).multilineTextAlignment(.leading)
                        Spacer(minLength: 4)
                        audioTime(asset, active: isActive)
                    }
                }
            }.frame(minHeight: 44)
        }
        .disabled(busyAssetPath != nil || (isActive && !playback.isReady && !playback.previewLoadFailed))
        .accessibilityLabel("\(localization.text(playing ? "暂停" : "播放")) · \(title)")
        .accessibilityValue(localization.text(playing ? "正在播放" : "已暂停"))
    }

    @ViewBuilder private func audioIcon(_ asset: VoiceDemoCatalog.Asset, active: Bool, playing: Bool) -> some View {
        if busyAssetPath == asset.path || (active && !playback.isReady && !playback.previewLoadFailed) {
            ProgressView().frame(width: 28)
        } else { Image(systemName: playing ? "pause.circle" : "play.circle").font(.title2) }
    }

    private func audioTime(_ asset: VoiceDemoCatalog.Asset, active: Bool) -> some View {
        Text(active ? "\(PlaybackTime.format(playback.position))/\(PlaybackTime.format(playback.duration))"
             : asset.durationSeconds.map(PlaybackTime.format) ?? "")
            .font(.caption).monospacedDigit().foregroundStyle(Color.secondary)
    }

    /// Cancellation and player pause are shared by language changes, collapse and dismissal.
    private func stopAudition() {
        requestID = UUID()
        assetTask?.cancel()
        assetTask = nil
        busyAssetPath = nil
        if playback.isPreview { playback.pause() }
    }

    private func prepare(_ asset: VoiceDemoCatalog.Asset, ready: @escaping (URL) -> Void) {
        stopAudition()
        // Includes the sermon player, so starting a video cannot overlap it.
        playback.pause()
        demoError = false
        busyAssetPath = asset.path
        let token = requestID
        assetTask = Task { @MainActor in
            do {
                let directory = FileManager.default.urls(for: .cachesDirectory, in: .userDomainMask)[0]
                    .appendingPathComponent("Tongxing/VoiceDemos", isDirectory: true)
                let file = try await asset.verifiedLocalURL(origin: model.mediaOrigin,
                    session: model.mediaSession, directory: directory)
                try Task.checkCancellation()
                guard requestID == token else { return }
                ready(file)
            } catch is CancellationError { }
            catch { if requestID == token { demoError = true } }
            if requestID == token { busyAssetPath = nil; assetTask = nil }
        }
    }

    private func languageName(_ locale: String?) -> String {
        switch locale {
        case "zh-Hans": return "中文"
        case "ko": return "한국어"
        case "es": return "Español"
        default: return "English"
        }
    }

    @MainActor private func load() async {
        guard !loading else { return }
        loading = true
        unavailable = false
        defer { loading = false }
        do {
            do { catalog = try VoiceDemoCatalog.validatedClips(await fetchCatalog(VoiceDemoCatalog.clipsRelativePath)) }
            catch CatalogError.notFound {
                if model.mediaOrigin.host == AppModel.productionContentOrigin.host {
                    catalog = try VoiceDemoCatalog.productionMerged(weeklyData: await fetchCatalog("weekly.json"),
                        auditionData: await fetchCatalog(VoiceDemoCatalog.productionPath))
                } else { catalog = try VoiceDemoCatalog.validated(await fetchCatalog(VoiceDemoCatalog.relativePath)) }
            }
        } catch { unavailable = true }
    }

    private enum CatalogError: Error { case notFound }
    private func fetchCatalog(_ path: String) async throws -> Data {
        guard let url = URL(string: path, relativeTo: model.mediaOrigin)?.absoluteURL,
              url.scheme == "https", url.host == model.mediaOrigin.host,
              url.port == model.mediaOrigin.port, url.user == nil,
              url.password == nil, url.query == nil, url.fragment == nil else { throw CocoaError(.fileReadNoPermission) }
        var request = URLRequest(url: url)
        request.cachePolicy = .reloadIgnoringLocalCacheData
        request.timeoutInterval = 15
        let (data, response) = try await model.mediaSession.data(for: request)
        guard response.url == url else { throw CocoaError(.fileReadNoPermission) }
        if (response as? HTTPURLResponse)?.statusCode == 404 { throw CatalogError.notFound }
        guard (response as? HTTPURLResponse)?.statusCode == 200,
              !data.isEmpty, data.count < 2_000_000 else { throw CocoaError(.fileReadCorruptFile) }
        return data
    }
}

struct DemoVideo: Identifiable { let id = UUID(); let url: URL }
struct DemoVideoSheet: View {
    @ObservedObject private var localization = AppLocalization.shared
    @Environment(\.dismiss) private var dismiss
    @ViewState private var player: AVPlayer
    init(url: URL) { _player = ViewState(initialValue: AVPlayer(url: url)) }
    var body: some View {
        NavigationStack {
            VStack(spacing: 16) {
                VideoPlayer(player: player).aspectRatio(16 / 9, contentMode: .fit)
                    .accessibilityIdentifier("voice-demo-video-player")
                Text(localization.text("与英语原声相同的片段")).font(.footnote).foregroundStyle(.secondary)
                Spacer(minLength: 0)
            }.padding()
                .navigationTitle(localization.text("同片段视频"))
                .toolbar { ToolbarItem(placement: .confirmationAction) { Button(localization.text("完成")) { dismiss() }.accessibilityIdentifier("voice-demo-video-done") } }
        }
        .onDisappear { player.pause() }
    }
}
