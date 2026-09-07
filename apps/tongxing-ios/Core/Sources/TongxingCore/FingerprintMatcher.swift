import Foundation

public struct FingerprintWindowEvidence: Codable, Sendable, Equatable {
    public let matched: Bool
    public let offsetSeconds: Double?
    public let reason: String
}

public struct FingerprintConsistency: Codable, Sendable, Equatable {
    public let passed: Bool
    public let toleranceSeconds: Double
    public let expectedWindowDeltaSeconds: Double
    public let first: FingerprintWindowEvidence
    public let last: FingerprintWindowEvidence
}

public struct FingerprintDiagnostics: Codable, Sendable, Equatable {
    public var reason: String
    public var queryDurationSeconds: Double = 0
    public var queryLandmarks: Int = 0
    public var queryPairs: Int = 0
    public var rms: Double = 0
    public var supportingPairs: Int = 0
    public var supportingAnchors: Int = 0
    public var supportFraction: Double = 0
    public var coverageSeconds: Double = 0
    public var runnerUpPairs: Int = 0
    public var runnerUpOffsetSeconds: Double?
    public var separationRatio: Double = 0
    public var consistency: FingerprintConsistency?
    public let algorithm: String
    public let confidenceKind: String
    public init(reason: String) {
        self.reason = reason; algorithm = "spectral-landmark-pairs"
        confidenceKind = "evidence-score-not-probability"
    }
}

public struct FingerprintMatchResult: Codable, Sendable, Equatable {
    public let matched: Bool
    /// Position of the FIRST query sample on the approved reference clip timeline.
    public let offsetSeconds: Double?
    /// Gate/evidence score, never a calibrated probability or human review label.
    public let confidence: Double
    public let diagnostics: FingerprintDiagnostics
    public init(matched: Bool, offsetSeconds: Double?, confidence: Double, diagnostics: FingerprintDiagnostics) {
        self.matched = matched; self.offsetSeconds = offsetSeconds
        self.confidence = confidence; self.diagnostics = diagnostics
    }
}

/// Browser v1 algorithm port. The same recording played at 1x is required. No
/// speech recognition, translation, media access, UI, or microphone side effects.
/// Call on a detached task; long loops cooperatively check task cancellation.
public enum FingerprintMatcher {
    public static let recommendedCaptureSeconds: Double = 8
    private static let a = FingerprintAlgorithm.supported
    private static let secondsPerFrame: Double = 0.032
    private static let fft = FFTPlan()

    public static func match(samples: [Float], sampleRate: Double, index: FingerprintIndex) throws -> FingerprintMatchResult {
        let duration = try validateAudio(samples, sampleRate)
        guard duration >= 7 else { throw FingerprintError.invalidAudio("一致性检查需要至少7秒声音") }
        let full = try matchWindow(samples: samples, sampleRate: sampleRate, index: index)
        guard full.matched else { return full }
        let windowLength = Int((5 * sampleRate).rounded())
        let lastStart = samples.count - windowLength
        let first = try matchWindow(samples: Array(samples.prefix(windowLength)), sampleRate: sampleRate, index: index)
        let last = try matchWindow(samples: Array(samples.suffix(windowLength)), sampleRate: sampleRate, index: index)
        let expectedDelta = Double(lastStart) / sampleRate
        var consistent = false
        if first.matched, last.matched, let firstOffset = first.offsetSeconds,
           let lastOffset = last.offsetSeconds, let fullOffset = full.offsetSeconds {
            let offsets = [fullOffset, firstOffset, lastOffset - expectedDelta]
            consistent = offsets.max()! - offsets.min()! <= 0.16
        }
        var diagnostics = full.diagnostics
        diagnostics.consistency = FingerprintConsistency(passed: consistent, toleranceSeconds: 0.16,
            expectedWindowDeltaSeconds: expectedDelta,
            first: FingerprintWindowEvidence(matched: first.matched, offsetSeconds: first.offsetSeconds, reason: first.diagnostics.reason),
            last: FingerprintWindowEvidence(matched: last.matched, offsetSeconds: last.offsetSeconds, reason: last.diagnostics.reason))
        guard consistent else { return reject("inconsistent-windows", diagnostics) }
        return FingerprintMatchResult(matched: true, offsetSeconds: full.offsetSeconds,
            confidence: min(full.confidence, first.confidence, last.confidence), diagnostics: diagnostics)
    }

