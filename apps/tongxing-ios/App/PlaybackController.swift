import AVFoundation
import Combine
import Foundation
import MediaPlayer
import TongxingCore
import TongxingInfrastructure
#if os(iOS)
import UIKit
#endif

/// The single owner of audio. Views observe AVPlayer instead of keeping a second
/// play/pause state; selecting, seeking and interruption callbacks are source-bound.
@MainActor
final class PlaybackController: ObservableObject {
    @Published private(set) var position = 0.0
    @Published private(set) var duration = 0.0
    @Published private(set) var offset = 0.0
    @Published private(set) var isPlaying = false
    @Published private(set) var isWaiting = false
    @Published private(set) var isReady = false
    @Published private(set) var message = "选择一篇证道，开始收听"
    @Published private(set) var resumePosition: ResumePosition?
    @Published private(set) var undoPosition: Double?
    @Published private(set) var storageWarning: String?
    @Published private(set) var publishedPositionRestoreFailed = false

    private(set) var alignmentRevision = UUID()
    var onManualInteraction: (() -> Void)?
    private var alignmentSeekRequest: UUID?

    private func manualInteraction() {
        alignmentRevision = UUID()
        cancelAlignmentSeek()
        onManualInteraction?()
        setAlignmentPhase(nil)
    }

    var alignmentPlaybackIntent: Bool { wantsPlayback || isPlaying || isWaiting }
    func pauseForAlignment() { pause(automatic: true) }
    func resumeAfterAlignment() { play(automatic: true) }

    func applyAlignedPosition(_ value: Double) async -> Bool {
        guard isReady, value.isFinite, value >= 0, value < duration else { return false }
        let request = UUID()
        alignmentSeekRequest = request
        return await withCheckedContinuation { continuation in
            seek(to: value, newOffset: 0, rememberUndo: true) { [weak self] success in
                if self?.alignmentSeekRequest == request { self?.alignmentSeekRequest = nil }
                continuation.resume(returning: success)
            }
        }
    }

    func cancelAlignmentSeek() {
        guard alignmentSeekRequest != nil else { return }
        alignmentSeekRequest = nil
        seekGeneration = UUID()
        pendingSeek = nil
        player.currentItem?.cancelPendingSeeks()
    }

    private let liveActivity = ListeningLiveActivityCoordinator()
    @Published private(set) var alignmentPhase: ListeningAlignmentPhase?
    private var alignmentSessionID: UUID?
    private var alignmentFeedbackTask: Task<Void, Never>?

    func setAlignmentPhase(_ phase: ListeningAlignmentPhase?) {
        // First ship this UI in the separately installed Beta app.
        let isBeta = Bundle.main.object(forInfoDictionaryKey: "TongxingURLScheme") as? String == "tongxing-beta"
        #if DEBUG
        // The isolated, explicitly opted-in synthetic smoke also runs under
        // the hosted Tongxing Debug identity. Release keeps the Beta gate.
        guard isBeta || UITestLaunch.liveActivitySmokeEnabled() else { return }
        #else
        guard isBeta else { return }
        #endif
        alignmentFeedbackTask?.cancel()
        if phase == .preparing { alignmentSessionID = UUID() }
        if phase == nil { alignmentSessionID = nil }
        alignmentPhase = phase
        publishLiveActivity()
        if let phase, !phase.isActive {
            alignmentFeedbackTask = Task { [weak self] in
                do { try await Task.sleep(for: .seconds(8)) } catch { return }
                guard let self else { return }
                self.alignmentPhase = nil
                self.alignmentSessionID = nil
                self.publishLiveActivity()
            }
        }
    }
    private var languageObservation: AnyCancellable?
    @Published private(set) var statisticsEnabled = UserDefaults.standard.bool(forKey: ListeningStatistics.preferenceKey)
    var statisticsContentLocale = "zh-Hans"
    private var statistics: ListeningStatistics?
    private var statisticsDefaults = UserDefaults.standard
    private var statisticsBootstrap: ListeningSource?
    private var statisticsForeground = true
    func setStatisticsForeground(_ value: Bool) {
        statisticsForeground = value
        if value { statisticsInterfaceVisit() }
        else { flushStatistics() }
    }

    func configureStatistics(origin: URL, defaults: UserDefaults = .standard, session: URLSession? = nil) {
        statisticsDefaults = defaults
        statisticsEnabled = defaults.bool(forKey: ListeningStatistics.preferenceKey)
        let version = Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String ?? "1.0.0"
        statistics = ListeningStatistics(origin: origin, appVersion: version, defaults: defaults, session: session)
    }

    func setStatisticsEnabled(_ enabled: Bool) {
        statisticsEnabled = enabled
        statisticsDefaults.set(enabled, forKey: ListeningStatistics.preferenceKey)
        Task { await statistics?.setEnabled(enabled) }
    }

    func statisticsInterfaceVisit(source: ListeningSource? = nil) {
        if let source { statisticsBootstrap = source }
        guard statisticsForeground, let source = statisticsBootstrap else { return }
        let locale = statisticsInterfaceLocale
        Task { await statistics?.interfaceVisit(source: source, locale: locale) }
    }

