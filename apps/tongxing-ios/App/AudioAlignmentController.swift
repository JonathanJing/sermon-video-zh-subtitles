import Foundation
import TongxingCore
import TongxingInfrastructure

@MainActor
protocol AlignmentPlayback: AnyObject {
    var alignmentRevision: UUID { get }
    var alignmentPlaybackIntent: Bool { get }
    var isReady: Bool { get }
    var isPlaying: Bool { get }
    var isWaiting: Bool { get }
    var position: Double { get }
    var duration: Double { get }
    func pauseForAlignment()
    func resumeAfterAlignment()
    func applyAlignedPosition(_ value: Double) async -> Bool
    func cancelAlignmentSeek()
}
extension PlaybackController: AlignmentPlayback {}

/// Matching and native playback share approved source-clip zero. The fingerprint
/// offset is the query's first sample; advance by elapsed monotonic time once.
enum AlignmentTarget {
    static func position(offset: Double?, startedAt: ContinuousClock.Instant,
                         now: ContinuousClock.Instant, duration: Double) -> Double? {
        let parts = startedAt.duration(to: now).components
        let elapsed = Double(parts.seconds) + Double(parts.attoseconds) / 1e18
        guard let offset, offset.isFinite, elapsed >= 0, elapsed <= 30,
              duration.isFinite, duration > 0 else { return nil }
        let target = offset + elapsed
        return target >= 0 && target < duration ? target : nil
    }
}

/// A finite source-bound transaction. User commands invalidate it before they
/// alter playback; it never infers a new source or accepts a late worker result.
@MainActor
final class AudioAlignmentController {
    struct Selection {
        let week: SermonWeek
        let track: SermonTrack
    }
    struct PublishedSelection {
        let page: MultilingualPage
        let locale: String
        let trackSha256: String
        let durationSeconds: Double
    }
    private enum ActiveSelection {
        case legacy(Selection)
        case published(PublishedSelection)
        var durationSeconds: Double {
            switch self {
            case .legacy(let value): value.track.durationSeconds
            case .published(let value): value.durationSeconds
            }
        }
    }
    /// Index bound to one alignment attempt. Legacy and published indexes use
    /// different quantization and must never be mixed.
    private enum MatchEngine: Sendable {
        case legacy(FingerprintIndex)
        case published(PublishedFingerprintIndex)
    }
    typealias IndexLoader = (Selection) async throws -> FingerprintIndex
    typealias PublishedIndexLoader = (Selection) async throws -> PublishedFingerprintIndex
    typealias PageIndexLoader = (PublishedSelection) async throws -> PublishedFingerprintIndex
    typealias Matcher = @Sendable (CapturedAudio, FingerprintIndex) async throws -> FingerprintMatchResult

    /// FIELD-03: checkpoints within one continuous capture session (seconds).
    /// 7s is the minimum viable query for both matchers; 15s is the single
    /// microphone budget shared with the Web batch's budget.
    private static let checkpoints: [Double] = [7, 10, 12, 15]
    private static let maxCaptureSeconds: Double = 15

    private let playback: any AlignmentPlayback
    private let capture: any MicrophoneCapturing
    private let getSelection: () -> Selection?
    private let getPublishedSelection: (() -> PublishedSelection?)?
    private let loadIndex: IndexLoader
    private let match: Matcher
    private let loadPublishedIndex: PublishedIndexLoader?
    private let loadPageIndex: PageIndexLoader?
    private let onState: (String, Bool, Double?) -> Void
    private let onFailure: (String) -> Void
    private let onPhase: (ListeningAlignmentPhase) -> Void
    private let now: () -> ContinuousClock.Instant
    private let deadline: Duration
    private let matchBudget: Duration
    private var requestID: UUID?
    private var selectionKey: String?
    private var capability: SermonAudioAlignment?
    private var publishedCapability: PublishedFingerprintBinding?
    private var pageCapability: PublishedFingerprintBinding?
    private var wasPlaying = false
    private var runningTask: Task<Void, Never>?
    private var timeoutTask: Task<Void, Never>?

