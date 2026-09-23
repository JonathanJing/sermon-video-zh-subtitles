import Combine
import Foundation
import TongxingCore
import TongxingInfrastructure
#if os(iOS)
import UIKit
#endif

@MainActor
final class AppModel: ObservableObject {
    static let productionContentOrigin = URL(string: "https://ai-for-god-sermon-audio.web.app")!
    static var contentOrigin: URL {
        guard let value = Bundle.main.object(forInfoDictionaryKey: "TongxingContentOrigin") as? String,
              let url = URL(string: value), url.scheme == "https", url.user == nil, url.password == nil,
              url.query == nil, url.fragment == nil else { return productionContentOrigin }
        return url
    }

    let playback: PlaybackController
    @Published private(set) var catalog: WeeklyCatalog?
    @Published private(set) var selectedWeek: SermonWeek?
    @Published private(set) var selectedTrack: SermonTrack?
    @Published private(set) var isLoading = false
    @Published private(set) var isPreparing = false
    @Published private(set) var errorMessage: String?
    @Published private(set) var catalogNotice: String?
    @Published private(set) var multilingualCatalog: MultilingualCatalog?
    @Published private(set) var multilingualNotice: String?
    @Published private(set) var devDemoCatalog: DevDemoCatalog?
    @Published private(set) var selectedDevPreviewURL: URL?
    @Published private(set) var selectedContentLocale = "zh-Hans"
    @Published private(set) var selectedPublishedPage: VerifiedLanguagePage?
    @Published private(set) var isSelectingLanguage = false
    @Published private(set) var languageSelectionError: String?
    @Published private(set) var interfaceContentNotice: String?
    @Published private(set) var downloadStates: [String: DownloadState] = [:]
    @Published private(set) var usingOfflineAudio = false
    @Published var display: ListeningDisplay = .current
    @Published private(set) var alignmentStatus = "请播放同一录音的原声，再点击听声对齐。"
    @Published private(set) var alignmentBusy = false
    @Published private(set) var alignmentPosition: Double?
    private var alignmentController: AudioAlignmentController!
    private var hasAlignmentFeedback = false

    var alignmentDisplayStatus: String {
        if alignmentBusy || hasAlignmentFeedback { return alignmentStatus }
        guard alignmentController?.available == true else {
            return "本篇尚未提供现场对齐资料，请刷新目录或手动定位。"
        }
        if isPreparing { return "正在准备音频，请稍候再开始现场自动对齐。" }
        if !playback.isReady { return "音频尚未准备就绪，请稍候或重新载入音频。" }
        return alignmentStatus
    }

    func updateAlignmentState(status: String, busy: Bool, position: Double?) {
        alignmentStatus = status
        alignmentBusy = busy
        alignmentPosition = position
        hasAlignmentFeedback = true
    }

    private func resetAlignmentState() {
        hasAlignmentFeedback = false
        alignmentBusy = false
        alignmentPosition = nil
        alignmentStatus = alignmentController?.available == true
            ? "请播放同一录音的原声，再点击听声对齐。"
            : "本篇尚未提供现场对齐资料，请刷新目录或手动定位。"
    }

    var alignmentAvailable: Bool {
        #if os(iOS)
        return playback.isReady && !isPreparing && alignmentController?.available == true
        #else
        return false
        #endif
    }

    func startAlignment() {
        #if os(iOS)
        guard UIApplication.shared.applicationState != .background else { return }
        #endif
        guard alignmentAvailable else { return }
        alignmentController.start()
    }

    func cancelAlignment() { alignmentController.cancel(resume: true) }
    func suspendAlignment() {
        alignmentController.cancel(message: "App 已进入后台，听声对齐已停止。", resume: true)
    }

    enum ListeningDisplay: String, CaseIterable { case current = "现场收听", transcript = "字幕全文" }
    enum DownloadState: Equatable {
        case absent, checking, downloading, ready, failed(String)
    }

    private var repository: CatalogRepository?
    private var multilingualRepository: MultilingualCatalogRepository?
    private var devDemoRepository: DevDemoCatalogRepository?
    private var offlineLibrary: OfflineLibrary?
    let mediaOrigin: URL
    private let languagePreferenceURL: URL
    private var languagePreferences: ContentLanguagePreferences
    private var started = false
    private var preparation = UUID()
    private var languageRequest = UUID()
    private var downloadTasks: [String: Task<Void, Never>] = [:]