    private var statisticsInterfaceLocale: String {
        let code = AppLocalization.shared.language.rawValue
        return code.hasPrefix("zh") ? "zh-Hans" : code
    }

    func flushStatistics() { Task { await statistics?.flush() } }

    private func sampleStatistics(playing: Bool? = nil, clearing: Bool = false) {
        guard let statistics else { return }
        let source: ListeningSource?
        switch loadedSource {
        case .legacy(let week, let track, _):
            source = ListeningSource(week: week.date, trackId: track.id, audioSha256: track.sha256)
        case .published(let audio):
            source = .published(pageID: audio.pageID, locale: audio.locale, sha256: audio.sha256)
        case nil: source = nil
        }
        let observedPosition = currentPosition(), observedDuration = duration
        let observedPlaying = playing ?? (player.timeControlStatus == .playing && pendingSeek == nil)
        let uptime = ProcessInfo.processInfo.systemUptime
        let ui = statisticsInterfaceLocale, content = statisticsContentLocale
        Task {
            await statistics.sample(source: clearing ? nil : source, position: observedPosition,
                                    duration: observedDuration, playing: observedPlaying, uptime: uptime,
                                    interfaceLocale: ui, contentLocale: content)
        }
    }
    private var player = AVPlayer()
    private let historyURL: URL
    private let audioSessionActivator: any AudioSessionActivating
    // Production uses AVPlayer's result unchanged; hosted tests can force an
    // interrupted seek completion while retaining the real player and item.
    private let seekCompletionResult: @MainActor (Bool) -> Bool
    private var history = PlaybackHistory()
    private var identity: TrackIdentity?
    @Published private(set) var isPreview = false
    @Published private(set) var previewID: String?
    @Published private(set) var previewLoadFailed = false
    private(set) var isVideoPresented = false
    private var sourceID = ""
    private var title = ""
    private var speaker = ""
    #if os(iOS)
    private lazy var nowPlayingArtwork: MPMediaItemArtwork? = {
        guard let mark = UIImage(named: "BrandMark") else { return nil }
        return MPMediaItemArtwork(boundsSize: mark.size) { _ in mark }
    }()
    #endif
    private var systemSubtitles: [PlaybackSystemSubtitle] = []
    private var generation = UUID()
    private var seekGeneration = UUID()
    private var activationGeneration = UUID()
    private var activationTask: Task<Void, Never>?
    private var sessionIsActivated = false
    private var positionTouched = false
    private var wantsPlayback = false
    private var interruptedIntent = false
    private var interruptedGeneration: UUID?
    private var undoSnapshot: (position: Double, offset: Double)?
    private var pendingSeek: (position: Double, offset: Double)?
    private struct PublishedLanguageTransfer {
        let pageID: String
        let sourceIdentity: String
        let position: Double
        let duration: Double
        let offset: Double
        var autoplay: Bool
    }
    private var publishedLanguageTransfer: PublishedLanguageTransfer?

    /// Hold the requested timeline position while another reviewed locale is
    /// downloaded, including a text-only stop between two audio locales.
    func preparePublishedLanguageSwitch(pageID: String, sourceIdentity: String) {
        let retained: PublishedLanguageTransfer?
        if let existing = publishedLanguageTransfer,
           existing.pageID == pageID, existing.sourceIdentity == sourceIdentity {
            if isReady {
                retained = PublishedLanguageTransfer(pageID: pageID, sourceIdentity: sourceIdentity,
                    position: pendingSeek?.position ?? currentPosition(), duration: duration,
                    offset: pendingSeek?.offset ?? offset, autoplay: wantsPlayback || isPlaying)
            } else { retained = existing }
        } else if case .some(.published(let audio)) = loadedSource,
                  audio.pageID == pageID, audio.sourceIdentitySha256 == sourceIdentity {
            retained = PublishedLanguageTransfer(pageID: pageID, sourceIdentity: sourceIdentity,
                position: pendingSeek?.position ?? currentPosition(), duration: duration,
                offset: pendingSeek?.offset ?? offset, autoplay: wantsPlayback || isPlaying)
        } else {
            retained = nil
        }
        clear(retaining: retained)
    }
    private enum LoadedSource {
        case legacy(week: SermonWeek, track: SermonTrack, url: URL)
        case published(VerifiedLanguageAudio)
    }
    private var loadedSource: LoadedSource?
    private var lastSave = Date.distantPast
    private var timeObserver: Any?
    private var stateObservation: NSKeyValueObservation?
    private var itemObservation: NSKeyValueObservation?
    private var notifications: [NSObjectProtocol] = []
    private var remoteTargets: [(MPRemoteCommand, Any)] = []

    init(historyURL: URL, audioSessionActivator: any AudioSessionActivating = SystemAudioSessionActivator.shared,
         seekCompletionResult: @escaping @MainActor (Bool) -> Bool = { $0 }) {
        self.historyURL = historyURL
        self.audioSessionActivator = audioSessionActivator
        self.seekCompletionResult = seekCompletionResult
        if let data = try? Data(contentsOf: historyURL) {
            history = PlaybackHistory(data: data)
        }
        observePlayer()
        observeNotifications()
        configureRemoteCommands()
        languageObservation = AppLocalization.shared.$language.dropFirst().sink { [weak self] _ in
            Task { @MainActor [weak self] in self?.publishNowPlaying(); self?.statisticsInterfaceVisit(); self?.sampleStatistics(playing: false) }
        }
    }