    /// Single-window evidence for diagnostics/tests. Automatic alignment must use
    /// match(), which also requires independent first/last-window consistency.
    static func matchWindow(samples: [Float], sampleRate: Double, index: FingerprintIndex) throws -> FingerprintMatchResult {
        let duration = try validateAudio(samples, sampleRate)
        let (peaks, rms) = try landmarks(samples, sampleRate)
        let query = try pairs(peaks)
        var diagnostics = FingerprintDiagnostics(reason: "no-consistent-offset")
        diagnostics.queryDurationSeconds = duration; diagnostics.queryLandmarks = peaks.count
        diagnostics.queryPairs = query.count; diagnostics.rms = rms
        if rms < 1e-6 { return reject("silence", diagnostics) }
        if Set(peaks.map { quantize($0.f, a.frequencyQuantization) }).count < 8 || peaks.count < 15 {
            return reject("insufficient-distinctive-audio", diagnostics)
        }
        if duration > index.durationSeconds + 0.1 { return reject("query-longer-than-reference", diagnostics) }
        var votes: [Int: [Int]] = [:]
        for (q, pair) in query.enumerated() {
            if q % 32 == 0 { try Task.checkCancellation() }
            var offsets = Set<Int>()
            for d1 in -1...1 { for d2 in -1...1 { for dt in -1...1 {
                let hash = hashPair(pair.f1 + d1, pair.f2 + d2, pair.dt + dt)
                guard let times = index.lookup[hash], times.count <= 80 else { continue }
                for time in times {
                    let offset = time - pair.t
                    if offset < -3 || Double(offset) * secondsPerFrame + duration > index.durationSeconds + 0.15 { continue }
                    offsets.insert(offset)
                }
            } } }
            for offset in offsets { votes[offset, default: []].append(q) }
        }
        guard !votes.isEmpty else { return reject("no-consistent-offset", diagnostics) }
        var ranked: [(offset: Int, count: Int)] = []
        ranked.reserveCapacity(votes.count)
        for (iteration, offset) in votes.keys.enumerated() {
            if iteration % 256 == 0 { try Task.checkCancellation() }
            let supporters = supporters(at: offset, votes: votes)
            ranked.append((offset, supporters.count))
        }
        ranked.sort { $0.count == $1.count ? $0.offset < $1.offset : $0.count > $1.count }
        let best = ranked[0]
        let runner = ranked.first { abs(Double($0.offset - best.offset)) * secondsPerFrame > 0.75 }
        let supported = supporters(at: best.offset, votes: votes)
        let anchors = Set(supported.map { query[$0].anchor })
        let anchorTimes = anchors.map { Double(peaks[$0].t) * secondsPerFrame }
        let coverage = (anchorTimes.max() ?? 0) - (anchorTimes.min() ?? 0)
        let ratio = Double(best.count) / Double(max(1, runner?.count ?? 0))
        let supportFraction = Double(anchors.count) / Double(max(1, Set(query.map(\.anchor)).count))
        diagnostics.supportingPairs = best.count; diagnostics.supportingAnchors = anchors.count
        diagnostics.supportFraction = supportFraction; diagnostics.coverageSeconds = coverage
        diagnostics.runnerUpPairs = runner?.count ?? 0
        diagnostics.runnerUpOffsetSeconds = runner.map { Double($0.offset) * secondsPerFrame }
        diagnostics.separationRatio = ratio
        guard best.count >= 50, anchors.count >= 20, supportFraction >= 0.18,
              coverage >= min(2.5, duration * 0.45) else { return reject("insufficient-consistent-evidence", diagnostics) }
        guard ratio >= 2 else { return reject("ambiguous-offset", diagnostics) }
        var rawOffsets: [Int] = []
        for offset in (best.offset - 1)...(best.offset + 1) {
            for q in votes[offset] ?? [] where supported.contains(q) { rawOffsets.append(offset) }
        }
        rawOffsets.sort()
        let position = max(0, Double(rawOffsets[rawOffsets.count / 2]) * secondsPerFrame)
        let confidence = [1, Double(best.count) / 80, Double(anchors.count) / 25,
            supportFraction / 0.4, coverage / (duration * 0.6), ratio / 3].min()!
        diagnostics.reason = "matched"
        return FingerprintMatchResult(matched: true, offsetSeconds: position, confidence: confidence, diagnostics: diagnostics)
    }

