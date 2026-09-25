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
    @Published private(set) var selectedPageID: String?
    @Published private(set) var selectedContentLocale = "zh-Hans"
    @Published private(set) var isSelectingLanguage = false
    @Published private(set) var languageSelectionError: String?
    @Published private(set) var selectedAudioLocale: String?
    @Published private(set) var publishedAudioSha256: String?
    @Published private(set) var isPreparingPublishedAudio = false
    @Published private(set) var publishedAudioError: String?
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
    private var offlineLibrary: OfflineLibrary?
    let mediaOrigin: URL
    let mediaSession: URLSession
    private let languagePreferenceURL: URL
    private var languagePreferences: ContentLanguagePreferences
    private var started = false
    private var preparation = UUID()
    private var publishedAudioRequest = UUID()
    private var downloadTasks: [String: Task<Void, Never>] = [:]

    init(supportDirectory: URL? = nil, contentOrigin: URL? = nil, session: URLSession = .shared) {
        let support = supportDirectory ?? FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask).first!
            .appendingPathComponent("Tongxing", isDirectory: true)
        mediaOrigin = contentOrigin ?? Self.contentOrigin
        mediaSession = session
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
            session: session,
            allowDevCandidate: mediaOrigin.host == "ai-for-god-sermon-audio-dev.web.app"
        )
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
            getPublishedSelection: { [weak self] in
                guard let self, self.selectedWeek == nil,
                      let page = self.selectedMultilingualPage,
                      let locale = self.selectedAudioLocale,
                      let sha = self.publishedAudioSha256,
                      self.playback.isReady else { return nil }
                return .init(page: page, locale: locale, trackSha256: sha,
                             durationSeconds: self.playback.duration)
            },
            loadPageIndex: { selected in
                guard let binding = selected.page.targets[selected.locale]?.audioFingerprint else {
                    throw AudioAlignmentError.unavailable
                }
                return try await indexStore.loadPublished(binding: binding, page: selected.page,
                                                          locale: selected.locale,
                                                          trackSha256: selected.trackSha256,
                                                          durationSeconds: selected.durationSeconds)
            },
            onState: { [weak self] status, busy, position in
                self?.updateAlignmentState(status: status, busy: busy, position: position)
            }
        )
        playback.onManualInteraction = { [weak self] in self?.alignmentController.cancel() }

    }

    var weeks: [SermonWeek] { catalog?.weeks ?? [] }
    var independentPages: [MultilingualPage] {
        let legacyIDs = Set(weeks.map(\.id))
        return multilingualCatalog?.pages.filter { !legacyIDs.contains($0.id) && !$0.publishedTargets.isEmpty } ?? []
    }
    var selectedMultilingualPage: MultilingualPage? {
        guard let multilingualCatalog else { return nil }
        if let selectedPageID { return multilingualCatalog.pages.first(where: { $0.id == selectedPageID }) }
        if let selectedWeek { return multilingualCatalog.pages.first(where: { $0.id == selectedWeek.id }) }
        return multilingualCatalog.defaultPage
    }
    var availableContentLanguages: [(locale: String, target: PageTarget)] {
        selectedMultilingualPage?.publishedTargets ?? []
    }
    var selectedContentTarget: PageTarget? { selectedMultilingualPage?.targets[selectedContentLocale] }
    var selectedContentLanguageName: String { Self.languageName(selectedContentLocale) }
    var selectedAudioLanguageName: String? { selectedAudioLocale.map(Self.languageName) }
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
            if selectedWeek != nil || selectedPageID == nil {
                let next = result.catalog.weeks.first { $0.id == selectedWeek?.id } ?? result.catalog.defaultWeek
                let track = next.tracks.first { $0.id == selectedTrack?.id } ?? next.tracks.first
                await select(week: next, track: track)
            }
            await refreshMultilingualCatalog(pageID: selectedPageID)
        } catch {
            errorMessage = "暂时无法读取证道目录。请连接网络后重试。"
            await refreshMultilingualCatalog(pageID: selectedPageID)
        }
    }

    private func refreshMultilingualCatalog(pageID: String?) async {
        guard let multilingualRepository else { return }
        do {
            let oldAudioTarget = selectedAudioLocale.flatMap { selectedMultilingualPage?.targets[$0] }
            let oldSourceIdentity = selectedMultilingualPage?.sourceIdentitySha256
            let result = try await multilingualRepository.loadCatalog()
            multilingualCatalog = result.catalog
            multilingualNotice = result.warning
            if let pageID, result.catalog.pages.contains(where: { $0.id == pageID }) {
                selectedPageID = pageID
            } else if selectedWeek == nil {
                selectedPageID = result.catalog.defaultPageId
            }
            resolveContentLanguage(pageID: selectedPageID)
            if let selectedAudioLocale,
               (selectedMultilingualPage?.targets[selectedAudioLocale] != oldAudioTarget
                || selectedMultilingualPage?.sourceIdentitySha256 != oldSourceIdentity) {
                publishedAudioRequest = UUID()
                isPreparingPublishedAudio = false
                playback.clear()
                self.selectedAudioLocale = nil
                publishedAudioSha256 = nil
                alignmentController.cancel()
                resetAlignmentState()
            }
        } catch {
            // The legacy Chinese catalog remains a valid migration path while a
            // multilingual catalog has not been published to this environment.
            multilingualNotice = "此环境尚未提供多语言发布目录，继续显示当前中文版本。"
        }
    }

    func selectContentLanguage(_ locale: String) async -> VerifiedLanguagePage? {
        guard !isSelectingLanguage, let page = selectedMultilingualPage,
              page.targets[locale]?.contentStatus == "human_reviewed", let multilingualRepository else { return nil }
        isSelectingLanguage = true
        languageSelectionError = nil
        defer { isSelectingLanguage = false }
        do {
            let package = try await multilingualRepository.loadRelease(page: page, locale: locale)
            let verifiedPage = try await multilingualRepository.loadPage(for: package)
            guard selectedMultilingualPage?.id == page.id else { return nil }
            if selectedAudioLocale != nil && selectedAudioLocale != locale {
                playback.clear()
                selectedAudioLocale = nil
                publishedAudioSha256 = nil
                alignmentController.cancel()
                resetAlignmentState()
            }
            publishedAudioRequest = UUID()
            isPreparingPublishedAudio = false
            publishedAudioError = nil
            selectedContentLocale = locale
            languagePreferences.preferredContentLocale = locale
            languagePreferences.pageSelections[page.id] = locale
            persistLanguagePreferences()
            return verifiedPage
        } catch {
            languageSelectionError = "暂时无法打开这个语言版本；当前内容和音频没有改变。"
            return nil
        }
    }

    private func resolveContentLanguage(pageID: String?) {
        guard let catalog = multilingualCatalog else { return }
        let page: MultilingualPage
        if let pageID {
            guard let matching = catalog.pages.first(where: { $0.id == pageID }) else {
                selectedContentLocale = "zh-Hans"
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
    }

    private func persistLanguagePreferences() {
        do {
            try FileManager.default.createDirectory(at: languagePreferenceURL.deletingLastPathComponent(), withIntermediateDirectories: true)
            try JSONEncoder().encode(languagePreferences).write(to: languagePreferenceURL, options: .atomic)
        } catch {
            languageSelectionError = "语言已选择，但本次偏好暂时无法保存。"
        }
    }

    func selectPublishedPage(_ page: MultilingualPage) {
        guard independentPages.contains(where: { $0.id == page.id }) else { return }
        publishedAudioRequest = UUID()
        isPreparingPublishedAudio = false
        playback.clear()
        preparation = UUID()
        alignmentController.cancel()
        selectedWeek = nil
        selectedTrack = nil
        selectedPageID = page.id
        selectedAudioLocale = nil
        publishedAudioSha256 = nil
        publishedAudioError = nil
        isPreparing = false
        usingOfflineAudio = false
        display = .current
        languageSelectionError = nil
        resolveContentLanguage(pageID: page.id)
        resetAlignmentState()
    }

    func prepareSelectedPublishedAudio() async {
        guard selectedWeek == nil, !isPreparingPublishedAudio,
              let page = selectedMultilingualPage,
              page.targets[selectedContentLocale]?.audioStatus == "human_reviewed",
              let multilingualRepository else { return }
        let locale = selectedContentLocale
        guard let requestedTarget = page.targets[locale] else { return }
        let request = UUID()
        publishedAudioRequest = request
        isPreparingPublishedAudio = true
        publishedAudioError = nil
        defer { if publishedAudioRequest == request { isPreparingPublishedAudio = false } }
        do {
            let package = try await multilingualRepository.loadRelease(page: page, locale: locale)
            let audio = try await multilingualRepository.loadAudio(for: package, page: page)
            guard publishedAudioRequest == request, selectedWeek == nil,
                  let currentPage = selectedMultilingualPage,
                  currentPage.id == page.id,
                  currentPage.sourceIdentitySha256 == page.sourceIdentitySha256,
                  currentPage.targets[locale] == requestedTarget,
                  selectedContentLocale == locale else { return }
            playback.loadPublishedAudio(audio)
            selectedAudioLocale = locale
            publishedAudioSha256 = audio.sha256
            resetAlignmentState()
        } catch {
            guard publishedAudioRequest == request else { return }
            publishedAudioError = "无法下载或校验所选语言音频，请联网后重试。"
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
        publishedAudioRequest = UUID()
        isPreparingPublishedAudio = false
        selectedAudioLocale = nil
        publishedAudioSha256 = nil
        publishedAudioError = nil
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
            selectedPageID = week.id
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
        selectedPageID = week.id
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
                if self.selectionKey == key && !self.playback.hasUserInteraction
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
