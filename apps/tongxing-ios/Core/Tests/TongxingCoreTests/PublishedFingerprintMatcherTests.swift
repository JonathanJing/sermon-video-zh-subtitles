import Foundation
import Testing
@testable import TongxingCore

/// Oracle comes from the production JavaScript implementation, never from the
/// Swift matcher under test. These synthetic signals do not establish venue QA.
struct PublishedFingerprintMatcherTests {
    private struct Golden: Decodable {
        struct Query: Decodable {
            let durationSeconds: Double
            let rms: Double
            let peakCount: Int
            let landmarks: [[Int]]
        }
        struct Result: Decodable {
            struct Diagnostics: Decodable {
                let reason: String
                let votes: Int?
                let distinctAnchors: Int?
                let matchFraction: Double?
                let runnerUpVotes: Int?
                let peakRatio: Double?
                let coveredSeconds: Double?
            }
            let matched: Bool
            let queryStartSeconds: Double?
            let confidence: Double
            let diagnostics: Diagnostics
        }
        struct Case: Decodable {
            let sampleRate: Int
            let query: Query
            let expectedMatch: Result
            let expectedAmbiguous: Result
            let expectedUnrelated: Result
            let expectedSilence: Result
        }
        let unrelatedLandmarks: [[Int]]
        let cases: [Case]
    }

    @Test(arguments: [8000, 44100, 48000])
    func publishedDSPMatchesBrowserGolden(sampleRate: Int) throws {
        let fixture = try golden()
        let item = try #require(fixture.cases.first { $0.sampleRate == sampleRate })
        let samples = signal(sampleRate)
        let query = try PublishedFingerprintMatcher.fingerprint(samples: samples, sampleRate: Double(sampleRate))
        #expect(query.duration == item.query.durationSeconds)
        #expect(abs(query.rms - item.query.rms) < 1e-8)
        #expect(query.peakCount == item.query.peakCount)
        #expect(query.landmarks.map { [Int($0.hash), $0.time] } == item.query.landmarks)

        let matchingIndex = try index(item.query.landmarks)
        let actual = try PublishedFingerprintMatcher.match(samples: samples, sampleRate: Double(sampleRate), index: matchingIndex)
        compare(actual, to: item.expectedMatch)
        #expect(actual.matched)
        #expect(actual.offsetSeconds == 20)

        let ambiguous = try PublishedFingerprintMatcher.match(query: query,
            index: index(item.query.landmarks, shifts: [625, 1562]))
        compare(ambiguous, to: item.expectedAmbiguous)
        #expect(!ambiguous.matched)
        #expect(ambiguous.diagnostics.reason == "ambiguous")

        let unrelated = try PublishedFingerprintMatcher.match(query: query, index: index(fixture.unrelatedLandmarks))
        compare(unrelated, to: item.expectedUnrelated)
        #expect(!unrelated.matched)
        #expect(unrelated.offsetSeconds == nil)

        let silence = try PublishedFingerprintMatcher.match(samples: [Float](repeating: 0, count: sampleRate * 10),
            sampleRate: Double(sampleRate), index: matchingIndex)
        compare(silence, to: item.expectedSilence)
        #expect(silence.diagnostics.reason == "silence")
        #expect(silence.offsetSeconds == nil)
    }

    @Test func invalidAudioIsRejectedBeforeDSP() throws {
        #expect(throws: FingerprintError.self) {
            try PublishedFingerprintMatcher.fingerprint(samples: [], sampleRate: 8000)
        }
        #expect(throws: FingerprintError.self) {
            try PublishedFingerprintMatcher.fingerprint(samples: [Float](repeating: .nan, count: 80000), sampleRate: 8000)
        }
        #expect(throws: FingerprintError.self) {
            try PublishedFingerprintMatcher.fingerprint(samples: [Float](repeating: 0, count: 80000), sampleRate: .infinity)
        }
    }

    private func compare(_ actual: FingerprintMatchResult, to expected: Golden.Result) {
        #expect(actual.matched == expected.matched)
        #expect(actual.offsetSeconds == expected.queryStartSeconds)
        #expect(abs(actual.confidence - expected.confidence) < 1e-12)
        #expect(actual.diagnostics.reason == expected.diagnostics.reason)
        if let votes = expected.diagnostics.votes { #expect(actual.diagnostics.supportingPairs == votes) }
        if let count = expected.diagnostics.distinctAnchors { #expect(actual.diagnostics.supportingAnchors == count) }
        if let fraction = expected.diagnostics.matchFraction { #expect(abs(actual.diagnostics.supportFraction - fraction) < 1e-12) }
        if let votes = expected.diagnostics.runnerUpVotes { #expect(actual.diagnostics.runnerUpPairs == votes) }
        if let ratio = expected.diagnostics.peakRatio { #expect(abs(actual.diagnostics.separationRatio - ratio) < 1e-12) }
        if let covered = expected.diagnostics.coveredSeconds { #expect(abs(actual.diagnostics.coverageSeconds - covered) < 1e-12) }
    }

    private func golden() throws -> Golden {
        let url = try #require(Bundle.module.url(forResource: "published-fingerprint.golden", withExtension: "json", subdirectory: "Fixtures"))
        return try JSONDecoder().decode(Golden.self, from: Data(contentsOf: url))
    }

    private func index(_ landmarks: [[Int]], shifts: [Int] = [625]) throws -> PublishedFingerprintIndex {
        var postings: [String: [Int]] = [:]
        for pair in landmarks {
            for shift in shifts { postings[String(pair[0]), default: []].append(pair[1] + shift) }
        }
        for key in Array(postings.keys) { postings[key]!.sort() }
        let doc: [String: Any] = [
            "schemaVersion": "sermon-landmark-index-v1", "algorithmVersion": "spectral-landmarks-v1",
            "sampleRate": 8000, "hopSize": 256, "fftSize": 1024,
            "sourceSha256": String(repeating: "a", count: 64), "trackSha256": String(repeating: "b", count: 64),
            "pageId": "matcher-golden", "sourceStartSeconds": 100, "sourceEndSeconds": 190,
            "window": ["startSeconds": 100, "endSeconds": 190], "durationSeconds": 90,
            "landmarkCount": landmarks.count * shifts.count, "postings": postings
        ]
        return try PublishedFingerprintIndex.decode(JSONSerialization.data(withJSONObject: doc))
    }

    /// Keep formula aligned with generate-published-fingerprint-golden.mjs.
    private func signal(_ rate: Int) -> [Float] {
        (0..<(rate * 10)).map { i in
            let t = Double(i) / Double(rate)
            let firstPhase = 300 * t + 45 * t * t + 90 * sin(1.7 * t)
            let secondPhase = 1100 * t - 29 * t * t + 65 * sin(2.3 * t)
            let thirdPhase = 2100 * t + 13 * t * t + 40 * sin(0.9 * t)
            let first = 0.18 * sin(2 * Double.pi * firstPhase)
            let second = 0.12 * sin(2 * Double.pi * secondPhase)
            let third = 0.08 * sin(2 * Double.pi * thirdPhase)
            return Float(first + second + third)
        }
    }
}
