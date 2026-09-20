import Foundation

/// Port of web/fingerprint-core.mjs for the published landmark-index contract.
/// Kept separate from the older packed index: the hash quantization is different.
public enum PublishedFingerprintMatcher {
    struct Query {
        let duration: Double
        let rms: Double
        let peakCount: Int
        let landmarks: [(hash: UInt32, time: Int)]
    }
    private struct Peak { let t: Int; let b: Int; let score: Double }
    private static let step = 0.032

    public static func match(samples: [Float], sampleRate: Double,
                             index: PublishedFingerprintIndex) throws -> FingerprintMatchResult {
        try match(query: fingerprint(samples: samples, sampleRate: sampleRate), index: index)
    }

    static func fingerprint(samples: [Float], sampleRate: Double) throws -> Query {
        try Task.checkCancellation()
        guard sampleRate.isFinite, (4000...192000).contains(sampleRate),
              (7...20).contains(Double(samples.count) / sampleRate), samples.allSatisfy(\.isFinite)
        else { throw FingerprintError.invalidAudio("需要7至20秒有效声音") }
        let pcm = try resample(samples, rate: sampleRate)
        let frames = max(0, (pcm.count - 1024) / 256 + 1)
        let rms = sqrt(pcm.reduce(0.0) { $0 + Double($1) * Double($1) } / Double(max(1, pcm.count)))
        var candidates = [[Peak]]()
        let window = (0..<1024).map { 0.5 - 0.5 * cos(2 * .pi * Double($0) / 1023) }
        var real = [Double](repeating: 0, count: 1024)
        var imag = real
        var logs = [Double](repeating: 0, count: 512)
        for t in 0..<frames {
            if t % 16 == 0 { try Task.checkCancellation() }
            for i in 0..<1024 { real[i] = Double(pcm[t * 256 + i]) * window[i]; imag[i] = 0 }
            fft(&real, &imag)
            var average = 0.0
            for b in 24..<440 {
                logs[b] = log(1e-16 + real[b] * real[b] + imag[b] * imag[b])
                average += logs[b]
            }
            average /= 416
            var peaks = [Peak]()
            for b in 27..<436 where logs[b] > logs[b - 1] && logs[b] >= logs[b + 1] && logs[b] > average + 1.2 {
                var local = 0.0
                for k in -10...10 { local += logs[max(24, min(439, b + k))] }
                peaks.append(Peak(t: t, b: b, score: logs[b] - 0.65 * local / 21 - 0.35 * average))
            }
            peaks.sort { $0.score == $1.score ? $0.b < $1.b : $0.score > $1.score }
            candidates.append(Array(peaks.prefix(5)))
        }
        var seconds: [Int: [Peak]] = [:]
        for t in 0..<frames {
            for p in candidates[t] {
                var strongest = true
                for d in -3...3 where t + d >= 0 && t + d < frames {
                    if candidates[t + d].contains(where: { abs($0.b - p.b) <= 3 && $0.score > p.score }) {
                        strongest = false; break
                    }
                }
                if strongest { seconds[Int(floor(Double(t) * step)), default: []].append(p) }
            }
        }
        var peaks = [Peak]()
        for second in seconds.keys.sorted() {
            let ranked = seconds[second]!.sorted {
                if $0.score != $1.score { return $0.score > $1.score }
                // JS stable sort preserves frame order and per-frame score order.
                return $0.t == $1.t ? $0.b < $1.b : $0.t < $1.t
            }
            peaks.append(contentsOf: ranked.prefix(14))
        }
        peaks.sort { $0.t == $1.t ? $0.b < $1.b : $0.t < $1.t }
        var landmarks = [(hash: UInt32, time: Int)]()
        for i in peaks.indices {
            var count = 0
            for j in (i + 1)..<peaks.count {
                let dt = peaks[j].t - peaks[i].t
                if dt < 5 { continue }
                if dt > 44 { break }
                landmarks.append((hash((peaks[i].b + 1) / 2, (peaks[j].b + 1) / 2, dt), peaks[i].t))
                count += 1
                if count >= 8 { break }
            }
        }
        return Query(duration: Double(samples.count) / sampleRate, rms: rms, peakCount: peaks.count, landmarks: landmarks)
    }