    init(supportDirectory: URL? = nil, contentOrigin: URL? = nil, session: URLSession = .shared) {
        let support = supportDirectory ?? FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask).first!
            .appendingPathComponent("Tongxing", isDirectory: true)
        mediaOrigin = contentOrigin ?? Self.contentOrigin
        languagePreferenceURL = support.appendingPathComponent("tongxing-language-preferences-v2.json")
        let savedPreferences = try? JSONDecoder().decode(ContentLanguagePreferences.self,
            from: Data(contentsOf: languagePreferenceURL))
        languagePreferences = savedPreferences?.schemaVersion == "tongxing-language-preferences-v2"
            ? savedPreferences! : .empty
        playback = PlaybackController(historyURL: support.appendingPathComponent("playback-history-v1.json"))
        repository = CatalogRepository(
                catalogURL: mediaOrigin.appendingPathComponent("weekly.json"),
                cacheDirectory: support.appendingPathComponent("Catalog", isDirectory: true),
                session: session
            )
        multilingualRepository = MultilingualCatalogRepository(
            origin: mediaOrigin,
            cacheDirectory: support.appendingPathComponent("MultilingualCatalog", isDirectory: true),
            session: session
        )
        #if DEBUG
        if mediaOrigin.host == "ai-for-god-sermon-audio-dev.web.app"
            || ProcessInfo.processInfo.arguments.contains("--ui-testing-dev-preview") {
            devDemoRepository = DevDemoCatalogRepository(origin: mediaOrigin, session: session)
        }
        #endif
        offlineLibrary = OfflineLibrary(
                directory: support.appendingPathComponent("Audio", isDirectory: true),
                baseURL: mediaOrigin,
                session: session
            )
        let indexStore = FingerprintIndexStore(directory: support.appendingPathComponent("Alignment", isDirectory: true),
                                               baseURL: mediaOrigin, session: session)
        alignmentController = AudioAlignmentController(
            playback: playback, capture: MicrophoneCapture(),
            getSelection: { [weak self] in
                guard let week = self?.selectedWeek, let track = self?.selectedTrack else { return nil }
                return .init(week: week, track: track)
            },
            loadIndex: { selected in
                guard let alignment = selected.track.alignment else { throw AudioAlignmentError.unavailable }
                return try await indexStore.load(alignment: alignment, week: selected.week, track: selected.track)
            },
            loadPublishedIndex: { selected in
                guard let binding = selected.week.audioFingerprint else { throw AudioAlignmentError.unavailable }
                return try await indexStore.loadPublished(binding: binding, week: selected.week, track: selected.track)
            },
            onState: { [weak self] status, busy, position in
                self?.updateAlignmentState(status: status, busy: busy, position: position)
            }
        )
        playback.onManualInteraction = { [weak self] in self?.alignmentController.cancel() }

    }

    var weeks: [SermonWeek] { catalog?.weeks ?? [] }
    var selectedMultilingualPage: MultilingualPage? {
        guard let multilingualCatalog else { return nil }
        if let selectedWeek { return multilingualCatalog.pages.first(where: { $0.id == selectedWeek.id }) }
        return multilingualCatalog.defaultPage
    }
    var availableContentLanguages: [(locale: String, target: PageTarget)] {
        selectedMultilingualPage?.publishedTargets ?? []
    }
    var selectedDevDemoPage: DevDemoPage? {
        guard let selectedWeek else { return nil }
        return devDemoCatalog?.page(id: selectedWeek.id)
    }
    var availableDevDemoLanguages: [String] {
        selectedDevDemoPage?.targets.keys.sorted() ?? []
    }
    var selectedContentTarget: PageTarget? { selectedMultilingualPage?.targets[selectedContentLocale] }
    var showingPublishedLanguagePage: Bool { selectedContentLocale != "zh-Hans" }
    var selectedContentLanguageName: String { Self.languageName(selectedContentLocale) }
    var selectedContentCapabilitySummary: String {
        guard let target = selectedContentTarget else { return "当前中文版本" }
        return target.audioStatus == "human_reviewed" ? "文字 · 音频" : "仅文字"
    }
    var selectionKey: String? {
        guard let week = selectedWeek, let track = selectedTrack else { return nil }
        return track.identity(weekID: week.id).key
    }
    var currentDownload: DownloadState { selectionKey.flatMap { downloadStates[$0] } ?? .absent }

    func start() async {
        guard !started else { return }
        started = true
        await refresh()
    }

    func refresh() async {
        guard !isLoading, let repository else { return }
        isLoading = true
        defer { isLoading = false }
        do {
            let result = try await repository.load()
            catalog = result.catalog
            catalogNotice = result.warning
            if result.source == .cache {
                catalogNotice = "当前使用上次保存的证道目录。\(result.warning ?? "连接网络后可刷新。")"
            }
            errorMessage = nil
            let next = result.catalog.weeks.first { $0.id == selectedWeek?.id } ?? result.catalog.defaultWeek
            let track = next.tracks.first { $0.id == selectedTrack?.id } ?? next.tracks.first
            await select(week: next, track: track)
            await refreshMultilingualCatalog(pageID: next.id)
        } catch {
            errorMessage = "暂时无法读取证道目录。请连接网络后重试。"
            await refreshMultilingualCatalog(pageID: selectedWeek?.id)
        }
    }

    private func refreshMultilingualCatalog(pageID: String?) async {
        guard let multilingualRepository else { return }
        do {
            let result = try await multilingualRepository.loadCatalog()
            let previousContentLocale = selectedContentLocale
            multilingualCatalog = result.catalog
            devDemoCatalog = nil
            selectedDevPreviewURL = nil
            multilingualNotice = result.warning
            resolveContentLanguage(pageID: pageID)
            await restoreChinesePlaybackIfNeeded(from: previousContentLocale)
            await loadSelectedLanguagePage()
        } catch {
            #if DEBUG
            if let devDemoRepository,
               let catalog = try? await devDemoRepository.loadCatalog() {
                let previousContentLocale = selectedContentLocale
                multilingualCatalog = nil
                devDemoCatalog = catalog
                selectedContentLocale = "zh-Hans"
                selectedPublishedPage = nil
                multilingualNotice = "Firebase Dev 演示内容未经人工审核，仅供开发预览。"
                await restoreChinesePlaybackIfNeeded(from: previousContentLocale)
                return
            }
            #endif
            devDemoCatalog = nil
            selectedDevPreviewURL = nil
            // The legacy Chinese catalog remains a valid migration path while a
            // multilingual catalog has not been published to this environment.
            multilingualNotice = "此环境尚未提供多语言发布目录，继续显示当前中文版本。"
        }
    }

    private func restoreChinesePlaybackIfNeeded(from previousContentLocale: String) async {
        guard previousContentLocale != "zh-Hans", selectedContentLocale == "zh-Hans",
              let selectedWeek else { return }
        await select(week: selectedWeek, track: selectedTrack, force: true)
    }

    func selectContentLanguage(_ locale: String) async -> Bool {
        guard !isSelectingLanguage, let page = selectedMultilingualPage,
              page.targets[locale]?.contentStatus == "human_reviewed", let multilingualRepository else { return false }
        let token = UUID()
        languageRequest = token
        isSelectingLanguage = true
        languageSelectionError = nil
        defer { isSelectingLanguage = false }
        do {
            let publishedPage: VerifiedLanguagePage?
            if locale == "zh-Hans" {
                // The existing weekly catalog is the Chinese migration path.
                // Returning to it must work offline even without a cached v2 package.
                publishedPage = nil
            } else {
                let package = try await multilingualRepository.loadRelease(page: page, locale: locale)
                publishedPage = try await multilingualRepository.loadPage(for: package)
            }
            guard languageRequest == token, selectedMultilingualPage?.id == page.id else { return false }
            if locale != "zh-Hans" {
                alignmentController.cancel()
                playback.clear()
            }
            selectedContentLocale = locale
            selectedPublishedPage = publishedPage
            interfaceContentNotice = nil
            languagePreferences.preferredContentLocale = locale
            languagePreferences.pageSelections[page.id] = locale
            persistLanguagePreferences()
            if locale == "zh-Hans", let selectedWeek {
                await select(week: selectedWeek, track: selectedTrack, force: true)
            }
            return true
        } catch {
            languageSelectionError = "暂时无法打开这个语言版本；当前内容和音频没有改变。"
            return false
        }
    }

    /// An explicit App-language change proposes the same sermon language for
    /// this page. An unavailable target leaves the visible content untouched.
    func followInterfaceLanguage(_ locale: String) async {
        languagePreferences.preferredContentLocale = locale
        persistLanguagePreferences()
        selectedDevPreviewURL = nil
        guard locale != selectedContentLocale else {
            interfaceContentNotice = nil
            return
        }
        if selectedMultilingualPage == nil, locale != "zh-Hans",
           selectedDevDemoPage?.targets[locale] != nil {
            if await previewDevLanguage(locale) { return }
        }
        if locale == "zh-Hans", selectedMultilingualPage?.targets[locale] == nil {
            selectedContentLocale = locale
            selectedPublishedPage = nil
            if let selectedWeek { await select(week: selectedWeek, track: selectedTrack, force: true) }
            interfaceContentNotice = nil
            return
        }
        guard selectedMultilingualPage?.targets[locale]?.contentStatus == "human_reviewed" else {
            interfaceContentNotice = "此篇尚无 {language} 内容，继续显示 {current}。"
            return
        }
        if !(await selectContentLanguage(locale)) {
            interfaceContentNotice = "此篇尚无 {language} 内容，继续显示 {current}。"
        }
    }

    /// Debug-only Dev POC route. It never becomes a verified release or an
    /// audio track and does not change the selected legacy content language.
    func previewDevLanguage(_ locale: String) async -> Bool {
        #if DEBUG
        guard let page = selectedDevDemoPage, page.targets[locale] != nil,
              let devDemoRepository else { return false }
        do {
            let url = try await devDemoRepository.pageURL(page: page, locale: locale)
            guard selectedDevDemoPage?.id == page.id else { return false }
            alignmentController.cancel()
            playback.pause()
            selectedDevPreviewURL = url
            languageSelectionError = nil
            interfaceContentNotice = nil
            return true
        } catch {
            languageSelectionError = "Dev 演示页面暂时无法打开；当前内容和音频没有改变。"
        }
        #endif
        return false
    }

    func loadSelectedLanguagePage() async {
        let token = UUID()
        languageRequest = token
        selectedPublishedPage = nil
        selectedDevPreviewURL = nil
        guard showingPublishedLanguagePage, let page = selectedMultilingualPage,
              let multilingualRepository else { return }
        alignmentController.cancel()
        playback.clear()
        do {
            let package = try await multilingualRepository.loadRelease(page: page, locale: selectedContentLocale)
            let publishedPage = try await multilingualRepository.loadPage(for: package)
            guard languageRequest == token, selectedMultilingualPage?.id == page.id,
                  selectedContentLocale == package.targetLocale else { return }
            selectedPublishedPage = publishedPage
            languageSelectionError = nil
        } catch {
            guard languageRequest == token else { return }
            languageSelectionError = "暂时无法打开这个语言版本；请联网后重试。"
        }
    }

    private func resolveContentLanguage(pageID: String?) {
        guard let catalog = multilingualCatalog else {
            selectedContentLocale = "zh-Hans"
            if let pageID { updateContentFallbackNotice(pageID: pageID) }
            return
        }
        let page: MultilingualPage
        if let pageID {
            guard let matching = catalog.pages.first(where: { $0.id == pageID }) else {
                selectedContentLocale = "zh-Hans"
                updateContentFallbackNotice(pageID: pageID)
                return
            }
            page = matching
        } else {
            page = catalog.defaultPage
        }
        let candidates = [languagePreferences.pageSelections[page.id], languagePreferences.preferredContentLocale,
                          page.defaultTargetLocale].compactMap { $0 }
        selectedContentLocale = candidates.first(where: { page.targets[$0]?.contentStatus == "human_reviewed" })
            ?? page.publishedTargets.first?.locale ?? "zh-Hans"
        updateContentFallbackNotice(pageID: page.id)
    }

    private func updateContentFallbackNotice(pageID: String) {
        guard languagePreferences.pageSelections[pageID] == nil,
              let preferred = languagePreferences.preferredContentLocale,
              preferred != selectedContentLocale else {
            interfaceContentNotice = nil
            return
        }
        interfaceContentNotice = "此篇尚无 {language} 内容，继续显示 {current}。"
    }

    private func persistLanguagePreferences() {
        do {
            try FileManager.default.createDirectory(at: languagePreferenceURL.deletingLastPathComponent(), withIntermediateDirectories: true)
            try JSONEncoder().encode(languagePreferences).write(to: languagePreferenceURL, options: .atomic)
        } catch {
            languageSelectionError = "语言已选择，但本次偏好暂时无法保存。"
        }
    }

    static func languageName(_ locale: String) -> String {
        switch locale {
        case "zh-Hans": return "简体中文"
        case "ko": return "한국어"
        case "es": return "Español"
        case "vi": return "Tiếng Việt"
        case "en": return "English"
        default: return Locale(identifier: locale).localizedString(forIdentifier: locale) ?? locale
        }
    }

    func select(week: SermonWeek, track: SermonTrack? = nil, force: Bool = false) async {
        let nextTrack = track ?? week.tracks.first
        let unchanged = selectedWeek?.id == week.id && selectedTrack?.id == nextTrack?.id
            && selectedTrack?.sha256 == nextTrack?.sha256
            && selectedWeek?.sourceId == week.sourceId && selectedWeek?.sourceUrl == week.sourceUrl
        if unchanged && !force {
            let capabilityChanged = selectedTrack?.alignment != nextTrack?.alignment
                || selectedWeek?.audioFingerprint != week.audioFingerprint
                || selectedWeek?.sourceSha256 != week.sourceSha256
                || selectedWeek?.sourceStartSeconds != week.sourceStartSeconds
                || selectedWeek?.sourceEndSeconds != week.sourceEndSeconds
                || nextTrack.map({ track in
                    if let binding = week.audioFingerprint {
                        return (try? binding.validate(week: week, track: track)) == nil
                    }
                    return track.alignment.map { (try? $0.validate(week: week, track: track)) == nil } ?? false
                }) == true
            if capabilityChanged {
                alignmentController.cancel(message: "对齐资料已更新，请重新开始识别。", resume: true)
            }
            selectedWeek = week
            selectedTrack = nextTrack
            resolveContentLanguage(pageID: week.id)
            if capabilityChanged { resetAlignmentState() }
            if let nextTrack { playback.updateMetadata(week: week, track: nextTrack) }
            return
        }
        playback.clear()
        preparation = UUID()
        let token = preparation
        isPreparing = true
        defer { if preparation == token { isPreparing = false } }
        selectedWeek = week
        selectedTrack = nextTrack
        selectedPublishedPage = nil
        selectedDevPreviewURL = nil
        resolveContentLanguage(pageID: week.id)
        resetAlignmentState()
        usingOfflineAudio = false
        display = .current
        guard let track = nextTrack else { return }
        let key = track.identity(weekID: week.id).key
        var local: URL?
        do {
            local = try await offlineLibrary?.offlineFile(for: track)
            guard preparation == token else { return }
            downloadStates[key] = local == nil ? (downloadTasks[key] == nil ? .absent : .downloading) : .ready
        } catch {
            guard preparation == token else { return }
            downloadStates[key] = .failed("离线文件需要重新下载。")
        }
        guard preparation == token else { return }
        do {
            let url = try local ?? track.mediaURL(relativeTo: mediaOrigin)
            usingOfflineAudio = local != nil
            playback.load(week: week, track: track, url: url)
        } catch { errorMessage = "这条音频的地址无效，未开始播放。" }
    }

    func retryAudio() async {
        guard let week = selectedWeek else { return }
        await select(week: week, track: selectedTrack, force: true)
    }

    func downloadSelected() {
        guard let week = selectedWeek, let track = selectedTrack, let library = offlineLibrary else { return }
        let key = track.identity(weekID: week.id).key
        guard downloadTasks[key] == nil else { return }
        downloadStates[key] = .downloading
        downloadTasks[key] = Task { [weak self] in
            do {
                _ = try await library.download(track: track)
                try Task.checkCancellation()
                guard let self else { return }
                self.downloadStates[key] = .ready
                self.downloadTasks[key] = nil
                // Switch automatically only before listening starts. A completed
                // download must never reset or interrupt an active audio source.
                if self.selectionKey == key && !self.showingPublishedLanguagePage
                    && !self.playback.hasUserInteraction
                    && self.playback.resumePosition == nil, let currentWeek = self.selectedWeek,
                    let currentTrack = self.selectedTrack {
                    await self.select(week: currentWeek, track: currentTrack, force: true)
                }
            } catch is CancellationError {
                self?.downloadStates[key] = .absent
                self?.downloadTasks[key] = nil
            } catch {
                self?.downloadStates[key] = .failed(error.localizedDescription)
                self?.downloadTasks[key] = nil
            }
        }
    }

    func cancelDownload() {
        guard let key = selectionKey else { return }
        downloadTasks[key]?.cancel()
    }

    var currentCue: SubtitleCue? { selectedTrack?.cue(at: playback.position) }
}

private struct ContentLanguagePreferences: Codable {
    let schemaVersion: String
    var preferredContentLocale: String?
    var pageSelections: [String: String]

    static let empty = ContentLanguagePreferences(
        schemaVersion: "tongxing-language-preferences-v2",
        preferredContentLocale: nil,
        pageSelections: [:]
    )
}