    private func observePlayer() {
        timeObserver = player.addPeriodicTimeObserver(
            forInterval: CMTime(seconds: 0.25, preferredTimescale: 600), queue: .main
        ) { [weak self] _ in
            Task { @MainActor [weak self] in self?.tick() }
        }
        stateObservation = player.observe(\.timeControlStatus, options: [.initial, .new]) { [weak self] _, _ in
            Task { @MainActor [weak self] in self?.refreshTransport() }
        }
    }

    var hasUserInteraction: Bool { positionTouched || pendingSeek != nil || wantsPlayback }

    deinit {
        activationTask?.cancel()
        if let timeObserver { player.removeTimeObserver(timeObserver) }
        notifications.forEach(NotificationCenter.default.removeObserver)
        remoteTargets.forEach { $0.0.removeTarget($0.1) }
    }

    func load(week: SermonWeek, track: SermonTrack, url: URL) {
        let next = track.identity(weekID: week.id)
        let previousSourceURL: String?
        if case .some(.legacy(let previousWeek, _, _)) = loadedSource { previousSourceURL = previousWeek.sourceUrl }
        else { previousSourceURL = nil }
        guard next != identity || sourceID != week.sourceId || previousSourceURL != week.sourceUrl else {
            updateMetadata(week: week, track: track)
            return
        }
        loadSource(identity: next, sourceID: week.sourceId, title: SermonHeading(title: SermonHeading.displayTitle(week.title, pageID: week.id, date: week.date, fallback: AppLocalization.shared.text("证道")), series: week.series).title, speaker: week.speaker,
                   url: url, duration: track.durationSeconds, source: .legacy(week: week, track: track, url: url))
    }

    func loadPublishedAudio(_ audio: VerifiedLanguageAudio) {
        let next = TrackIdentity(weekID: audio.pageID, trackID: "published_\(audio.locale)", audioSHA256: audio.sha256)
        guard next.isValid, audio.localURL.isFileURL, audio.sourceIdentitySha256.count == 64 else { return }
        if next == identity, sourceID == audio.sourceIdentitySha256, !publishedPositionRestoreFailed { return }
        let transfer = publishedLanguageTransfer.flatMap {
            $0.pageID == audio.pageID && $0.sourceIdentity == audio.sourceIdentitySha256 ? $0 : nil
        }
        loadSource(identity: next, sourceID: audio.sourceIdentitySha256, title: SermonHeading.displayTitle(nil, pageID: audio.pageID, date: "", fallback: AppLocalization.shared.text("证道")),
                   speaker: "", url: audio.localURL, duration: 0, source: .published(audio),
                   transfer: transfer)
    }

    private func loadSource(identity next: TrackIdentity, sourceID nextSourceID: String,
                            title nextTitle: String, speaker nextSpeaker: String, url: URL,
                            duration estimatedDuration: Double, source: LoadedSource,
                            transfer: PublishedLanguageTransfer? = nil) {
        sampleStatistics(playing: false, clearing: true)
        manualInteraction()
        saveProgress()
        invalidateActivation()
        if player.status == .failed { recreatePlayer() }
        player.pause()
        wantsPlayback = false
        interruptedIntent = false
        interruptedGeneration = nil
        generation = UUID()
        seekGeneration = UUID()
        itemObservation = nil
        isPreview = false
        previewID = nil
        previewLoadFailed = false
        identity = next
        loadedSource = source
        sourceID = nextSourceID
        title = nextTitle
        speaker = nextSpeaker
        systemSubtitles = []
        publishedLanguageTransfer = transfer
        publishedPositionRestoreFailed = false
        position = transfer?.position ?? 0
        duration = transfer?.duration ?? estimatedDuration
        offset = transfer?.offset ?? 0
        positionTouched = false
        pendingSeek = nil
        undoSnapshot = nil
        undoPosition = nil
        isReady = false
        isPlaying = false
        isWaiting = false
        message = "正在准备音频…"
        resumePosition = transfer == nil ? history.resume(identity: next, sourceID: sourceID, duration: duration) : nil
        let token = generation
        let item = AVPlayerItem(url: url)
        itemObservation = item.observe(\.status, options: [.initial, .new]) { [weak self] _, _ in
            Task { @MainActor [weak self] in
                guard let self, self.generation == token else { return }
                switch item.status {
                case .readyToPlay:
                    let measured = item.duration.seconds
                    if measured.isFinite, measured > 0 {
                        self.duration = measured
                        if self.publishedLanguageTransfer == nil, !self.positionTouched, let identity = self.identity {
                            self.resumePosition = self.history.resume(identity: identity, sourceID: self.sourceID, duration: measured)
                        }
                    }
                    self.isReady = true
                    if let transfer = self.publishedLanguageTransfer {
                        self.wantsPlayback = transfer.autoplay && transfer.position < self.duration - 0.1
                        self.seek(to: transfer.position, newOffset: transfer.offset, rememberUndo: false)
                        self.updateRemoteAvailability()
                        self.publishNowPlaying()
                        return
                    }
                    self.message = self.resumePosition == nil
                        ? (self.isPublishedAudio ? "音频就绪 · 可以播放" : "音频就绪 · 请按现场起点开始")
                        : "已找到上次收听的位置"
                    self.updateRemoteAvailability()
                    self.publishNowPlaying()
                case .failed:
                    self.isReady = false
                    self.wantsPlayback = false
                    self.invalidateActivation()
                    self.message = "音频加载失败，请检查网络或使用已下载版本。"
                    self.liveActivity.end()
                    self.updateRemoteAvailability()
                case .unknown: break
                @unknown default: break
                }
            }
        }
        player.replaceCurrentItem(with: item)
        updateRemoteAvailability()
        publishNowPlaying()
    }