    init(playback: any AlignmentPlayback, capture: any MicrophoneCapturing,
         getSelection: @escaping () -> Selection?, loadIndex: @escaping IndexLoader,
         loadPublishedIndex: PublishedIndexLoader? = nil,
         getPublishedSelection: (() -> PublishedSelection?)? = nil,
         loadPageIndex: PageIndexLoader? = nil,
         match: @escaping Matcher = { recording, index in
             let work = Task.detached(priority: .userInitiated) {
                 try FingerprintMatcher.match(samples: recording.samples, sampleRate: recording.sampleRate, index: index)
             }
             return try await withTaskCancellationHandler { try await work.value } onCancel: { work.cancel() }
         }, now: @escaping () -> ContinuousClock.Instant = { ContinuousClock.now }, deadline: Duration = .seconds(20),
         matchBudget: Duration = .seconds(3),
         onState: @escaping (String, Bool, Double?) -> Void,
         onFailure: @escaping (String) -> Void = { _ in },
         onPhase: @escaping (ListeningAlignmentPhase) -> Void = { _ in }) {
        self.playback = playback; self.capture = capture; self.getSelection = getSelection
        self.loadIndex = loadIndex; self.match = match; self.onState = onState
        self.onFailure = onFailure
        self.onPhase = onPhase
        self.now = now; self.deadline = deadline; self.matchBudget = matchBudget
        self.loadPublishedIndex = loadPublishedIndex
        self.getPublishedSelection = getPublishedSelection
        self.loadPageIndex = loadPageIndex
    }

    private func activeSelection() -> ActiveSelection? {
        if let selected = getSelection() { return .legacy(selected) }
        if let selected = getPublishedSelection?() { return .published(selected) }
        return nil
    }

    var busy: Bool { requestID != nil }
    var available: Bool {
        guard let selected = activeSelection() else { return false }
        switch selected {
        case .legacy(let selected):
            if let alignment = selected.track.alignment {
                return (try? alignment.validate(week: selected.week, track: selected.track)) != nil
            }
            guard loadPublishedIndex != nil, let binding = selected.week.audioFingerprint else { return false }
            return (try? binding.validate(week: selected.week, track: selected.track)) != nil
        case .published(let selected):
            guard loadPageIndex != nil,
                  let binding = selected.page.targets[selected.locale]?.audioFingerprint else { return false }
            return (try? binding.validate(page: selected.page, locale: selected.locale,
                                          trackSha256: selected.trackSha256,
                                          durationSeconds: selected.durationSeconds)) != nil
        }
    }

    private func key() -> String? {
        guard let selected = activeSelection() else { return nil }
        switch selected {
        case .legacy(let selected):
            return [selected.week.id, selected.week.sourceId, selected.week.sourceUrl,
                    selected.track.id, selected.track.sha256, playback.alignmentRevision.uuidString].joined(separator: "|")
        case .published(let selected):
            let binding = selected.page.targets[selected.locale]?.audioFingerprint
            return [selected.page.id, selected.page.sourceIdentitySha256, selected.locale,
                    selected.trackSha256, binding?.indexSha256 ?? "", binding?.sourceSha256 ?? "",
                    playback.alignmentRevision.uuidString].joined(separator: "|")
        }
    }
    private var sourceStillCurrent: Bool {
        selectionKey == key() && capability == getSelection()?.track.alignment
            && publishedCapability == getSelection()?.week.audioFingerprint
            && pageCapability == getPublishedSelection?()?.page.targets[getPublishedSelection?()?.locale ?? ""]?.audioFingerprint
            && available
    }
    private func current(_ token: UUID) -> Bool { requestID == token && sourceStillCurrent && !Task.isCancelled }