    static func match(query: Query, index: PublishedFingerprintIndex) throws -> FingerprintMatchResult {
        var diagnostics = FingerprintDiagnostics(reason: "no_consensus")
        diagnostics.queryDurationSeconds = query.duration
        diagnostics.rms = query.rms; diagnostics.queryLandmarks = query.peakCount
        diagnostics.queryPairs = query.landmarks.count
        func fail(_ reason: String) -> FingerprintMatchResult {
            var info = diagnostics; info.reason = reason
            return .init(matched: false, offsetSeconds: nil, confidence: 0, diagnostics: info)
        }
        if query.rms < 0.0001 { return fail("silence") }
        if query.duration < 7 || query.duration > 20 || query.landmarks.count < 80 { return fail("insufficient_audio") }
        struct Vote { let time: Int; let offset: Int }
        var votes: [Int: [Vote]] = [:]
        var binOrder = [Int]()
        for (qi, pair) in query.landmarks.enumerated() {
            if qi % 32 == 0 { try Task.checkCancellation() }
            let f1 = Int(pair.hash >> 14), f2 = Int((pair.hash >> 6) & 255), dt = Int(pair.hash & 63)
            var seen = Set<Int>()
            for a in -1...1 { for b in -1...1 { for d in -1...1 {
                guard let positions = index.lookup[hash(f1 + a, f2 + b, dt + d)], positions.count <= 80 else { continue }
                for position in positions {
                    let offset = position - pair.time
                    if offset < -2 || Double(offset) * step + query.duration > index.durationSeconds + 0.15 { continue }
                    // JS Math.round rounds a negative half toward positive infinity.
                    let bin = Int(floor(Double(offset) / 2 + 0.5))
                    if !seen.insert(bin).inserted { continue }
                    if votes[bin] == nil { binOrder.append(bin) }
                    votes[bin, default: []].append(Vote(time: pair.time, offset: offset))
                }
            } } }
        }
        guard !binOrder.isEmpty else { return fail("no_consensus") }
        let ranked = binOrder.enumerated().sorted {
            let a = votes[$0.element]!.count, b = votes[$1.element]!.count
            return a == b ? $0.offset < $1.offset : a > b
        }.map(\.element)
        let bestBin = ranked[0], best = votes[bestBin]!
        let second = ranked.first { abs($0 - bestBin) > 6 }.map { votes[$0]!.count } ?? 0
        let offsets = best.map(\.offset).sorted(), anchors = Set(best.map(\.time))
        let span = Double(anchors.max()! - anchors.min()!) * step
        let fraction = Double(best.count) / Double(query.landmarks.count)
        let ratio = Double(best.count) / Double(max(1, second))
        let confidence = [1, Double(best.count) / 65, Double(anchors.count) / 18, span / 6, ratio / 2.5, fraction / 0.10].min()!
        let windows = (0..<3).map { k in
            Set(best.filter { min(2, Int(floor(Double($0.time) * step / query.duration * 3))) == k }.map(\.time)).count
        }
        diagnostics.supportingPairs = best.count; diagnostics.supportingAnchors = anchors.count
        diagnostics.supportFraction = fraction; diagnostics.coverageSeconds = span
        diagnostics.runnerUpPairs = second; diagnostics.separationRatio = ratio
        if best.count < 35 || anchors.count < 12 || span < 4.5 || ratio < 1.8 || fraction < 0.055 || windows.contains(where: { $0 < 3 }) {
            return fail(ratio < 1.8 ? "ambiguous" : "low_confidence")
        }
        diagnostics.reason = "matched"
        return .init(matched: true, offsetSeconds: max(0, Double(offsets[offsets.count / 2]) * step), confidence: confidence, diagnostics: diagnostics)
    }

    private static func hash(_ f1: Int, _ f2: Int, _ dt: Int) -> UInt32 { UInt32((f1 << 14) | (f2 << 6) | dt) }

    private static func resample(_ input: [Float], rate: Double) throws -> [Float] {
        if rate == 8000 { return input }
        let ratio = rate / 8000, cutoff = min(1, 1 / ratio) * 0.94
        let radius = Int(ceil(12 / cutoff))
        var output = [Float](repeating: 0, count: Int(floor(Double(input.count) / ratio)))
        var kernels: [Double: [Double]] = [:]
        for i in output.indices {
            if i % 1024 == 0 { try Task.checkCancellation() }
            let p = Double(i) * ratio, base = Int(floor(p))
            let phase = p - Double(base)
            if kernels[phase] == nil {
                kernels[phase] = (-radius...radius).map { offset in
                    let d = phase - Double(offset), x = Double.pi * d * cutoff
                    return (abs(x) < 1e-8 ? 1 : sin(x) / x) * (0.5 + 0.5 * cos(.pi * d / Double(radius + 1)))
                }
            }
            let kernel = kernels[phase]!
            var sum = 0.0, norm = 0.0
            for offset in -radius...radius {
                let j = base + offset
                guard j >= 0 && j < input.count else { continue }
                let w = kernel[offset + radius]
                sum += Double(input[j]) * w; norm += w
            }
            output[i] = Float(sum / norm)
        }
        return output
    }

    private static func fft(_ re: inout [Double], _ im: inout [Double]) {
        let n = 1024
        var j = 0
        for i in 1..<n {
            var bit = n >> 1
            while j & bit != 0 { j ^= bit; bit >>= 1 }
            j ^= bit
            if i < j { re.swapAt(i, j); im.swapAt(i, j) }
        }
        var size = 2
        while size <= n {
            let a = -2 * Double.pi / Double(size), wr = cos(a), wi = sin(a)
            for base in stride(from: 0, to: n, by: size) {
                var ur = 1.0, ui = 0.0
                for j in 0..<(size / 2) {
                    let k = base + j, l = k + size / 2
                    let tr = ur * re[l] - ui * im[l], ti = ur * im[l] + ui * re[l]
                    re[l] = re[k] - tr; im[l] = im[k] - ti; re[k] += tr; im[k] += ti
                    let nr = ur * wr - ui * wi; ui = ur * wi + ui * wr; ur = nr
                }
            }
            size <<= 1
        }
    }
}