    /// Play a locally verified audition sample through the same player. Demos
    /// have no weekly identity, bookmark, alignment, or live activity.
    func loadPreview(url: URL, title: String, previewID: String? = nil) {
        guard url.isFileURL else { return }
        clear()
        isPreview = true
        self.previewID = previewID
        wantsPlayback = true
        self.title = title
        speaker = ""
        message = "正在准备音频…"
        let token = generation
        let item = AVPlayerItem(url: url)
        itemObservation = item.observe(\.status, options: [.initial, .new]) { [weak self] _, _ in
            Task { @MainActor [weak self] in
                guard let self, self.generation == token, self.isPreview else { return }
                switch item.status {
                case .readyToPlay:
                    let measured = item.duration.seconds
                    guard measured.isFinite, measured > 0 else {
                        self.previewLoadFailed = true
                        self.wantsPlayback = false
                        self.message = "音频加载失败，请检查网络或使用已下载版本。"
                        return
                    }
                    self.duration = measured
                    self.isReady = true
                    self.updateRemoteAvailability()
                    if self.wantsPlayback { self.startPlayback() }
                    else { self.refreshTransport() }
                case .failed:
                    self.previewLoadFailed = true
                    self.wantsPlayback = false
                    self.message = "音频加载失败，请检查网络或使用已下载版本。"
                case .unknown: break
                @unknown default: break
                }
            }
        }
        player.replaceCurrentItem(with: item)
    }

    private var isPublishedAudio: Bool {
        if case .some(.published) = loadedSource { return true }
        return false
    }

    func clear() { clear(retaining: nil) }

    private func clear(retaining transfer: PublishedLanguageTransfer?) {
        setAlignmentPhase(nil)
        publishedLanguageTransfer = nil
        sampleStatistics(playing: false, clearing: true)
        saveProgress()
        pause()
        generation = UUID()
        seekGeneration = UUID()
        player.replaceCurrentItem(with: nil)
        itemObservation = nil
        isPreview = false
        previewID = nil
        previewLoadFailed = false
        identity = nil
        loadedSource = nil
        systemSubtitles = []
        pendingSeek = nil
        resumePosition = nil
        undoPosition = nil
        undoSnapshot = nil
        isReady = false
        publishedLanguageTransfer = transfer
        publishedPositionRestoreFailed = false
        position = transfer?.position ?? 0
        duration = transfer?.duration ?? 0
        offset = transfer?.offset ?? 0
        message = "正在准备所选证道…"
        updateRemoteAvailability()
        MPNowPlayingInfoCenter.default().nowPlayingInfo = nil
        liveActivity.end()
    }

    func updateMetadata(week: SermonWeek, track: SermonTrack) {
        guard identity == track.identity(weekID: week.id), sourceID == week.sourceId,
              case .some(.legacy(_, _, let url)) = loadedSource else { return }
        title = SermonHeading(title: SermonHeading.displayTitle(week.title, pageID: week.id, date: week.date, fallback: AppLocalization.shared.text("证道")), series: week.series).title
        speaker = week.speaker
        self.loadedSource = .legacy(week: week, track: track, url: url)
        publishNowPlaying()
    }

    /// Caller supplies reviewed, explicitly mapped subtitle intervals for this
    /// exact loaded track. The player never guesses cross-language time mapping.
    func updateSystemMetadata(identity expected: TrackIdentity, sourceID expectedSourceID: String,
                              title: String, speaker: String, subtitles: [PlaybackSystemSubtitle]) {
        guard identity == expected, sourceID == expectedSourceID else { return }
        self.title = SermonHeading.displayTitle(title, pageID: expected.weekID, date: "",
                                              fallback: AppLocalization.shared.text("证道"))
        self.speaker = speaker
        systemSubtitles = subtitles.filter { $0.start.isFinite && $0.end.isFinite && $0.start >= 0 && $0.end > $0.start }
            .sorted { $0.start < $1.start }
        publishNowPlaying()
    }

    var currentSystemSubtitle: PlaybackSystemSubtitle? {
        guard pendingSeek == nil else { return nil }
        return systemSubtitles.first { position >= $0.start && position < $0.end }
    }

    func toggle() {
        if wantsPlayback || isPlaying || isWaiting { pause() }
        else { play() }
    }

    /// The system play command uses this same owner, so it cannot overlap video audio.
    func setVideoPresented(_ presented: Bool) {
        isVideoPresented = presented
        if presented { pause() }
    }

