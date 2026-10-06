import AVFoundation
import Foundation

struct CapturedAudio: Sendable {
    let samples: [Float]
    let sampleRate: Double
    /// A monotonic timestamp for the beginning of the first collected buffer.
    let startedAt: ContinuousClock.Instant
}

enum AudioAlignmentError: Error, LocalizedError, Equatable {
    case permissionDenied, unavailable, interrupted, invalidCapture
    var errorDescription: String? {
        switch self {
        case .permissionDenied: return "麦克风权限未获允许，请在系统设置中检查权限。"
        case .unavailable: return "当前设备无法进行听声对齐。"
        case .interrupted: return "听声被系统中断，请重试。"
        case .invalidCapture: return "未能取得有效声音，请重试。"
        }
    }
}

@MainActor
protocol MicrophoneCapturing: AnyObject {
    func capture(seconds: Double) async throws -> CapturedAudio
    /// Starts one continuous capture session for checkpointed alignment (FIELD-03).
    /// The engine runs once; the caller observes prefix snapshots at checkpoints
    /// and the session ends at maxSeconds, on cancel(), or on interruption.
    /// Throws like capture(seconds:) on permission denial or setup failure.
    func beginContinuousCapture(maxSeconds: Double) async throws -> any ContinuousCaptureSessionProtocol
    func cancel()
}

/// One continuous microphone session (FIELD-03): the engine starts once and the
/// caller polls waitUntil/snapshot for prefixes. Never writes audio to disk or
/// network; PCM stays in memory until the session ends. Callers must call
/// cancel() (or let the session finish) to release the microphone.
@MainActor
protocol ContinuousCaptureSessionProtocol: AnyObject {
    /// Seconds accumulated so far (0 before the first buffer).
    var accumulatedSeconds: Double { get }
    /// True after the session reached maxSeconds or terminally failed.
    var isFinished: Bool { get }
    /// Suspends until at least `seconds` have accumulated or the session ends.
    /// Throws the session's terminal error (e.g. interrupted), or CancellationError.
    func waitUntil(seconds: Double) async throws
    /// Current prefix snapshot, or nil before the first buffer. Snapshots share
    /// the session's first-sample monotonic clock, so elapsed compensation is
    /// applied exactly once downstream (FIELD-05).
    func snapshot() -> CapturedAudio?
    /// Stops the engine and releases the microphone. Idempotent.
    func cancel()
    var onCaptureStarted: (() -> Void)? { get set }
}

extension MicrophoneCapturing {
    var onCaptureStarted: (() -> Void)? {
        get { nil }
        set {}
    }
}

/// One finite, in-memory capture. This object never writes audio to disk or network.
@MainActor
final class MicrophoneCapture: MicrophoneCapturing {
    var onCaptureStarted: (() -> Void)?
    #if os(iOS)
    private var engine: AVAudioEngine?
    private var continuation: CheckedContinuation<CapturedAudio, Error>?
    private var requestID: UUID?
    private var observers: [NSObjectProtocol] = []
    private var hasTap = false
    private var activeStream: ContinuousCaptureSession?

    func capture(seconds: Double = 8) async throws -> CapturedAudio {
        guard seconds >= 7, seconds <= 12, requestID == nil else { throw AudioAlignmentError.invalidCapture }
        let token = UUID()
        requestID = token
        do {
            let allowed = await withCheckedContinuation { continuation in
                AVAudioApplication.requestRecordPermission { continuation.resume(returning: $0) }
            }
            try Task.checkCancellation()
            guard requestID == token else { throw CancellationError() }
            guard allowed else { throw AudioAlignmentError.permissionDenied }
            try await SystemAudioSessionActivator.shared.prepareRecording(token: token)
            try Task.checkCancellation()
            guard requestID == token else { throw CancellationError() }
            return try await withTaskCancellationHandler {
                try await withCheckedThrowingContinuation { continuation in
                    self.continuation = continuation
                    do {
                        let engine = AVAudioEngine()
                        self.engine = engine
                        let input = engine.inputNode
                        let format = input.outputFormat(forBus: 0)
                        guard format.sampleRate >= 8000, format.sampleRate <= 192000,
                              format.channelCount > 0, format.commonFormat == .pcmFormatFloat32
                        else { throw AudioAlignmentError.invalidCapture }
                        let accumulator = CaptureAccumulator(sampleRate: format.sampleRate, seconds: seconds)
                        input.installTap(onBus: 0, bufferSize: 1024, format: format) { [weak self] buffer, _ in
                            guard let result = accumulator.append(buffer) else { return }
                            Task { @MainActor [weak self] in self?.finish(result, token: token) }
                        }
                        hasTap = true
                        let center = NotificationCenter.default
                        for name in [AVAudioSession.interruptionNotification,
                                     AVAudioSession.mediaServicesWereResetNotification,
                                     NSNotification.Name.AVAudioEngineConfigurationChange] {
                            observers.append(center.addObserver(forName: name, object: nil, queue: .main) { [weak self] _ in
                                Task { @MainActor [weak self] in self?.finish(.failure(AudioAlignmentError.interrupted), token: token) }
                            })
                        }
                        engine.prepare()
                        try engine.start()
                        onCaptureStarted?()
                        if Task.isCancelled { finish(.failure(CancellationError()), token: token) }
                    } catch { finish(.failure(error), token: token) }
                }
            } onCancel: {
                Task { @MainActor [weak self] in
                    guard self?.requestID == token else { return }
                    self?.cancel()
                }
            }
        } catch {
            if requestID == token { finish(.failure(error), token: token) }
            throw error
        }
    }

