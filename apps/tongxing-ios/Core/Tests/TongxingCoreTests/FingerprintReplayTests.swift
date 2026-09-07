import CryptoKit
import Foundation
import Testing
@testable import TongxingCore

/// Optional, explicitly selected offline recording replay. Inputs stay outside
/// the package/Git. This does not establish acoustic or real-venue readiness.
struct FingerprintReplayTests {
    private struct CaseResult: Encodable {
        let mode: String
        let positive: Bool
        let expectedOffset: Double?
        let sampleRate: Double
        let milliseconds: Double
        let result: FingerprintMatchResult
        let errorSeconds: Double?
    }
    private struct Report: Encodable {
        let kind = "swift-offline-file-replay-not-acoustic-or-venue-proof"
        let referencePcmSha256: String
        let referenceDurationSeconds: Double
        let positives: Int
        let acceptedCorrect: Int
        let negatives: Int
        let falseAccepts: Int
        let maxErrorSeconds: Double
        let p95Milliseconds: Double
        let results: [CaseResult]
    }

    private func pcm(_ url: URL) throws -> [Float] {
        let bytes = try Data(contentsOf: url)
        guard bytes.count % 4 == 0 else { throw FingerprintError.invalidAudio("PCM字节不完整") }
        return bytes.withUnsafeBytes { buffer in
            (0..<(bytes.count / 4)).map { index in
                Float(bitPattern: UInt32(littleEndian: buffer.loadUnaligned(fromByteOffset: index * 4, as: UInt32.self)))
            }
        }
    }