    func play(automatic: Bool = false) {
        guard !isVideoPresented else { return }
        if isPreview { previewLoadFailed = false }
        if !automatic { manualInteraction() }
        guard isReady else { return }
        wantsPlayback = true
        publishedLanguageTransfer?.autoplay = true
        // Finish the user's latest requested position before starting audio.
        // A pending restart must take precedence over an older resume card.
        if pendingSeek != nil { return }
        if resumePosition != nil { restore(autoplay: true); return }
        if position >= duration - 0.1 {
            seek(to: 0, newOffset: 0, rememberUndo: false)
            return
        }
        startPlayback()
    }

    private func startPlayback() {
        guard !isVideoPresented, isReady, wantsPlayback, pendingSeek == nil else { return }
        if sessionIsActivated {
            beginPlayerPlayback()
            return
        }
        guard activationTask == nil else { return }
        let sourceToken = generation
        let requestToken = UUID()
        activationGeneration = requestToken
        isWaiting = true
        message = "正在启用音频…"
        publishNowPlaying()
        activationTask = Task { [weak self, activator = audioSessionActivator] in
            do {
                try Task.checkCancellation()
                try await activator.activate()
                guard !Task.isCancelled, let self,
                      self.generation == sourceToken, self.activationGeneration == requestToken else { return }
                // Only this still-current request owns the task slot. An older
                // completion cannot clear a newer activation after pause/play.
                self.activationTask = nil
                guard self.wantsPlayback, self.isReady else { self.refreshTransport(); return }
                self.sessionIsActivated = true
                if self.pendingSeek == nil { self.beginPlayerPlayback() }
                else {
                    self.isWaiting = false
                    self.message = "正在定位…"
                }
            } catch {
                guard !Task.isCancelled, let self,
                      self.generation == sourceToken, self.activationGeneration == requestToken else { return }
                self.activationTask = nil
                guard self.wantsPlayback, self.isReady else { self.refreshTransport(); return }
                self.sessionIsActivated = false
                self.wantsPlayback = false
                self.refreshTransport()
                if self.isPreview { self.previewLoadFailed = true }
                self.message = "无法启用音频，请稍后再试。"
            }
        }
    }

    private func beginPlayerPlayback() {
        guard isReady, wantsPlayback, pendingSeek == nil else { return }
        positionTouched = true
        player.play()
        refreshTransport()
    }

    private func invalidateActivation() {
        activationGeneration = UUID()
        activationTask?.cancel()
        activationTask = nil
        sessionIsActivated = false
        isWaiting = player.timeControlStatus == .waitingToPlayAtSpecifiedRate
    }

    func pause(automatic: Bool = false) {
        publishedLanguageTransfer?.autoplay = false
        sampleStatistics(playing: false)
        if !automatic { manualInteraction() }
        wantsPlayback = false
        interruptedIntent = false
        invalidateActivation()
        player.pause()
        refreshTransport()
        saveProgress()
        if isReady { message = "已暂停" }
        publishNowPlaying()
    }

    func restore(autoplay: Bool = false) {
        manualInteraction()
        guard let saved = resumePosition, isReady else { return }
        if autoplay { wantsPlayback = true }
        seek(to: saved.position, newOffset: saved.offset, rememberUndo: true,
             completionMessage: "已恢复上次位置，现场可能已继续，请手动对齐。")
    }

    func restart() {
        manualInteraction()
        guard isReady else { return }
        seek(to: 0, newOffset: 0, rememberUndo: true,
             completionMessage: "已返回开头 · 请按现场起点开始")
    }

    func nudge(_ amount: Double) {
        manualInteraction()
        guard isReady, amount.isFinite else { return }
        let before = pendingSeek?.position ?? currentPosition()
        let after = max(0, min(duration, before + amount))
        seek(to: after, newOffset: (pendingSeek?.offset ?? offset) + after - before, rememberUndo: true)
    }

    func jump(to value: Double, completion: ((Bool) -> Void)? = nil) {
        manualInteraction()
        seek(to: value, newOffset: pendingSeek?.offset ?? offset, rememberUndo: true, completion: completion)
    }

    func undo() {
        manualInteraction()
        guard let snapshot = undoSnapshot else { return }
        undoSnapshot = nil
        undoPosition = nil
        seek(to: snapshot.position, newOffset: snapshot.offset, rememberUndo: false,
             completionMessage: "已返回 \(PlaybackTime.format(snapshot.position))")
    }

