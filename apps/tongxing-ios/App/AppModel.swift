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

    static func permitsDevCandidates(origin: URL, bundleIdentifier: String?) -> Bool {
        bundleIdentifier == "com.jonathanjing.tongxing.beta" && origin.scheme == "https"
            && origin.host == "ai-for-god-sermon-audio-dev.web.app"
            && (origin.port == nil || origin.port == 443) && origin.user == nil && origin.password == nil
            && origin.query == nil && origin.fragment == nil
    }

    static func selectableTargets(in page: MultilingualPage, allowDevCandidates: Bool) -> [(locale: String, target: PageTarget)] {
        guard allowDevCandidates || (page.diagnosticOnly != true && page.simulationOnly != true) else { return [] }
        return page.targets.filter { _, target in
            (target.contentStatus == "human_reviewed" || (allowDevCandidates && target.contentStatus == "machine_reviewed"))
                && (allowDevCandidates || (target.diagnosticOnly != true && target.simulationOnly != true))
        }.sorted { $0.key.localizedStandardCompare($1.key) == .orderedAscending }
            .map { (locale: $0.key, target: $0.value) }
    }

    let allowsDevCandidates: Bool
    let playback: PlaybackController
    @Published private(set) var catalog: WeeklyCatalog?
    @Published private(set) var selectedWeek: SermonWeek? {
        didSet { rebuildBilingualRows() }
    }
    @Published private(set) var selectedTrack: SermonTrack? {
        didSet { rebuildBilingualRows() }
    }
    @Published private(set) var isLoading = false
    @Published private(set) var isPreparing = false
    @Published private(set) var errorMessage: String?
    @Published private(set) var catalogNotice: String?
    @Published private(set) var multilingualCatalog: MultilingualCatalog?
    @Published private(set) var multilingualNotice: String?
    @Published private(set) var selectedPageID: String?
    @Published private(set) var selectedContentLocale = "zh-Hans" {
        didSet { playback.statisticsContentLocale = selectedContentLocale }
    }
    @Published private(set) var isSelectingLanguage = false
    @Published private(set) var languageSelectionError: String?
    @Published private(set) var selectedAudioLocale: String?
    @Published private(set) var publishedAudioSha256: String?
    @Published private(set) var isPreparingPublishedAudio = false
    @Published private(set) var publishedAudioError: String?
    @Published private(set) var publishedTranscript: VerifiedPublishedTranscript? {
        didSet {
            publishedCaptionsByID = Dictionary(uniqueKeysWithValues:
                (publishedTranscript?.captions ?? []).map { ($0.id, $0) })
            transcriptRowsRevision = UUID()
        }
    }
    @Published private(set) var publishedCaptionsByID: [String: PublishedTranscriptCue] = [:]
    @Published private(set) var bilingualRows: BilingualTranscriptRows?

    // A scalar invalidation token keeps view observation independent of cue count.
    @Published private(set) var transcriptRowsRevision = UUID()

    // Selection changes invalidate derived text; player ticks never rebuild it.
    private func rebuildBilingualRows() {
        bilingualRows = selectedTrack.flatMap { selectedWeek?.bilingualCueRows(for: $0) }
        transcriptRowsRevision = UUID()
    }
    @Published private(set) var isLoadingPublishedTranscript = false
    private var verifiedTranscriptSelectionKey: String?
    @Published private(set) var publishedTranscriptError: String?
    @Published private var publishedHeadings: [String: SermonHeading] = [:]
    private var transcriptRequest = UUID()
    @Published private(set) var downloadStates: [String: DownloadState] = [:]
    @Published private(set) var usingOfflineAudio = false
    @Published var display: ListeningDisplay = .current
    @Published private(set) var alignmentStatus = "请播放同一录音的原声，再点击听声对齐。"
    @Published private(set) var alignmentBusy = false
    @Published private(set) var alignmentPosition: Double?
    private var alignmentController: AudioAlignmentController!
    private(set) var hasAlignmentFeedback = false
    struct AlignmentFailure: Identifiable {
        let id = UUID()
        let message: String
    }
    @Published private(set) var alignmentFailure: AlignmentFailure?

    func dismissAlignmentFailure() { alignmentFailure = nil }

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
        if busy { dismissAlignmentFailure() }
        alignmentStatus = status
        alignmentBusy = busy
        alignmentPosition = position
        hasAlignmentFeedback = true
    }

    private func resetAlignmentState() {
        dismissAlignmentFailure()
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
        dismissAlignmentFailure()
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
    private var publishedSelectionRevision = UUID()
    private var languageSelectionRequest = UUID()
    private var publishedAudioTask: Task<VerifiedLanguageAudio, Error>?
    private var downloadTasks: [String: Task<Void, Never>] = [:]

    private func cancelPublishedAudioPreparation() {
        publishedAudioTask?.cancel()
        publishedAudioTask = nil
        publishedAudioRequest = UUID()
        isPreparingPublishedAudio = false
    }

    private func preparePublishedAudioIfNeeded() {
        guard selectedWeek == nil, selectedAudioLocale == nil,
              selectedContentTarget?.audioStatus == "human_reviewed",
              !isPreparingPublishedAudio, !playback.isPreview else { return }
        Task { [weak self] in await self?.prepareSelectedPublishedAudio() }
    }

    init(supportDirectory: URL? = nil, contentOrigin: URL? = nil, session: URLSession = .shared, statisticsDefaults: UserDefaults = .standard,
         alignmentCapture: (any MicrophoneCapturing)? = nil,
         applicationBundleIdentifier: String? = Bundle.main.bundleIdentifier) {
        let support = supportDirectory ?? FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask).first!
            .appendingPathComponent("Tongxing", isDirectory: true)
        mediaOrigin = contentOrigin ?? Self.contentOrigin
        mediaSession = session
        allowsDevCandidates = Self.permitsDevCandidates(origin: mediaOrigin, bundleIdentifier: applicationBundleIdentifier)
        languagePreferenceURL = support.appendingPathComponent("tongxing-language-preferences-v2.json")
        let savedPreferences = try? JSONDecoder().decode(ContentLanguagePreferences.self,
            from: Data(contentsOf: languagePreferenceURL))
        languagePreferences = savedPreferences?.schemaVersion == "tongxing-language-preferences-v2"
            ? savedPreferences! : .empty
        playback = PlaybackController(historyURL: support.appendingPathComponent("playback-history-v1.json"))
        playback.configureStatistics(origin: mediaOrigin, defaults: statisticsDefaults, session: contentOrigin == nil ? nil : session)
        repository = CatalogRepository(
                catalogURL: mediaOrigin.appendingPathComponent("weekly.json"),
                cacheDirectory: support.appendingPathComponent("Catalog", isDirectory: true),
                session: session
            )
        multilingualRepository = MultilingualCatalogRepository(
            origin: mediaOrigin,
            cacheDirectory: support.appendingPathComponent("MultilingualCatalog", isDirectory: true),
            session: session,
            allowDevCandidate: allowsDevCandidates
        )
        offlineLibrary = OfflineLibrary(
                directory: support.appendingPathComponent("Audio", isDirectory: true),
                baseURL: mediaOrigin,
                session: session
            )
        let indexStore = FingerprintIndexStore(directory: support.appendingPathComponent("Alignment", isDirectory: true),
                                               baseURL: mediaOrigin, session: session)
        alignmentController = AudioAlignmentController(
            playback: playback, capture: alignmentCapture ?? MicrophoneCapture(),
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
            },
            onFailure: { [weak self] message in self?.alignmentFailure = AlignmentFailure(message: message) },
            onPhase: { [weak self] phase in self?.playback.setAlignmentPhase(phase) }
        )
        playback.onManualInteraction = { [weak self] in self?.alignmentController.cancel() }

    }

    var weeks: [SermonWeek] { catalog?.weeks ?? [] }
    var independentPages: [MultilingualPage] {
        let legacyIDs = Set(weeks.map(\.id))
        return multilingualCatalog?.pages.filter { !legacyIDs.contains($0.id) && !Self.selectableTargets(in: $0, allowDevCandidates: allowsDevCandidates).isEmpty } ?? []
    }
    var selectedMultilingualPage: MultilingualPage? {
        guard let multilingualCatalog else { return nil }
        if let selectedPageID { return multilingualCatalog.pages.first(where: { $0.id == selectedPageID }) }
        if let selectedWeek { return multilingualCatalog.pages.first(where: { $0.id == selectedWeek.id }) }
        return multilingualCatalog.defaultPage
    }
    var availableContentLanguages: [(locale: String, target: PageTarget)] {
        selectedMultilingualPage.map { Self.selectableTargets(in: $0, allowDevCandidates: allowsDevCandidates) } ?? []
    }
    private func canSelectContent(_ locale: String, in page: MultilingualPage) -> Bool {
        Self.selectableTargets(in: page, allowDevCandidates: allowsDevCandidates).contains { $0.locale == locale }
    }
    var selectedContentReviewNotice: String? {
        if selectedContentTarget?.contentStatus == "machine_reviewed" {
            return "Dev 候选 · 仅机器审核，人工全文审核未批准。"
        }
        if publishedTranscript?.releaseStatus == "candidate" {
            return "Dev 候选 · 发布与设备验收尚未完成。"
        }
        return nil
    }
    var selectedContentTarget: PageTarget? { selectedMultilingualPage?.targets[selectedContentLocale] }
    var fullVideoURL: URL? {
        guard multilingualCatalog?.schemaVersion == MultilingualCatalog.dualScriptSchemaVersion,
              let page = selectedMultilingualPage, page.mediaType != "podcast" else { return nil }
        return mediaOrigin.appendingPathComponent("pages/\(page.id)/full-video-browser.mp4")
    }
    var usesNativePublishedReader: Bool {
        selectedWeek == nil && multilingualCatalog?.schemaVersion == MultilingualCatalog.dualScriptSchemaVersion
    }
    var publishedTranscriptSelectionKey: String? {
        guard usesNativePublishedReader, let page = selectedMultilingualPage,
              let target = selectedContentTarget else { return nil }
        return "\(page.id):\(selectedContentLocale):\(target.releasePackageJsonSha256)"
    }

    var currentPublishedTranscript: VerifiedPublishedTranscript? {
        guard let transcript = publishedTranscript, let page = selectedMultilingualPage,
              selectedWeek == nil, verifiedTranscriptSelectionKey == publishedTranscriptSelectionKey,
              transcript.pageID == page.id, transcript.locale == selectedContentLocale,
              transcript.sourceIdentitySha256 == page.sourceIdentitySha256 else { return nil }
        return transcript
    }

    func publishedHeadingKey(_ page: MultilingualPage) -> String {
        "\(page.id):\(page.sourceIdentitySha256):\(page.targets[page.defaultTargetLocale]?.releasePackageJsonSha256 ?? "")"
    }

    func heading(for week: SermonWeek) -> SermonHeading {
        SermonHeading(title: SermonHeading.displayTitle(week.title, pageID: week.id, date: week.date,
                                                       fallback: AppLocalization.shared.text("证道")),
                      series: week.series, speaker: week.speaker)
    }

    func heading(for page: MultilingualPage) -> SermonHeading {
        if let transcript = currentPublishedTranscript, transcript.pageID == page.id,
           transcript.sourceIdentitySha256 == page.sourceIdentitySha256 {
            return SermonHeading(title: displayTitle(transcript.title ?? page.title, for: page),
                                 series: transcript.series, speaker: transcript.speaker)
        }
        return publishedHeadings[publishedHeadingKey(page)] ?? SermonHeading(title: displayTitle(page.title, for: page))
    }

    private func displayTitle(_ title: String?, for page: MultilingualPage) -> String {
        SermonHeading.displayTitle(title, pageID: page.id, date: page.date,
                                   fallback: AppLocalization.shared.text("证道"))
    }

    /// Apply only metadata for the currently loaded, verified audio identity.
    func refreshSystemPresentation() {
        if let week = selectedWeek, let track = selectedTrack {
            let title = SermonHeading.displayTitle(week.title, pageID: week.id, date: week.date,
                                                   fallback: AppLocalization.shared.text("证道"))
            let rows = week.bilingualCueRows(for: track).rows
            playback.updateSystemMetadata(identity: track.identity(weekID: week.id), sourceID: week.sourceId,
                title: SermonHeading(title: title, series: week.series).title, speaker: week.speaker,
                subtitles: rows.map { PlaybackSystemSubtitle(id: "cue-\($0.index)", start: $0.cue.start,
                    end: $0.cue.end, chinese: $0.cue.text, english: $0.english) })
        } else if let page = selectedMultilingualPage, let locale = selectedAudioLocale,
                  let hash = publishedAudioSha256 {
            let heading = heading(for: page)
            let transcript = currentPublishedTranscript.flatMap {
                $0.pageID == page.id && $0.locale == locale && $0.sourceIdentitySha256 == page.sourceIdentitySha256 ? $0 : nil
            }
            playback.updateSystemMetadata(identity: TrackIdentity(weekID: page.id, trackID: "published_\(locale)", audioSHA256: hash),
                sourceID: page.sourceIdentitySha256, title: heading.title, speaker: heading.speaker ?? "",
                subtitles: (transcript?.captions ?? []).map {
                    PlaybackSystemSubtitle(id: $0.id, start: $0.start, end: $0.end,
                        chinese: locale == "zh-Hans" ? $0.text : nil,
                        english: locale == "en" ? $0.text : $0.english)
                })
        }
    }

    /// Only visible picker rows request metadata, through the existing verified
    /// text cache. This never selects a page or touches audio/playback state.
    func loadPublishedHeading(_ page: MultilingualPage) async {
        let key = publishedHeadingKey(page)
        guard publishedHeadings[key] == nil,
              multilingualCatalog?.schemaVersion == MultilingualCatalog.dualScriptSchemaVersion,
              canSelectContent(page.defaultTargetLocale, in: page),
              let multilingualRepository else { return }
        do {
            let package = try await multilingualRepository.loadRelease(page: page, locale: page.defaultTargetLocale)
            let transcript = try await multilingualRepository.loadPublishedTranscript(for: package, page: page)
            try Task.checkCancellation()
            guard independentPages.contains(where: { publishedHeadingKey($0) == key }) else { return }
            publishedHeadings[key] = SermonHeading(title: displayTitle(transcript.title ?? page.title, for: page),
                                                  series: transcript.series, speaker: transcript.speaker)
        } catch {
            // Metadata failure keeps the catalog title/date available, with no invented speaker.
        }
    }

    func loadSelectedPublishedTranscript() async {
        let request = UUID()
        transcriptRequest = request
        verifiedTranscriptSelectionKey = nil
        publishedTranscript = nil
        publishedTranscriptError = nil
        isLoadingPublishedTranscript = false
        guard let key = publishedTranscriptSelectionKey,
              let page = selectedMultilingualPage, let multilingualRepository else { return }
        let locale = selectedContentLocale
        isLoadingPublishedTranscript = true
        defer { if transcriptRequest == request { isLoadingPublishedTranscript = false } }
        do {
            let package = try await multilingualRepository.loadRelease(page: page, locale: locale)
            let transcript = try await multilingualRepository.loadPublishedTranscript(for: package, page: page)
            try Task.checkCancellation()
            guard transcriptRequest == request, publishedTranscriptSelectionKey == key else { return }
            verifiedTranscriptSelectionKey = key
            publishedTranscript = transcript
            if locale == page.defaultTargetLocale {
                publishedHeadings[publishedHeadingKey(page)] = SermonHeading(
                    title: displayTitle(transcript.title ?? page.title, for: page), series: transcript.series, speaker: transcript.speaker)
            }
            refreshSystemPresentation()
        } catch is CancellationError {
            return
        } catch {
            guard transcriptRequest == request, publishedTranscriptSelectionKey == key else { return }
            publishedTranscriptError = "文稿暂时无法读取，请重试。"
        }
    }

    func selectPublishedContentLanguage(_ locale: String) {
        guard usesNativePublishedReader, let page = selectedMultilingualPage,
              canSelectContent(locale, in: page) else { return }
        guard locale != selectedContentLocale else { return }
        publishedSelectionRevision = UUID()
        cancelPublishedAudioPreparation()
        playback.preparePublishedLanguageSwitch(pageID: page.id, sourceIdentity: page.sourceIdentitySha256)
        alignmentController.cancel()
        selectedAudioLocale = nil
        publishedAudioSha256 = nil
        publishedAudioError = nil
        publishedTranscript = nil
        publishedTranscriptError = nil
        transcriptRequest = UUID()
        selectedContentLocale = locale
        languagePreferences.preferredContentLocale = locale
        languagePreferences.pageSelections[page.id] = locale
        persistLanguagePreferences()
        resetAlignmentState()
        preparePublishedAudioIfNeeded()
    }
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
        let preferPublishedDefault = selectedWeek == nil && selectedPageID == nil
        if isPreparingPublishedAudio { cancelPublishedAudioPreparation() }
        isLoading = true
        defer { isLoading = false }
        do {
            let result = try await repository.load()
            catalog = result.catalog
            if let track = result.catalog.defaultWeek.tracks.first {
                playback.statisticsInterfaceVisit(source: ListeningSource(week: result.catalog.defaultWeek.date,
                    trackId: track.id, audioSha256: track.sha256))
            }
            catalogNotice = result.warning
            if result.source == .cache {
                catalogNotice = "当前使用上次保存的证道目录。\(result.warning ?? "连接网络后可刷新。")"
            }
            errorMessage = nil
            if let selectedWeek {
                let next = result.catalog.weeks.first { $0.id == selectedWeek.id } ?? result.catalog.defaultWeek
                let track = next.tracks.first { $0.id == selectedTrack?.id } ?? next.tracks.first
                await select(week: next, track: track)
            }
            await refreshMultilingualCatalog(pageID: selectedPageID, preferPublishedDefault: preferPublishedDefault)
            if selectedWeek == nil, selectedPageID == nil {
                let next = result.catalog.defaultWeek
                await select(week: next, track: next.tracks.first)
            }
        } catch {
            errorMessage = "暂时无法读取证道目录。请连接网络后重试。"
            await refreshMultilingualCatalog(pageID: selectedPageID, preferPublishedDefault: preferPublishedDefault)
        }
    }

    private func refreshMultilingualCatalog(pageID: String?, preferPublishedDefault: Bool = false) async {
        guard let multilingualRepository else { return }
        do {
            let oldAudioTarget = selectedAudioLocale.flatMap { selectedMultilingualPage?.targets[$0] }
            let oldSourceIdentity = selectedMultilingualPage?.sourceIdentitySha256
            let result = try await multilingualRepository.loadCatalog()
            multilingualCatalog = result.catalog
            multilingualNotice = result.warning
            let usePublishedDefault = preferPublishedDefault
                && result.catalog.schemaVersion == MultilingualCatalog.dualScriptSchemaVersion
                && independentPages.contains(where: { $0.id == result.catalog.defaultPageId })
            if usePublishedDefault {
                selectPublishedPage(result.catalog.defaultPage)
            }
            if !usePublishedDefault, let pageID, result.catalog.pages.contains(where: { $0.id == pageID }) {
                selectedPageID = pageID
            } else if selectedWeek == nil,
                      !weeks.contains(where: { $0.id == result.catalog.defaultPageId }) {
                selectedPageID = result.catalog.defaultPageId
            }
            resolveContentLanguage(pageID: selectedPageID)
            if selectedWeek == nil && (selectedMultilingualPage?.sourceIdentitySha256 != oldSourceIdentity
                || (selectedAudioLocale != nil && selectedAudioLocale.flatMap { selectedMultilingualPage?.targets[$0] } != oldAudioTarget)) {
                publishedSelectionRevision = UUID()
                cancelPublishedAudioPreparation()
                playback.clear()
                self.selectedAudioLocale = nil
                publishedAudioSha256 = nil
                alignmentController.cancel()
                resetAlignmentState()
            }
            preparePublishedAudioIfNeeded()
        } catch {
            // The legacy Chinese catalog remains a valid migration path while a
            // multilingual catalog has not been published to this environment.
            multilingualNotice = "此环境尚未提供多语言发布目录，继续显示当前中文版本。"
        }
    }

    func selectContentLanguage(_ locale: String) async -> VerifiedLanguagePage? {
        guard !isSelectingLanguage, let page = selectedMultilingualPage,
              canSelectContent(locale, in: page), let multilingualRepository else { return nil }
        let request = UUID()
        let selectionRevision = publishedSelectionRevision
        languageSelectionRequest = request
        isSelectingLanguage = true
        languageSelectionError = nil
        defer { if languageSelectionRequest == request { isSelectingLanguage = false } }
        do {
            let package = try await multilingualRepository.loadRelease(page: page, locale: locale)
            let verifiedPage = try await multilingualRepository.loadPage(for: package)
            try Task.checkCancellation()
            guard languageSelectionRequest == request, publishedSelectionRevision == selectionRevision,
                  selectedMultilingualPage?.id == page.id,
                  selectedMultilingualPage?.sourceIdentitySha256 == page.sourceIdentitySha256 else { return nil }
            if locale != selectedContentLocale {
                publishedSelectionRevision = UUID()
                cancelPublishedAudioPreparation()
                if selectedWeek == nil {
                    playback.preparePublishedLanguageSwitch(pageID: page.id, sourceIdentity: page.sourceIdentitySha256)
                }
                selectedAudioLocale = nil
                publishedAudioSha256 = nil
                alignmentController.cancel()
                resetAlignmentState()
            }
            publishedAudioError = nil
            selectedContentLocale = locale
            languagePreferences.preferredContentLocale = locale
            languagePreferences.pageSelections[page.id] = locale
            persistLanguagePreferences()
            preparePublishedAudioIfNeeded()
            return verifiedPage
        } catch {
            guard languageSelectionRequest == request, publishedSelectionRevision == selectionRevision else { return nil }
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
        selectedContentLocale = candidates.first(where: { canSelectContent($0, in: page) })
            ?? Self.selectableTargets(in: page, allowDevCandidates: allowsDevCandidates).first?.locale ?? "zh-Hans"
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
        guard selectedWeek != nil || selectedPageID != page.id else { return }
        publishedSelectionRevision = UUID()
        cancelPublishedAudioPreparation()
        playback.clear()
        preparation = UUID()
        alignmentController.cancel()
        selectedWeek = nil
        selectedTrack = nil
        selectedPageID = page.id
        publishedTranscript = nil
        publishedTranscriptError = nil
        transcriptRequest = UUID()
        selectedAudioLocale = nil
        publishedAudioSha256 = nil
        publishedAudioError = nil
        isPreparing = false
        usingOfflineAudio = false
        display = .current
        languageSelectionError = nil
        resolveContentLanguage(pageID: page.id)
        resetAlignmentState()
        preparePublishedAudioIfNeeded()
    }

    func prepareSelectedPublishedAudio() async {
        guard selectedWeek == nil, !isPreparingPublishedAudio,
              let page = selectedMultilingualPage,
              page.targets[selectedContentLocale]?.audioStatus == "human_reviewed",
              let multilingualRepository else { return }
        let locale = selectedContentLocale
        guard selectedAudioLocale != locale || !playback.isReady else { return }
        guard let requestedTarget = page.targets[locale] else { return }
        let request = UUID()
        publishedAudioRequest = request
        isPreparingPublishedAudio = true
        publishedAudioError = nil
        let audioTask = Task { () throws -> VerifiedLanguageAudio in
            let package = try await multilingualRepository.loadRelease(page: page, locale: locale)
            return try await multilingualRepository.loadAudio(for: package, page: page)
        }
        publishedAudioTask = audioTask
        defer {
            if publishedAudioRequest == request {
                publishedAudioTask = nil
                isPreparingPublishedAudio = false
            }
        }
        do {
            let audio = try await withTaskCancellationHandler {
                try await audioTask.value
            } onCancel: {
                audioTask.cancel()
            }
            try Task.checkCancellation()
            guard publishedAudioRequest == request, selectedWeek == nil,
                  let currentPage = selectedMultilingualPage,
                  currentPage.id == page.id,
                  currentPage.sourceIdentitySha256 == page.sourceIdentitySha256,
                  currentPage.targets[locale] == requestedTarget,
                  selectedContentLocale == locale,
                  !playback.isPreview else { return }
            playback.loadPublishedAudio(audio)
            selectedAudioLocale = locale
            publishedAudioSha256 = audio.sha256
            refreshSystemPresentation()
            resetAlignmentState()
        } catch is CancellationError {
            return
        } catch {
            guard publishedAudioRequest == request else { return }
            publishedAudioError = "无法下载或校验所选语言音频，请联网后重试。"
        }
    }

    func restorePublishedAudioAfterPreview() {
        guard selectedWeek == nil,
              selectedContentTarget?.audioStatus == "human_reviewed" else { return }
        cancelPublishedAudioPreparation()
        selectedAudioLocale = nil
        publishedAudioSha256 = nil
        alignmentController.cancel()
        resetAlignmentState()
        preparePublishedAudioIfNeeded()
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
        publishedSelectionRevision = UUID()
        cancelPublishedAudioPreparation()
        selectedAudioLocale = nil
        publishedAudioSha256 = nil
        publishedAudioError = nil
        publishedTranscript = nil
        transcriptRequest = UUID()
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
            refreshSystemPresentation()
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
            refreshSystemPresentation()
        } catch { errorMessage = "这条音频的地址无效，未开始播放。" }
    }

    func retryAudio() async {
        if let week = selectedWeek {
            await select(week: week, track: selectedTrack, force: true)
        } else if selectedContentTarget?.audioStatus == "human_reviewed" {
            cancelPublishedAudioPreparation()
            if let page = selectedMultilingualPage {
                playback.preparePublishedLanguageSwitch(pageID: page.id, sourceIdentity: page.sourceIdentitySha256)
            } else { playback.clear() }
            selectedAudioLocale = nil
            publishedAudioSha256 = nil
            await prepareSelectedPublishedAudio()
        }
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