    /// FIELD-03: one continuous session for checkpointed early-stop alignment.
    /// Single mic budget: at most 15 seconds per session (shared with the Web
    /// batch's budget); the caller's checkpoint loop decides when to stop early.
    func beginContinuousCapture(maxSeconds: Double = 15) async throws -> any ContinuousCaptureSessionProtocol {
        guard maxSeconds >= 7, maxSeconds <= 15, requestID == nil, activeStream == nil else {
            throw AudioAlignmentError.invalidCapture
        }
        let token = UUID()
        requestID = token
        do {
            let allowed = await withCheckedContinuation { continuation in
                AVAudioApplication.requestRecordPermission { continuation.resume(returning: $0) }
            }
            try Task.checkCancellation()
            guard requestID == token else { throw CancellationError() }
            guard allowed else { throw AudioAlignmentError.permissionDenied }
            try await SystemAudioSessionActivator.shared.prepareRecording(token: token)
            try Task.checkCancellation()
            guard requestID == token else { throw CancellationError() }
            let session = ContinuousCaptureSession(owner: self, token: token)
            try session.startEngine(maxSeconds: maxSeconds)
            try Task.checkCancellation()
            guard requestID == token else {
                session.cancel()
                throw CancellationError()
            }
            activeStream = session
            return session
        } catch {
            if requestID == token { requestID = nil }
            throw error
        }
    }

    func cancel() {
        if let stream = activeStream {
            stream.cancel()
            return
        }
        guard let token = requestID else { return }
        finish(.failure(CancellationError()), token: token)
    }

    fileprivate func streamingDidFinish(_ session: ContinuousCaptureSession) {
        if activeStream === session { activeStream = nil }
        requestID = nil
    }

    private func finish(_ result: Result<CapturedAudio, Error>, token: UUID) {
        guard requestID == token else { return }
        requestID = nil
        engine?.stop()
        if hasTap { engine?.inputNode.removeTap(onBus: 0) }
        hasTap = false
        engine = nil
        observers.forEach(NotificationCenter.default.removeObserver)
        observers.removeAll()
        let waiting = continuation
        continuation = nil
        // Restore the playback category on the same serialized session queue.
        // Engine input is already stopped even if the system call is delayed.
        SystemAudioSessionActivator.shared.restorePlaybackCategory(token: token)
        waiting?.resume(with: result)
    }
    #else
    func capture(seconds: Double = 8) async throws -> CapturedAudio { throw AudioAlignmentError.unavailable }
    func beginContinuousCapture(maxSeconds: Double = 15) async throws -> any ContinuousCaptureSessionProtocol {
        throw AudioAlignmentError.unavailable
    }
    func cancel() {}
    #endif
}

#if os(iOS)
/// Concrete continuous session behind ContinuousCaptureSessionProtocol.
/// The engine starts once; prefixes are observed via snapshot(). Created by
/// MicrophoneCapture only.
@MainActor
final class ContinuousCaptureSession: ContinuousCaptureSessionProtocol {
    private weak var owner: MicrophoneCapture?
    private let token: UUID
    private var engine: AVAudioEngine?
    private var accumulator: CaptureAccumulator?
    private var observers: [NSObjectProtocol] = []
    private var hasTap = false
    private var terminalError: Error?
    private var finished = false

    fileprivate init(owner: MicrophoneCapture, token: UUID) {
        self.owner = owner
        self.token = token
    }

    var accumulatedSeconds: Double { accumulator?.accumulatedSeconds ?? 0 }
    var isFinished: Bool { finished || terminalError != nil }

    func waitUntil(seconds: Double) async throws {
        while true {
            try Task.checkCancellation()
            if let terminalError { throw terminalError }
            if finished || accumulatedSeconds >= seconds { return }
            try await Task.sleep(for: .milliseconds(100))
        }
    }

    func snapshot() -> CapturedAudio? { accumulator?.snapshot() }