    private func seek(to value: Double, newOffset: Double, rememberUndo: Bool, completionMessage: String? = nil, completion: ((Bool) -> Void)? = nil) {
        guard isReady, value.isFinite, newOffset.isFinite, duration > 0 else { completion?(false); return }
        if rememberUndo {
            undoSnapshot = pendingSeek ?? (currentPosition(), offset)
            undoPosition = undoSnapshot?.position
        }
        sampleStatistics(playing: false)
        let destination = min(max(0, value), duration)
        let destinationOffset = min(duration, max(-duration, newOffset))
        let token = generation
        let seekToken = UUID()
        seekGeneration = seekToken
        pendingSeek = (destination, destinationOffset)
        message = "正在定位…"
        publishNowPlaying()
        player.seek(to: CMTime(seconds: destination, preferredTimescale: 600), toleranceBefore: .zero, toleranceAfter: .zero) { [weak self] finished in
            Task { @MainActor [weak self] in
                guard let self, self.generation == token, self.seekGeneration == seekToken else { completion?(false); return }
                self.pendingSeek = nil
                guard self.seekCompletionResult(finished) else {
                    self.wantsPlayback = false
                    self.invalidateActivation()
                    self.player.pause()
                    self.refreshTransport()
                    if self.publishedLanguageTransfer != nil {
                        // The replacement locale has not reached the requested
                        // position. Keep the timeline visible, block playback,
                        // and retain it for an explicit reload/retry.
                        self.publishedLanguageTransfer?.autoplay = false
                        self.publishedPositionRestoreFailed = true
                        self.isReady = false
                        self.message = "收听位置恢复失败，已保留原进度，请重试。"
                    } else {
                        self.message = "定位未完成，已保留上次确认的位置。"
                    }
                    self.updateRemoteAvailability()
                    self.publishNowPlaying()
                    completion?(false)
                    return
                }
                self.publishedPositionRestoreFailed = false
                self.publishedLanguageTransfer = nil
                self.resumePosition = nil
                self.positionTouched = true
                self.position = self.currentPosition()
                self.offset = destinationOffset
                self.saveProgress()
                self.publishNowPlaying()
                if self.wantsPlayback { self.startPlayback() }
                else { self.message = completionMessage ?? "已定位 \(PlaybackTime.format(self.position))" }
                completion?(true)
            }
        }
    }

    func saveProgress() {
        guard positionTouched, pendingSeek == nil, let identity, duration > 0 else { return }
        history.record(identity: identity, sourceID: sourceID, position: currentPosition(), offset: offset, duration: duration)
        do {
            try FileManager.default.createDirectory(at: historyURL.deletingLastPathComponent(), withIntermediateDirectories: true)
            try history.encoded().write(to: historyURL, options: .atomic)
            storageWarning = nil
            lastSave = Date()
        } catch {
            storageWarning = "本次位置暂时无法保存，关闭 App 后可能需要重新定位。"
        }
    }

    private func currentPosition() -> Double {
        let seconds = player.currentTime().seconds
        return seconds.isFinite ? min(duration, max(0, seconds)) : position
    }

    private func tick() {
        guard identity != nil || isPreview else { return }
        guard pendingSeek == nil, publishedLanguageTransfer == nil else { return }
        position = currentPosition()
        sampleStatistics()
        statisticsInterfaceVisit()
        publishLiveActivity()
        if positionTouched, Date().timeIntervalSince(lastSave) >= 4 { saveProgress() }
    }

    private func refreshTransport() {
        sampleStatistics()
        isPlaying = player.timeControlStatus == .playing
        isWaiting = activationTask != nil || player.timeControlStatus == .waitingToPlayAtSpecifiedRate
        if isPlaying { message = "正在收听" }
        else if activationTask != nil { message = "正在启用音频…" }
        else if isWaiting { message = "正在缓冲音频…" }
        publishNowPlaying()
    }

    private func observeNotifications() {
        notifications.append(NotificationCenter.default.addObserver(
            forName: AVPlayerItem.didPlayToEndTimeNotification, object: nil, queue: .main
        ) { [weak self] note in
            Task { @MainActor [weak self] in
                guard let self, let item = note.object as? AVPlayerItem, item === self.player.currentItem else { return }
                self.wantsPlayback = false
                self.invalidateActivation()
                self.position = self.duration
                self.message = "已收听完毕"
                self.saveProgress()
                self.refreshTransport()
            }
        })
        notifications.append(NotificationCenter.default.addObserver(
            forName: AVPlayerItem.failedToPlayToEndTimeNotification, object: nil, queue: .main
        ) { [weak self] note in
            Task { @MainActor [weak self] in
                guard let self, let item = note.object as? AVPlayerItem, item === self.player.currentItem else { return }
                self.pause()
                self.message = "播放中断，位置已保留。请检查网络或使用已下载版本。"
            }
        })
        #if os(iOS)
        notifications.append(NotificationCenter.default.addObserver(
            forName: AVAudioSession.interruptionNotification, object: nil, queue: .main
        ) { [weak self] note in
            let type = note.userInfo?[AVAudioSessionInterruptionTypeKey] as? UInt
            let options = note.userInfo?[AVAudioSessionInterruptionOptionKey] as? UInt ?? 0
            Task { @MainActor [weak self] in self?.handleInterruption(type: type, options: options) }
        })
        notifications.append(NotificationCenter.default.addObserver(
            forName: AVAudioSession.routeChangeNotification, object: nil, queue: .main
        ) { [weak self] note in
            let reason = note.userInfo?[AVAudioSessionRouteChangeReasonKey] as? UInt
            Task { @MainActor [weak self] in
                guard let self, reason == AVAudioSession.RouteChangeReason.oldDeviceUnavailable.rawValue else { return }
                self.pause()
                self.message = "耳机已断开，播放已暂停。"
            }
        })
        notifications.append(NotificationCenter.default.addObserver(
            forName: AVAudioSession.mediaServicesWereResetNotification, object: nil, queue: .main
        ) { [weak self] _ in
            Task { @MainActor [weak self] in
                self?.recoverMediaServices()
            }
        })
        #endif
    }