    func start() {
        guard !busy else { return }
        guard playback.isReady, available, let selected = activeSelection() else {
            onPhase(.failed)
            onState("当前音频没有可用的听声对齐资料。", false, nil); return
        }
        let token = UUID()
        requestID = token; selectionKey = key()
        switch selected {
        case .legacy(let value):
            capability = value.track.alignment; publishedCapability = value.week.audioFingerprint
            pageCapability = nil
        case .published(let value):
            capability = nil; publishedCapability = nil
            pageCapability = value.page.targets[value.locale]?.audioFingerprint
        }
        wasPlaying = playback.alignmentPlaybackIntent
        playback.pauseForAlignment()
        onPhase(.preparing)
        onState("正在准备听声对齐…", true, nil)
        timeoutTask = Task { [weak self, deadline] in
            do {
                try await Task.sleep(for: deadline)
                guard self?.requestID == token else { return }
                self?.cancel(message: "对齐超时，请保持前台后重试。", resume: true, reportFailure: true)
            } catch {}
        }
        runningTask = Task { [weak self] in await self?.run(selected, token: token) }
    }

    func cancel(message: String = "已取消对齐。", resume: Bool = false, reportFailure: Bool = false) {
        guard requestID != nil else { return }
        let sameSelection = sourceStillCurrent
        let mayResume = resume && wasPlaying && sameSelection
        requestID = nil
        runningTask?.cancel(); runningTask = nil
        timeoutTask?.cancel(); timeoutTask = nil
        capture.cancel()
        capture.onCaptureStarted = nil
        playback.cancelAlignmentSeek()
        if mayResume { playback.resumeAfterAlignment() }
        onPhase(reportFailure ? .failed : .cancelled)
        onState(message, false, nil)
        if reportFailure && sameSelection { onFailure(message) }
    }

    private func loadMatchEngine(_ selected: ActiveSelection) async throws -> MatchEngine {
        if case .published(let page) = selected, let loadPageIndex {
            return .published(try await loadPageIndex(page))
        }
        if case .legacy(let legacy) = selected, legacy.track.alignment == nil, let loadPublishedIndex {
            return .published(try await loadPublishedIndex(legacy))
        }
        guard case .legacy(let legacy) = selected else { throw AudioAlignmentError.unavailable }
        return .legacy(try await loadIndex(legacy))
    }

    /// Runs one checkpoint match with a bounded compute budget so a slow match
    /// cannot consume the microphone budget (FIELD-03). Returns nil on timeout;
    /// the session keeps capturing and the next checkpoint retries.
    private func matchWithBudget(_ prefix: CapturedAudio,
                                 _ matchFn: @Sendable (CapturedAudio) async throws -> FingerprintMatchResult
    ) async throws -> FingerprintMatchResult? {
        let budget = matchBudget
        return try await withThrowingTaskGroup(of: FingerprintMatchResult?.self) { group in
            group.addTask { try await matchFn(prefix) }
            group.addTask {
                try await Task.sleep(for: budget)
                return nil
            }
            guard let first = try await group.next() else { return nil }
            group.cancelAll()
            return first
        }
    }

