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
    typealias IndexLoader = (Selection) async throws -> FingerprintIndex
    typealias PublishedIndexLoader = (Selection) async throws -> PublishedFingerprintIndex
    typealias Matcher = @Sendable (CapturedAudio, FingerprintIndex) async throws -> FingerprintMatchResult

    private let playback: any AlignmentPlayback
    private let capture: any MicrophoneCapturing
    private let getSelection: () -> Selection?
    private let loadIndex: IndexLoader
    private let match: Matcher
    private let loadPublishedIndex: PublishedIndexLoader?
    private let onState: (String, Bool, Double?) -> Void
    private let now: () -> ContinuousClock.Instant
    private let deadline: Duration
    private var requestID: UUID?
    private var selectionKey: String?
    private var capability: SermonAudioAlignment?
    private var publishedCapability: PublishedFingerprintBinding?
    private var wasPlaying = false
    private var runningTask: Task<Void, Never>?
    private var timeoutTask: Task<Void, Never>?

    init(playback: any AlignmentPlayback, capture: any MicrophoneCapturing,
         getSelection: @escaping () -> Selection?, loadIndex: @escaping IndexLoader,
         loadPublishedIndex: PublishedIndexLoader? = nil,
         match: @escaping Matcher = { recording, index in
             let work = Task.detached(priority: .userInitiated) {
                 try FingerprintMatcher.match(samples: recording.samples, sampleRate: recording.sampleRate, index: index)
             }
             return try await withTaskCancellationHandler { try await work.value } onCancel: { work.cancel() }
         }, now: @escaping () -> ContinuousClock.Instant = { ContinuousClock.now }, deadline: Duration = .seconds(20),
         onState: @escaping (String, Bool, Double?) -> Void) {
        self.playback = playback; self.capture = capture; self.getSelection = getSelection
        self.loadIndex = loadIndex; self.match = match; self.onState = onState
        self.now = now; self.deadline = deadline
        self.loadPublishedIndex = loadPublishedIndex
    }

    var busy: Bool { requestID != nil }
    var available: Bool {
        guard let selected = getSelection() else { return false }
        if let alignment = selected.track.alignment {
            return (try? alignment.validate(week: selected.week, track: selected.track)) != nil
        }
        guard loadPublishedIndex != nil, let binding = selected.week.audioFingerprint else { return false }
        return (try? binding.validate(week: selected.week, track: selected.track)) != nil
    }

    private func key() -> String? {
        guard let selected = getSelection() else { return nil }
        return [selected.week.id, selected.week.sourceId, selected.week.sourceUrl,
                selected.track.id, selected.track.sha256, playback.alignmentRevision.uuidString].joined(separator: "|")
    }
    private var sourceStillCurrent: Bool {
        selectionKey == key() && capability == getSelection()?.track.alignment
            && publishedCapability == getSelection()?.week.audioFingerprint && available
    }
    private func current(_ token: UUID) -> Bool { requestID == token && sourceStillCurrent && !Task.isCancelled }

    func start() {
        guard !busy else { return }
        guard playback.isReady, available, let selected = getSelection() else {
            onState("当前音频没有可用的听声对齐资料。", false, nil); return
        }
        let token = UUID()
        requestID = token; selectionKey = key(); capability = selected.track.alignment
        publishedCapability = selected.week.audioFingerprint
        wasPlaying = playback.alignmentPlaybackIntent
        playback.pauseForAlignment()
        onState("正在准备听声对齐…", true, nil)
        timeoutTask = Task { [weak self, deadline] in
            do {
                try await Task.sleep(for: deadline)
                guard self?.requestID == token else { return }
                self?.cancel(message: "对齐超时，请保持前台后重试。", resume: true)
            } catch {}
        }
        runningTask = Task { [weak self] in await self?.run(selected, token: token) }
    }

    func cancel(message: String = "已取消对齐。", resume: Bool = false) {
        guard requestID != nil else { return }
        let mayResume = resume && wasPlaying && sourceStillCurrent
        requestID = nil
        runningTask?.cancel(); runningTask = nil
        timeoutTask?.cancel(); timeoutTask = nil
        capture.cancel()
        playback.cancelAlignmentSeek()
        if mayResume { playback.resumeAfterAlignment() }
        onState(message, false, nil)
    }

    private func run(_ selected: Selection, token: UUID) async {
        var resumed = false, mayResume = true
        var status = "听声对齐未完成，请重试或手动调整。"
        var confirmedPosition: Double?
        var capturedStart = now()
        defer {
            if requestID == token {
                let sameSelection = sourceStillCurrent
                requestID = nil; runningTask = nil
                timeoutTask?.cancel(); timeoutTask = nil
                capture.cancel()
                if sameSelection && wasPlaying && !resumed && mayResume { playback.resumeAfterAlignment() }
                onState(status, false, confirmedPosition)
            }
        }
        do {
            let result: FingerprintMatchResult
            if selected.track.alignment == nil, let loadPublishedIndex {
                let index = try await loadPublishedIndex(selected)
                guard current(token) else { return }
                onState("正在听原声，约 10 秒；请保持 App 前台。", true, nil)
                let recording = try await capture.capture(seconds: 10)
                guard current(token) else { return }
                capturedStart = recording.startedAt
                onState("正在本机匹配播放位置…", true, nil)
                let worker = Task.detached(priority: .userInitiated) {
                    try PublishedFingerprintMatcher.match(samples: recording.samples, sampleRate: recording.sampleRate, index: index)
                }
                result = try await withTaskCancellationHandler { try await worker.value } onCancel: { worker.cancel() }
            } else {
                let index = try await loadIndex(selected)
                guard current(token) else { return }
                onState("正在听原声，约 8 秒；请保持 App 前台。", true, nil)
                let recording = try await capture.capture(seconds: 8)
                guard current(token) else { return }
                capturedStart = recording.startedAt
                onState("正在本机匹配播放位置…", true, nil)
                result = try await match(recording, index)
            }
            guard current(token) else { return }
            guard result.matched,
                  let target = AlignmentTarget.position(offset: result.offsetSeconds, startedAt: capturedStart,
                                                        now: now(), duration: selected.track.durationSeconds) else {
                status = "未找到可靠匹配，播放位置未改变。"; return
            }
            let applied = await playback.applyAlignedPosition(target)
            guard current(token) else { return }
            guard applied else { status = "定位未完成，请重试或手动调整。"; return }
            confirmedPosition = target
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
                if let final = AlignmentTarget.position(offset: result.offsetSeconds, startedAt: capturedStart,
                                                       now: now(), duration: selected.track.durationSeconds),
                   abs(final - playback.position) > 0.15 {
                    let corrected = await playback.applyAlignedPosition(final)
                    guard current(token) else { return }
                    if corrected { confirmedPosition = final }
                    else { status = "定位未完成，请重试或手动调整。" }
                }
            }
        } catch is CancellationError {
            status = "已取消对齐。"
        } catch let error as AudioAlignmentError {
            mayResume = error != .interrupted
            status = error.localizedDescription
        } catch {
            status = "无法读取或校验对齐指纹，请联网重试。"
        }
    }
}
