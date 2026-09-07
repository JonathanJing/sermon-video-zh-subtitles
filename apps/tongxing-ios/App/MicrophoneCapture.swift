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
    func cancel()
}

/// One finite, in-memory capture. This object never writes audio to disk or network.
@MainActor
final class MicrophoneCapture: MicrophoneCapturing {
    #if os(iOS)
    private var engine: AVAudioEngine?
    private var continuation: CheckedContinuation<CapturedAudio, Error>?
    private var requestID: UUID?
    private var observers: [NSObjectProtocol] = []
    private var hasTap = false

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

    func cancel() {
        guard let token = requestID else { return }
        finish(.failure(CancellationError()), token: token)
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
    func cancel() {}
    #endif
}

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
}
#endif