    #if os(iOS)
    private func handleInterruption(type: UInt?, options: UInt) {
        guard let type, let kind = AVAudioSession.InterruptionType(rawValue: type) else { return }
        switch kind {
        case .began:
            publishedLanguageTransfer?.autoplay = false
            manualInteraction()
            interruptedIntent = wantsPlayback || isPlaying
            interruptedGeneration = generation
            wantsPlayback = false
            invalidateActivation()
            player.pause()
            saveProgress()
            message = "音频被系统中断，位置已保存。"
        case .ended:
            let resume = interruptedIntent && interruptedGeneration == generation
                && AVAudioSession.InterruptionOptions(rawValue: options).contains(.shouldResume)
            interruptedIntent = false
            interruptedGeneration = nil
            if resume { wantsPlayback = true; startPlayback() }
            else {
                wantsPlayback = false
                invalidateActivation()
                message = "中断已结束，可继续收听并手动对齐。"
            }
        @unknown default: break
        }
    }
    #endif

    private func recreatePlayer() {
        player.pause()
        if let timeObserver { player.removeTimeObserver(timeObserver) }
        timeObserver = nil
        stateObservation = nil
        itemObservation = nil
        player = AVPlayer()
        observePlayer()
    }

    private func recoverMediaServices() {
        publishedLanguageTransfer?.autoplay = false
        manualInteraction()
        let source = loadedSource
        saveProgress()
        wantsPlayback = false
        interruptedIntent = false
        invalidateActivation()
        generation = UUID()
        seekGeneration = UUID()
        identity = nil
        pendingSeek = nil
        recreatePlayer()
        switch source {
        case .some(.legacy(let week, let track, let url)): load(week: week, track: track, url: url)
        case .some(.published(let audio)): loadPublishedAudio(audio)
        case nil: break
        }
        message = "音频服务已恢复，请点击播放继续并手动对齐。"
    }

    enum RemoteAction { case play, pause, toggle, backward, forward, seek(Double) }

    /// Synchronous command acceptance runs on the same actor as AVPlayer intent.
    /// Queueing a Task and reporting success first allowed rapid commands to race.
    @discardableResult
    func handleRemoteCommand(_ action: RemoteAction) -> MPRemoteCommandHandlerStatus {
        guard isReady, player.currentItem != nil else { return .noSuchContent }
        switch action {
        case .play:
            guard !isVideoPresented else { return .commandFailed }
            play()
        case .pause: pause()
        case .toggle:
            guard !isVideoPresented else { return .commandFailed }
            toggle()
        case .backward: nudge(-1)
        case .forward: nudge(1)
        case .seek(let seconds):
            guard seconds.isFinite, seconds >= 0, seconds <= duration else { return .commandFailed }
            jump(to: seconds)
        }
        publishNowPlaying()
        return .success
    }

    private func configureRemoteCommands() {
        let commands = MPRemoteCommandCenter.shared()
        func bind(_ command: MPRemoteCommand, _ action: RemoteAction) {
            let token = command.addTarget { [weak self] _ in
                Self.onPlaybackActor { self?.handleRemoteCommand(action) ?? .commandFailed }
            }
            remoteTargets.append((command, token))
        }
        bind(commands.playCommand, .play)
        bind(commands.pauseCommand, .pause)
        bind(commands.togglePlayPauseCommand, .toggle)
        commands.skipBackwardCommand.preferredIntervals = [1]
        commands.skipForwardCommand.preferredIntervals = [1]
        bind(commands.skipBackwardCommand, .backward)
        bind(commands.skipForwardCommand, .forward)
        let positionTarget = commands.changePlaybackPositionCommand.addTarget { [weak self] event in
            guard let event = event as? MPChangePlaybackPositionCommandEvent else { return .commandFailed }
            let seconds = event.positionTime
            return Self.onPlaybackActor { self?.handleRemoteCommand(.seek(seconds)) ?? .commandFailed }
        }
        remoteTargets.append((commands.changePlaybackPositionCommand, positionTarget))
        commands.nextTrackCommand.isEnabled = false
        commands.previousTrackCommand.isEnabled = false
        updateRemoteAvailability()
    }

    nonisolated private static func onPlaybackActor(_ action: @MainActor () -> MPRemoteCommandHandlerStatus) -> MPRemoteCommandHandlerStatus {
        if Thread.isMainThread { return MainActor.assumeIsolated { action() } }
        return DispatchQueue.main.sync { MainActor.assumeIsolated { action() } }
    }

    private func updateRemoteAvailability() {
        remoteTargets.forEach { $0.0.isEnabled = isReady }
    }

    func refreshLiveActivityPresentation() { publishLiveActivity() }

    private func publishLiveActivity() {
        guard let identity, isReady else { liveActivity.end(); return }
        liveActivity.update(title: title, speaker: speaker, position: position, duration: duration,
                            isPlaying: isPlaying && pendingSeek == nil, sourceKey: identity.key + "|" + sourceID,
                            languageCode: AppLocalization.shared.language.rawValue, isWaiting: isWaiting || pendingSeek != nil,
                            alignmentPhase: alignmentPhase, alignmentSessionID: alignmentSessionID,
                            subtitleID: currentSystemSubtitle?.id, chineseSubtitle: currentSystemSubtitle?.chinese,
                            englishSubtitle: currentSystemSubtitle?.english)
    }