    private static func reject(_ reason: String, _ evidence: FingerprintDiagnostics) -> FingerprintMatchResult {
        var diagnostics = evidence; diagnostics.reason = reason
        return FingerprintMatchResult(matched: false, offsetSeconds: nil, confidence: 0, diagnostics: diagnostics)
    }

    private static func supporters(at offset: Int, votes: [Int: [Int]]) -> Set<Int> {
        var output = Set(votes[offset - 1] ?? [])
        output.formUnion(votes[offset] ?? []); output.formUnion(votes[offset + 1] ?? [])
        return output
    }

    private static func validateAudio(_ samples: [Float], _ sampleRate: Double) throws -> Double {
        try Task.checkCancellation()
        guard sampleRate.isFinite, (8000...192000).contains(sampleRate) else { throw FingerprintError.invalidAudio("采样率超出范围") }
        let duration = Double(samples.count) / sampleRate
        guard (5...20).contains(duration) else { throw FingerprintError.invalidAudio("需要5至20秒声音") }
        guard samples.allSatisfy(\.isFinite) else { throw FingerprintError.invalidAudio("采样包含非有限值") }
        return duration
    }

    private struct Peak { let t: Int; let f: Int; let strength: Double }
    private struct Pair { let t: Int; let anchor: Int; let f1: Int; let f2: Int; let dt: Int }
    private static func quantize(_ value: Int, _ step: Int) -> Int { Int((Double(value) / Double(step)).rounded()) }
    private static func hashPair(_ f1: Int, _ f2: Int, _ dt: Int) -> UInt32 { UInt32((f1 << 14) | (f2 << 6) | dt) }

    private static func pairs(_ peaks: [Peak]) throws -> [Pair] {
        var output: [Pair] = []
        output.reserveCapacity(peaks.count * a.fanout)
        for i in peaks.indices {
            if i % 128 == 0 { try Task.checkCancellation() }
            let anchor = peaks[i]
            var count = 0
            for j in (i + 1)..<peaks.count {
                let delta = peaks[j].t - anchor.t
                if delta < a.pairMinFrames { continue }
                if delta > a.pairMaxFrames || count >= a.fanout { break }
                output.append(Pair(t: anchor.t, anchor: i, f1: quantize(anchor.f, a.frequencyQuantization),
                    f2: quantize(peaks[j].f, a.frequencyQuantization), dt: quantize(delta, a.deltaQuantization)))
                count += 1
            }
        }
        return output
    }

    // Symmetric windowed-sinc filtering matches the browser converter, including
    // its 1/1024 phase quantization. It does not add a causal resampling delay.
    private static func resample(_ samples: [Float], _ sampleRate: Double) throws -> [Float] {
        if sampleRate == 8000 { return samples }
        let ratio = sampleRate / 8000, radius = Int(ceil(12 * sampleRate / 8000)), cutoff = 0.46 / (sampleRate / 8000)
        var output = [Float](repeating: 0, count: Int(floor(Double(samples.count) / ratio)))
        var phases: [Int: [Double]] = [:]
        for i in output.indices {
            if i % 2048 == 0 { try Task.checkCancellation() }
            let position = Double(i) * ratio, center = Int(floor(position))
            let phase = Int(((position - Double(center)) * 1024).rounded())
            if phases[phase] == nil {
                var kernel = [Double](repeating: 0, count: radius * 2 + 1), sum = 0.0
                for k in -radius...radius {
                    let distance = Double(k) - Double(phase) / 1024
                    let sinc = distance == 0 ? 2 * cutoff : sin(2 * .pi * cutoff * distance) / (.pi * distance)
                    kernel[k + radius] = sinc * (0.5 + 0.5 * cos(.pi * distance / Double(radius + 1)))
                    sum += kernel[k + radius]
                }
                for k in kernel.indices { kernel[k] /= sum }
                phases[phase] = kernel
            }
            let kernel = phases[phase]!
            var value = 0.0
            for k in -radius...radius {
                let source = center + k
                if source >= 0 && source < samples.count { value += Double(samples[source]) * kernel[k + radius] }
            }
            output[i] = Float(value)
        }
        return output
    }