    func cancel() { finish(.failure(CancellationError())) }

    fileprivate func startEngine(maxSeconds: Double) throws {
        let engine = AVAudioEngine()
        self.engine = engine
        let input = engine.inputNode
        let format = input.outputFormat(forBus: 0)
        guard format.sampleRate >= 8000, format.sampleRate <= 192000,
              format.channelCount > 0, format.commonFormat == .pcmFormatFloat32
        else { throw AudioAlignmentError.invalidCapture }
        let accumulator = CaptureAccumulator(sampleRate: format.sampleRate, seconds: maxSeconds)
        self.accumulator = accumulator
        input.installTap(onBus: 0, bufferSize: 1024, format: format) { [weak self] buffer, _ in
            // Real-time thread: only copy PCM here. Terminal events hop to MainActor.
            guard let result = accumulator.append(buffer) else { return }
            Task { @MainActor [weak self] in self?.finish(result) }
        }
        hasTap = true
        let center = NotificationCenter.default
        for name in [AVAudioSession.interruptionNotification,
                     AVAudioSession.mediaServicesWereResetNotification,
                     NSNotification.Name.AVAudioEngineConfigurationChange] {
            observers.append(center.addObserver(forName: name, object: nil, queue: .main) { [weak self] _ in
                Task { @MainActor [weak self] in self?.finish(.failure(AudioAlignmentError.interrupted)) }
            })
        }
        engine.prepare()
        try engine.start()
    }

    private func finish(_ result: Result<CapturedAudio, Error>) {
        guard !finished, terminalError == nil else { return }
        switch result {
        case .success: finished = true
        case .failure(let error): terminalError = error
        }
        teardown()
        owner?.streamingDidFinish(self)
    }

    private func teardown() {
        engine?.stop()
        if hasTap { engine?.inputNode.removeTap(onBus: 0) }
        hasTap = false
        engine = nil
        // Keep the accumulator: snapshot() must still serve the final prefix.
        observers.forEach(NotificationCenter.default.removeObserver)
        observers.removeAll()
        SystemAudioSessionActivator.shared.restorePlaybackCategory(token: token)
    }
}
#endif

#if os(iOS)
/// Only this small accumulator is shared with the audio render callback. The lock
/// protects completion and bounds; no actor hops or file I/O occur while copying PCM.
private final class CaptureAccumulator: @unchecked Sendable {
    private let lock = NSLock()
    private let sampleRate: Double
    private let maximumFrames: Int
    private var samples: [Float] = []
    private var startedAt: ContinuousClock.Instant?
    private var finished = false

    init(sampleRate: Double, seconds: Double) {
        self.sampleRate = sampleRate
        maximumFrames = Int((sampleRate * seconds).rounded())
        samples.reserveCapacity(maximumFrames)
    }

    func append(_ buffer: AVAudioPCMBuffer) -> Result<CapturedAudio, Error>? {
        lock.lock(); defer { lock.unlock() }
        guard !finished else { return nil }
        guard buffer.format.sampleRate == sampleRate, let channels = buffer.floatChannelData,
              buffer.format.channelCount > 0, buffer.frameLength > 0 else {
            finished = true
            return .failure(AudioAlignmentError.invalidCapture)
        }
        let count = min(Int(buffer.frameLength), maximumFrames - samples.count)
        if startedAt == nil {
            // The tap delivers a completed buffer. Remove its duration from the
            // callback time; physical input latency remains a device acceptance item.
            startedAt = ContinuousClock.now.advanced(by: .seconds(-Double(buffer.frameLength) / sampleRate))
        }
        for frame in 0..<count {
            var value: Float = 0
            for channel in 0..<Int(buffer.format.channelCount) { value += channels[channel][frame * buffer.stride] }
            value /= Float(buffer.format.channelCount)
            guard value.isFinite else { finished = true; return .failure(AudioAlignmentError.invalidCapture) }
            samples.append(value)
        }
        guard samples.count == maximumFrames, let startedAt else { return nil }
        finished = true
        return .success(CapturedAudio(samples: samples, sampleRate: sampleRate, startedAt: startedAt))
    }

    /// Seconds accumulated so far. Lock-protected; safe to poll from any thread.
    var accumulatedSeconds: Double {
        lock.lock(); defer { lock.unlock() }
        return Double(samples.count) / sampleRate
    }

    /// Prefix snapshot for checkpointed matching (FIELD-03). Shares the session's
    /// first-sample clock and does not end the capture. Returns nil before the
    /// first buffer.
    func snapshot() -> CapturedAudio? {
        lock.lock(); defer { lock.unlock() }
        guard let startedAt, !samples.isEmpty else { return nil }
        return CapturedAudio(samples: samples, sampleRate: sampleRate, startedAt: startedAt)
    }
}
#endif
