import AVFoundation
import Combine
import Foundation
import MediaPlayer
import TongxingCore

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

    private var player = AVPlayer()
    private let historyURL: URL
    private let audioSessionActivator: any AudioSessionActivating
    private var history = PlaybackHistory()
    private var identity: TrackIdentity?
    private var sourceID = ""
    private var title = ""
    private var speaker = ""
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
    private var loadedSource: (week: SermonWeek, track: SermonTrack, url: URL)?
    private var lastSave = Date.distantPast
    private var timeObserver: Any?
    private var stateObservation: NSKeyValueObservation?
    private var itemObservation: NSKeyValueObservation?
    private var notifications: [NSObjectProtocol] = []
    private var remoteTargets: [(MPRemoteCommand, Any)] = []

    init(historyURL: URL, audioSessionActivator: any AudioSessionActivating = SystemAudioSessionActivator.shared) {
        self.historyURL = historyURL
        self.audioSessionActivator = audioSessionActivator
        if let data = try? Data(contentsOf: historyURL) {
            history = PlaybackHistory(data: data)
        }
        observePlayer()
        observeNotifications()
        configureRemoteCommands()
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
        guard next != identity || sourceID != week.sourceId || loadedSource?.week.sourceUrl != week.sourceUrl else {
            updateMetadata(week: week, track: track)
            return
        }
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
        identity = next
        loadedSource = (week, track, url)
        sourceID = week.sourceId
        title = week.title
        speaker = week.speaker
        position = 0
        duration = track.durationSeconds
        offset = 0
        positionTouched = false
        pendingSeek = nil
        undoSnapshot = nil
        undoPosition = nil
        isReady = false
        isPlaying = false
        isWaiting = false
        message = "正在准备音频…"
        resumePosition = history.resume(identity: next, sourceID: sourceID, duration: duration)
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
                        if !self.positionTouched, let identity = self.identity {
                            self.resumePosition = self.history.resume(identity: identity, sourceID: self.sourceID, duration: measured)
                        }
                    }
                    self.isReady = true
                    self.message = self.resumePosition == nil ? "音频就绪 · 请按现场起点开始" : "已找到上次收听的位置"
                    self.updateRemoteAvailability()
                    self.publishNowPlaying()
                case .failed:
                    self.isReady = false
                    self.wantsPlayback = false
                    self.invalidateActivation()
                    self.message = "音频加载失败，请检查网络或使用已下载版本。"
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

    func clear() {
        saveProgress()
        pause()
        generation = UUID()
        seekGeneration = UUID()
        player.replaceCurrentItem(with: nil)
        itemObservation = nil
        identity = nil
        loadedSource = nil
        pendingSeek = nil
        resumePosition = nil
        undoPosition = nil
        undoSnapshot = nil
        isReady = false
        position = 0
        duration = 0
        offset = 0
        message = "正在准备所选证道…"
        updateRemoteAvailability()
        MPNowPlayingInfoCenter.default().nowPlayingInfo = nil
    }

    func updateMetadata(week: SermonWeek, track: SermonTrack) {
        guard identity == track.identity(weekID: week.id), sourceID == week.sourceId,
              let loadedSource else { return }
        title = week.title
        speaker = week.speaker
        self.loadedSource = (week, track, loadedSource.url)
        publishNowPlaying()
    }

    func toggle() {
        if wantsPlayback || isPlaying || isWaiting { pause() }
        else { play() }
    }

    func play() {
        guard isReady else { return }
        wantsPlayback = true
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
        guard isReady, wantsPlayback, pendingSeek == nil else { return }
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

    func pause() {
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
        guard let saved = resumePosition, isReady else { return }
        if autoplay { wantsPlayback = true }
        seek(to: saved.position, newOffset: saved.offset, rememberUndo: true,
             completionMessage: "已恢复上次位置，现场可能已继续，请手动对齐。")
    }

    func restart() {
        guard isReady else { return }
        seek(to: 0, newOffset: 0, rememberUndo: true,
             completionMessage: "已返回开头 · 请按现场起点开始")
    }

    func nudge(_ amount: Double) {
        guard isReady, amount.isFinite else { return }
        let before = pendingSeek?.position ?? currentPosition()
        let after = max(0, min(duration, before + amount))
        seek(to: after, newOffset: (pendingSeek?.offset ?? offset) + after - before, rememberUndo: true)
    }

    func jump(to value: Double) { seek(to: value, newOffset: pendingSeek?.offset ?? offset, rememberUndo: true) }

    func undo() {
        guard let snapshot = undoSnapshot else { return }
        undoSnapshot = nil
        undoPosition = nil
        seek(to: snapshot.position, newOffset: snapshot.offset, rememberUndo: false,
             completionMessage: "已返回 \(PlaybackTime.format(snapshot.position))")
    }

    private func seek(to value: Double, newOffset: Double, rememberUndo: Bool, completionMessage: String? = nil) {
        guard isReady, value.isFinite, newOffset.isFinite, duration > 0 else { return }
        if rememberUndo {
            undoSnapshot = pendingSeek ?? (currentPosition(), offset)
            undoPosition = undoSnapshot?.position
        }
        let destination = min(max(0, value), duration)
        let destinationOffset = min(duration, max(-duration, newOffset))
        let token = generation
        let seekToken = UUID()
        seekGeneration = seekToken
        pendingSeek = (destination, destinationOffset)
        message = "正在定位…"
        player.seek(to: CMTime(seconds: destination, preferredTimescale: 600), toleranceBefore: .zero, toleranceAfter: .zero) { [weak self] finished in
            Task { @MainActor [weak self] in
                guard let self, self.generation == token, self.seekGeneration == seekToken else { return }
                self.pendingSeek = nil
                guard finished else {
                    self.wantsPlayback = false
                    self.invalidateActivation()
                    self.message = "定位未完成，已保留上次确认的位置。"
                    return
                }
                self.resumePosition = nil
                self.positionTouched = true
                self.position = self.currentPosition()
                self.offset = destinationOffset
                self.saveProgress()
                self.publishNowPlaying()
                if self.wantsPlayback { self.startPlayback() }
                else { self.message = completionMessage ?? "已定位 \(PlaybackTime.format(self.position))" }
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
        guard identity != nil else { return }
        guard pendingSeek == nil else { return }
        position = currentPosition()
        if positionTouched, Date().timeIntervalSince(lastSave) >= 4 { saveProgress() }
    }

    private func refreshTransport() {
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
        if let source { load(week: source.week, track: source.track, url: source.url) }
        message = "音频服务已恢复，请点击播放继续并手动对齐。"
    }

    private func configureRemoteCommands() {
        let commands = MPRemoteCommandCenter.shared()
        func bind(_ command: MPRemoteCommand, _ action: @escaping @MainActor (PlaybackController) -> Void) {
            let token = command.addTarget { [weak self] _ in
                guard let self else { return .commandFailed }
                Task { @MainActor in action(self) }
                return .success
            }
            remoteTargets.append((command, token))
        }
        bind(commands.playCommand) { $0.play() }
        bind(commands.pauseCommand) { $0.pause() }
        bind(commands.togglePlayPauseCommand) { $0.toggle() }
        commands.skipBackwardCommand.preferredIntervals = [1]
        commands.skipForwardCommand.preferredIntervals = [1]
        bind(commands.skipBackwardCommand) { $0.nudge(-1) }
        bind(commands.skipForwardCommand) { $0.nudge(1) }
        let positionTarget = commands.changePlaybackPositionCommand.addTarget { [weak self] event in
            guard let event = event as? MPChangePlaybackPositionCommandEvent, let self else { return .commandFailed }
            let seconds = event.positionTime
            Task { @MainActor in self.jump(to: seconds) }
            return .success
        }
        remoteTargets.append((commands.changePlaybackPositionCommand, positionTarget))
        commands.nextTrackCommand.isEnabled = false
        commands.previousTrackCommand.isEnabled = false
        updateRemoteAvailability()
    }

    private func updateRemoteAvailability() {
        remoteTargets.forEach { $0.0.isEnabled = isReady }
    }

    private func publishNowPlaying() {
        guard identity != nil else { return }
        MPNowPlayingInfoCenter.default().nowPlayingInfo = [
            MPMediaItemPropertyTitle: title,
            MPMediaItemPropertyArtist: speaker,
            MPMediaItemPropertyAlbumTitle: "同行 · 证道中文听译",
            MPMediaItemPropertyPlaybackDuration: duration,
            MPNowPlayingInfoPropertyElapsedPlaybackTime: position,
            MPNowPlayingInfoPropertyPlaybackRate: isPlaying ? 1.0 : 0.0,
        ]
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