    private func run(_ selected: ActiveSelection, token: UUID) async {
        var resumed = false, mayResume = true
        var status = "听声对齐未完成，请重试或手动调整。"
        var confirmedPosition: Double?
        var failed = true
        var unmatched = false
        var capturedStart = now()
        defer {
            if requestID == token {
                let sameSelection = sourceStillCurrent
                requestID = nil; runningTask = nil
                timeoutTask?.cancel(); timeoutTask = nil
                capture.cancel()
                capture.onCaptureStarted = nil
                if sameSelection && wasPlaying && !resumed && mayResume { playback.resumeAfterAlignment() }
                onPhase(unmatched ? .unmatched : failed ? .failed : confirmedPosition != nil ? .aligned : .cancelled)
                onState(status, false, confirmedPosition)
                if failed && sameSelection { onFailure(status) }
            }
        }
        do {
            let engine = try await loadMatchEngine(selected)
            guard current(token) else { return }
            // Bind the loaded index to a Sendable prefix matcher. The legacy
            // branch keeps the injected `match` closure so tests can stub it.
            let matchFn: @Sendable (CapturedAudio) async throws -> FingerprintMatchResult
            switch engine {
            case .legacy(let index):
                let injected = match
                matchFn = { prefix in try await injected(prefix, index) }
            case .published(let index):
                matchFn = { prefix in
                    let worker = Task.detached(priority: .userInitiated) {
                        try PublishedFingerprintMatcher.match(samples: prefix.samples, sampleRate: prefix.sampleRate, index: index)
                    }
                    return try await withTaskCancellationHandler { try await worker.value } onCancel: { worker.cancel() }
                }
            }
            capture.onCaptureStarted = { [weak self] in
                guard let self, self.current(token) else { return }
                self.onPhase(.listening)
                self.onState("正在听原声，请保持 App 前台。", true, nil)
            }
            // FIELD-03: one continuous session; checkpoints share the same PCM.
            // A reliable hit at any checkpoint stops the mic early; otherwise
            // the session continues to the next checkpoint within the budget.
            let session = try await capture.beginContinuousCapture(maxSeconds: Self.maxCaptureSeconds)
            var hit: (result: FingerprintMatchResult, prefix: CapturedAudio)?
            for (i, checkpoint) in Self.checkpoints.enumerated() {
                try await session.waitUntil(seconds: checkpoint)
                guard current(token) else { return }
                guard let prefix = session.snapshot() else { break }
                onPhase(.matching)
                onState("正在本机匹配播放位置…", true, nil)
                let attempt = try await matchWithBudget(prefix, matchFn)
                guard current(token) else { return }
                if let attempt, attempt.matched {
                    hit = (attempt, prefix)
                    break // early stop: same thresholds as before (FIELD-07)
                }
                if i < Self.checkpoints.count - 1 {
                    onPhase(.listening)
                    onState("已采集约\(Int(checkpoint))秒，证据不足，继续听取…", true, nil)
                }
            }
            // The microphone is no longer needed once the checkpoint loop ends.
            session.cancel()
            guard current(token) else { return }
            guard let hit else {
                unmatched = true
                status = "未找到可靠匹配，播放位置未改变。"
                return
            }
            capturedStart = hit.prefix.startedAt
            guard let target = AlignmentTarget.position(offset: hit.result.offsetSeconds, startedAt: capturedStart,
                                                        now: now(), duration: selected.durationSeconds) else {
                status = "未找到可靠匹配，播放位置未改变。"
                return
            }
            let applied = await playback.applyAlignedPosition(target)
            guard current(token) else { return }
            guard applied else { status = "定位未完成，请重试或手动调整。"; return }
            confirmedPosition = target
            failed = false
            status = "已对齐至 {time}。"
            if wasPlaying {
                resumed = true
                playback.resumeAfterAlignment()
                // Retain task ownership while AVPlayer activates/buffers, so a
                // manual command or the deadline still defeats late correction.
                while current(token) && !playback.isPlaying {
                    if !playback.isWaiting && !playback.alignmentPlaybackIntent {
                        status = "已定位，请点播放继续收听。"; return
                    }
                    try await Task.sleep(for: .milliseconds(50))
                }
                guard current(token) else { return }
                if let final = AlignmentTarget.position(offset: hit.result.offsetSeconds, startedAt: capturedStart,
                                                       now: now(), duration: selected.durationSeconds),
                   abs(final - playback.position) > 0.15 {
                    let corrected = await playback.applyAlignedPosition(final)
                    guard current(token) else { return }
                    if corrected { confirmedPosition = final }
                    else { failed = true; status = "定位未完成，请重试或手动调整。" }
                }
            }
        } catch is CancellationError {
            failed = false
            status = "已取消对齐。"
        } catch let error as AudioAlignmentError {
            mayResume = error != .interrupted
            status = error.localizedDescription
        } catch {
            status = "无法读取或校验对齐指纹，请联网重试。"
        }
    }
}