    private struct FFTPlan: Sendable {
        struct Stage: Sendable { let length: Int; let real: [Double]; let imag: [Double] }
        let reverse: [Int]
        let window: [Double]
        let stages: [Stage]
        init() {
            let n = 1024
            var reverse = [Int](repeating: 0, count: n), window = [Double](repeating: 0, count: n)
            for i in 0..<n {
                var x = i, y = 0
                for _ in 0..<10 { y = (y << 1) | (x & 1); x >>= 1 }
                reverse[i] = y; window[i] = 0.5 - 0.5 * cos(2 * .pi * Double(i) / Double(n - 1))
            }
            var stages: [Stage] = [], length = 2
            while length <= n {
                let real = (0..<(length / 2)).map { cos(-2 * .pi * Double($0) / Double(length)) }
                let imag = (0..<(length / 2)).map { sin(-2 * .pi * Double($0) / Double(length)) }
                stages.append(Stage(length: length, real: real, imag: imag)); length <<= 1
            }
            self.reverse = reverse; self.window = window; self.stages = stages
        }
    }

    private static func landmarks(_ samples: [Float], _ sampleRate: Double) throws -> ([Peak], Double) {
        let pcm = try resample(samples, sampleRate)
        let frames = (pcm.count - a.fftSize) / a.hopSize + 1, bins = a.maxBin + a.frequencyRadius + 1
        var spectra = [Float](repeating: 0, count: frames * bins)
        var real = [Double](repeating: 0, count: a.fftSize), imag = [Double](repeating: 0, count: a.fftSize)
        var totalEnergy = 0.0
        for t in 0..<frames {
            if t % 32 == 0 { try Task.checkCancellation() }
            let start = t * a.hopSize
            for i in 0..<a.fftSize {
                let value = Double(pcm[start + i])
                real[fft.reverse[i]] = value * fft.window[i]; imag[i] = 0
                totalEnergy += value * value
            }
            for stage in fft.stages {
                let half = stage.length / 2
                for base in stride(from: 0, to: a.fftSize, by: stage.length) {
                    for j in 0..<half {
                        let u = base + j, v = u + half
                        let r = real[v] * stage.real[j] - imag[v] * stage.imag[j]
                        let m = real[v] * stage.imag[j] + imag[v] * stage.real[j]
                        real[v] = real[u] - r; imag[v] = imag[u] - m
                        real[u] += r; imag[u] += m
                    }
                }
            }
            let row = t * bins
            for f in 0..<bins { spectra[row + f] = Float(10 * log10(1e-20 + real[f] * real[f] + imag[f] * imag[f])) }
        }
        let rms = sqrt(totalEnergy / Double(frames * a.fftSize))
        if rms < 1e-6 { return ([], rms) }
        var tiles = [[Peak]](repeating: [], count: (frames + a.tileFrames - 1) / a.tileFrames)
        for t in a.timeRadius..<(frames - a.timeRadius) {
            if t % 32 == 0 { try Task.checkCancellation() }
            let row = t * bins
            for f in a.minBin...a.maxBin {
                let value = spectra[row + f]
                if value <= spectra[row + f - 1] || value < spectra[row + f + 1] { continue }
                var maximum = true
                for dt in -a.timeRadius...a.timeRadius {
                    for df in -a.frequencyRadius...a.frequencyRadius {
                        if dt == 0 && df == 0 { continue }
                        if spectra[(t + dt) * bins + f + df] > value { maximum = false; break }
                    }
                    if !maximum { break }
                }
                if !maximum { continue }
                var background = 0.0, count = 0
                for df in -18...18 {
                    if abs(df) < 4 || f + df < 1 || f + df >= bins { continue }
                    background += Double(spectra[row + f + df]); count += 1
                }
                let prominence = Double(value) - background / Double(count)
                if prominence < a.minProminenceDb { continue }
                tiles[t / a.tileFrames].append(Peak(t: t, f: f, strength: prominence))
            }
        }
        var peaks: [Peak] = []
        for candidates in tiles {
            let sorted = candidates.sorted {
                if $0.strength != $1.strength { return $0.strength > $1.strength }
                return $0.t == $1.t ? $0.f < $1.f : $0.t < $1.t
            }
            peaks.append(contentsOf: sorted.prefix(a.peaksPerTile))
        }
        peaks.sort { $0.t == $1.t ? $0.f < $1.f : $0.t < $1.t }
        return (peaks, rms)
    }
}