    @Test(.enabled(if: ProcessInfo.processInfo.environment["TONGXING_FINGERPRINT_REFERENCE_ROOT"] != nil))
    func realTwoWeekReferencesAndNegativeRecordings() throws {
        let environment = ProcessInfo.processInfo.environment
        let root = URL(fileURLWithPath: try #require(environment["TONGXING_FINGERPRINT_REFERENCE_ROOT"]))
        let referenceURL = root.appendingPathComponent("reference-20260906.f32")
        let reference = try pcm(referenceURL), other = try pcm(root.appendingPathComponent("reference-20260830.f32"))
        let sameSpeaker = try pcm(root.appendingPathComponent("negative-jared-reference.f32"))
        let index = try FingerprintIndex.decode(Data(contentsOf: root.appendingPathComponent("alignment-index/l8ucqF9uA9A-fingerprint.json")))
        let otherIndex = try FingerprintIndex.decode(Data(contentsOf: root.appendingPathComponent("alignment-index/-BeFX5G2oAw-fingerprint.json")))
        let offsets = [0.0, 4.123, 32.879, 99.371, 206.135, 450.77, 701.913, 990.001, 1345.683, 1645.723, 1900.117, 1959.0]
        var random = FingerprintTestAudio.Random(seed: 734829), results: [CaseResult] = []
        func check(_ sample: [Float], offset: Double?, mode: String, rate: Double = 8000,
                   referenceIndex: FingerprintIndex? = nil, consistent: Bool = true) throws {
            let start = ProcessInfo.processInfo.systemUptime
            let selected = referenceIndex ?? index
            let result = try consistent ? FingerprintMatcher.match(samples: sample, sampleRate: rate, index: selected)
                : FingerprintMatcher.matchWindow(samples: sample, sampleRate: rate, index: selected)
            let elapsed = (ProcessInfo.processInfo.systemUptime - start) * 1000
            let error = offset.flatMap { expected in result.offsetSeconds.map { $0 - expected } }
            results.append(CaseResult(mode: mode, positive: offset != nil, expectedOffset: offset,
                sampleRate: rate, milliseconds: elapsed, result: result, errorSeconds: error))
        }
        for snr in [nil, 10.0, 0.0] as [Double?] {
            for offset in offsets {
                var sample = FingerprintTestAudio.slice(reference, at: offset)
                if let snr {
                    let energy = sample.reduce(0.0) { $0 + Double($1) * Double($1) }
                    let amplitude = sqrt(energy / Double(sample.count)) * sqrt(3) * pow(10, -snr / 20)
                    for i in sample.indices { sample[i] = Float(0.2 * (Double(sample[i]) + (random.next() * 2 - 1) * amplitude)) }
                }
                try check(sample, offset: offset, mode: snr.map { "white-noise-\(Int($0))dB-gain-0.2" } ?? "clean")
                if snr == nil { try check(Array(sample.prefix(40000)), offset: offset, mode: "clean-five-seconds", consistent: false) }
            }
        }
        for i in 0..<50 {
            let offset = (Double(other.count) / 8000 - 8) * random.next()
            let sample = FingerprintTestAudio.slice(other, at: offset)
            try check(sample, offset: nil, mode: "different-sermon-eric")
            if i < 12 { try check(sample, offset: offset, mode: "20260830-positive", referenceIndex: otherIndex) }
        }
        for offset in [0.0, 1.231, 3.8] {
            try check(FingerprintTestAudio.slice(sameSpeaker, at: offset), offset: nil, mode: "same-speaker-different-sermon-jared")
        }
        for _ in 0..<25 {
            let noise = (0..<64000).map { _ in Float(0.2 * (random.next() * 2 - 1)) }
            try check(noise, offset: nil, mode: "random-noise")
            let offset = (Double(reference.count) / 8000 - 8) * random.next()
            try check(Array(FingerprintTestAudio.slice(reference, at: offset).reversed()), offset: nil, mode: "real-speech-reversed")
        }
        if let codecPath = environment["TONGXING_FINGERPRINT_CODEC_ROOT"] {
            let codecRoot = URL(fileURLWithPath: codecPath)
            for offset in [99.371, 701.913, 1645.723] {
                try check(pcm(codecRoot.appendingPathComponent("\(offset)-48k.f32")), offset: offset,
                    mode: "mp3-24kbps-to-48kHz", rate: 48000)
            }
        }
        let positives = results.filter(\.positive), negatives = results.filter { !$0.positive }
        let accepted = positives.filter { $0.result.matched && abs($0.errorSeconds ?? .infinity) <= 0.064 }
        let maximumError = positives.compactMap(\.errorSeconds).map(abs).max() ?? 0
        let timing = results.map(\.milliseconds).sorted()
        let report = Report(referencePcmSha256: SHA256.hash(data: try Data(contentsOf: referenceURL)).map { String(format: "%02x", $0) }.joined(),
            referenceDurationSeconds: index.durationSeconds, positives: positives.count, acceptedCorrect: accepted.count,
            negatives: negatives.count, falseAccepts: negatives.filter { $0.result.matched }.count,
            maxErrorSeconds: maximumError, p95Milliseconds: timing[Int(Double(timing.count) * 0.95)], results: results)
        if let path = environment["TONGXING_FINGERPRINT_REPORT"] {
            let url = URL(fileURLWithPath: path)
            try FileManager.default.createDirectory(at: url.deletingLastPathComponent(), withIntermediateDirectories: true)
            let encoder = JSONEncoder(); encoder.outputFormatting = [.prettyPrinted, .sortedKeys]
            try encoder.encode(report).write(to: url, options: .atomic)
        }
        #expect(report.falseAccepts == 0, "Unexpected nonmatching recording accepted")
        #expect(maximumError <= 0.064)
        #expect(accepted.count >= positives.count - 1, "More than one expected low-SNR refusal")
        #expect(positives.filter { !$0.result.matched }.allSatisfy { $0.mode == "white-noise-0dB-gain-0.2" })
        print("Swift fingerprint replay: \(accepted.count)/\(positives.count) positive, \(report.falseAccepts)/\(negatives.count) false accepts; max error \(maximumError)s; P95 \(report.p95Milliseconds)ms")
    }
}