    private func publishNowPlaying() {
        guard identity != nil || isPreview else { return }
        publishLiveActivity()
        var info: [String: Any] = [
            MPMediaItemPropertyTitle: title,
            MPMediaItemPropertyArtist: speaker,
            MPMediaItemPropertyAlbumTitle: AppLocalization.shared.text("同行 · 证道中文听译"),
            MPMediaItemPropertyPlaybackDuration: duration,
            MPNowPlayingInfoPropertyElapsedPlaybackTime: position,
            MPNowPlayingInfoPropertyPlaybackRate: isPlaying ? 1.0 : 0.0,
        ]
        #if os(iOS)
        if let nowPlayingArtwork { info[MPMediaItemPropertyArtwork] = nowPlayingArtwork }
        #endif
        MPNowPlayingInfoCenter.default().nowPlayingInfo = info
        #if os(macOS)
        MPNowPlayingInfoCenter.default().playbackState = isPlaying ? .playing : .paused
        #endif
    }
}

/// Activation has a separate implementation so delayed system completion can be
/// tested without altering playback behavior or exposing product test switches.
protocol AudioSessionActivating: Sendable {
    func activate() async throws
}

final class SystemAudioSessionActivator: AudioSessionActivating, @unchecked Sendable {
    static let shared = SystemAudioSessionActivator()

    #if os(iOS)
    // All mutable state and potentially blocking AVAudioSession configuration
    // belong to this dedicated serial queue, never the UI or cooperative executor.
    private let queue = DispatchQueue(label: "com.jonathanjing.tongxing.audio-session", qos: .userInitiated)
    private var waiters: [CheckedContinuation<Void, Error>] = []
    private var isActivating = false
    private var recordingOwner: UUID?

    func activate() async throws {
        try Task.checkCancellation()
        try await withCheckedThrowingContinuation { continuation in
            queue.async {
                self.waiters.append(continuation)
                guard !self.isActivating else { return }
                self.isActivating = true
                self.configureAndActivate()
            }
        }
    }

    @MainActor
    func prepareRecording(token: UUID) async throws {
        try Task.checkCancellation()
        queue.async { self.recordingOwner = token }
        // Wait for any earlier async playback activation before changing category.
        try await activate()
        try Task.checkCancellation()
        try await withCheckedThrowingContinuation { (continuation: CheckedContinuation<Void, Error>) in
            queue.async {
                do {
                    guard self.recordingOwner == token else { throw CancellationError() }
                    let session = AVAudioSession.sharedInstance()
                    // The legacy spelling also builds with the older CI SDK;
                    // both names select the same Bluetooth HFP option (0x4).
                    try session.setCategory(.playAndRecord, mode: .measurement, options: [.allowBluetooth, .defaultToSpeaker])
                    try session.setActive(true)
                    continuation.resume()
                } catch { continuation.resume(throwing: error) }
            }
        }
    }

    @MainActor
    func restorePlaybackCategory(token: UUID) {
        queue.async {
            guard self.recordingOwner == token else { return }
            self.recordingOwner = nil
            let session = AVAudioSession.sharedInstance()
            // A manual play request can already have restored the category.
            if session.category != .playback || session.mode != .spokenAudio {
                try? session.setCategory(.playback, mode: .spokenAudio)
            }
        }
    }

    private func configureAndActivate() {
        dispatchPrecondition(condition: .onQueue(queue))
        let session = AVAudioSession.sharedInstance()
        do {
            if session.category != .playback || session.mode != .spokenAudio {
                try session.setCategory(.playback, mode: .spokenAudio)
            }
            // iOS 27 adds official asynchronous activation. The compile-time
            // guard also permits builds using SDKs that predate that declaration.
            // https://developer.apple.com/documentation/avfaudio/avaudiosession/activate(options:completionhandler:)
            #if compiler(>=6.4)
            if #available(iOS 27.0, *) {
                session.activate(options: []) { activated, error in
                    let result: Result<Void, Error> = error.map { .failure($0) }
                        ?? (activated ? .success(()) : .failure(ActivationError.declined))
                    self.queue.async { self.finish(result) }
                }
                return
            }
            #endif
            // setActive is synchronous on iOS 17–26; this dedicated queue keeps
            // its potentially lengthy operation off the main thread.
            try session.setActive(true)
            finish(.success(()))
        } catch { finish(.failure(error)) }
    }

    private func finish(_ result: Result<Void, Error>) {
        dispatchPrecondition(condition: .onQueue(queue))
        let completions = waiters
        waiters.removeAll()
        isActivating = false
        completions.forEach { $0.resume(with: result) }
    }

    private enum ActivationError: Error { case declined }
    #else
    func activate() async throws {}
    #endif
}

/// Only reviewed source mappings enter this timeline; nil means unavailable.
struct PlaybackSystemSubtitle: Equatable {
    let id: String
    let start: Double
    let end: Double
    let chinese: String?
    let english: String?
}
