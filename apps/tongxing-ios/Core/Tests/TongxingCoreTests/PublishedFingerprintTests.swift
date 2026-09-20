import Foundation
import Testing
@testable import TongxingCore

struct PublishedFingerprintTests {
    private let source = String(repeating: "b", count: 64)
    private let indexHash = String(repeating: "c", count: 64)

    func fixture() throws -> (Data, Data) {
        var catalog = try #require(JSONSerialization.jsonObject(with: CatalogTests().fixture()) as? [String: Any])
        var weeks = catalog["weeks"] as! [[String: Any]], week = weeks[0]
        let tracks = week["tracks"] as! [[String: Any]], track = tracks[0]
        let identity: [String: Any] = ["pageId": week["id"]!, "sourceSha256": source,
            "trackSha256": track["sha256"]!, "sourceStartSeconds": 1200, "sourceEndSeconds": 1212,
            "algorithmVersion": "spectral-landmarks-v1"]
        var binding = identity
        binding.merge(["schemaVersion": "sermon-audio-fingerprint-binding-v1", "captureSeconds": 10,
                       "indexSha256": indexHash, "indexUrl": "/fingerprints/\(indexHash.prefix(16))-landmarks.json"]) { _, b in b }
        week["sourceSha256"] = source; week["sourceStartSeconds"] = 1200; week["sourceEndSeconds"] = 1212
        week["audioFingerprint"] = binding; week["videoSynchronization"] = "candidate_aligned"
        week["candidateEvidence"] = ["syncMp3Sha256": track["sha256"]!]
        weeks[0] = week; catalog["weeks"] = weeks
        var index = identity
        index.merge(["schemaVersion": "sermon-landmark-index-v1", "sampleRate": 8000, "hopSize": 256,
                     "fftSize": 1024, "window": ["startSeconds": 1200, "endSeconds": 1212],
                     "durationSeconds": 12, "landmarkCount": 3, "postings": ["230277": [1, 4, 8]]]) { _, b in b }
        return (try JSONSerialization.data(withJSONObject: catalog), try JSONSerialization.data(withJSONObject: index))
    }

    @Test func publishedBindingAndIndexRoundTripWithoutLegacyCapability() throws {
        let (catalogData, indexData) = try fixture()
        let catalog = try WeeklyCatalog.decode(catalogData), week = catalog.defaultWeek
        let binding = try #require(week.audioFingerprint)
        try binding.validate(week: week, track: week.tracks[0])
        #expect(week.tracks[0].alignment == nil)
        let index = try PublishedFingerprintIndex.decode(indexData)
        try index.validate(binding: binding)
        #expect(index.lookup[230277] == [1, 4, 8])
        #expect(try WeeklyCatalog.decode(JSONEncoder().encode(catalog)) == catalog)
        #expect(try binding.indexURL(relativeTo: URL(string: "https://example.org/weekly.json?old=1")!).path == binding.indexUrl)
    }

    @Test func mismatchedSourceWindowTrackAndUnsafeURLCannotEnable() throws {
        let (data, _) = try fixture()
        for (key, value) in [("sourceSha256", String(repeating: "d", count: 64) as Any),
                             ("sourceStartSeconds", 1199 as Any), ("sourceEndSeconds", 1213 as Any),
                             ("trackSha256", String(repeating: "e", count: 64) as Any),
                             ("indexUrl", "https://evil.example/index.json" as Any)] {
            var catalog = try JSONSerialization.jsonObject(with: data) as! [String: Any]
            var weeks = catalog["weeks"] as! [[String: Any]], week = weeks[0]
            var binding = week["audioFingerprint"] as! [String: Any]; binding[key] = value
            week["audioFingerprint"] = binding; weeks[0] = week; catalog["weeks"] = weeks
            let decoded = try WeeklyCatalog.decode(JSONSerialization.data(withJSONObject: catalog)).defaultWeek
            #expect(throws: (any Error).self) { try decoded.audioFingerprint!.validate(week: decoded, track: decoded.tracks[0]) }
        }
    }

    @Test func malformedPostingsAndDifferentAlgorithmRejected() throws {
        let (_, data) = try fixture()
        for (key, value) in [("landmarkCount", 4 as Any), ("fftSize", 2048 as Any),
                             ("postings", ["230277": [4, 1, 8]] as Any),
                             ("postings", ["230277": [-1, 1, 8]] as Any),
                             ("postings", ["230277": [1, 4, 99999]] as Any)] {
            var index = try JSONSerialization.jsonObject(with: data) as! [String: Any]; index[key] = value
            let invalid = try JSONSerialization.data(withJSONObject: index)
            #expect(throws: (any Error).self) { try PublishedFingerprintIndex.decode(invalid) }
        }
    }

    @Test(.enabled(if: ProcessInfo.processInfo.environment["TONGXING_PUBLISHED_CATALOG"] != nil))
    func frozenPublishedCatalogAndIndexWhenRequested() throws {
        guard let catalogPath = ProcessInfo.processInfo.environment["TONGXING_PUBLISHED_CATALOG"],
              let indexPath = ProcessInfo.processInfo.environment["TONGXING_PUBLISHED_INDEX"] else { return }
        let week = try WeeklyCatalog.decode(Data(contentsOf: URL(fileURLWithPath: catalogPath))).defaultWeek
        let binding = try #require(week.audioFingerprint)
        try binding.validate(week: week, track: week.tracks[0])
        let index = try PublishedFingerprintIndex.decode(Data(contentsOf: URL(fileURLWithPath: indexPath)))
        try index.validate(binding: binding)
    }
    @Test(.enabled(if: ProcessInfo.processInfo.environment["TONGXING_PUBLISHED_REPLAY"] != nil))
    func realPublishedReferenceWindowsAndSilence() throws {
        let root = URL(fileURLWithPath: try #require(ProcessInfo.processInfo.environment["TONGXING_PUBLISHED_REPLAY"]))
        let indexPath = try #require(ProcessInfo.processInfo.environment["TONGXING_PUBLISHED_INDEX"])
        let index = try PublishedFingerprintIndex.decode(Data(contentsOf: URL(fileURLWithPath: indexPath)))
        for offset in [30, 300, 900] {
            let bytes = try Data(contentsOf: root.appendingPathComponent("offset-\(offset).f32"))
            let samples = bytes.withUnsafeBytes { buffer in
                (0..<(buffer.count / 4)).map { Float(bitPattern: UInt32(littleEndian: buffer.loadUnaligned(fromByteOffset: $0 * 4, as: UInt32.self))) }
            }
            let result = try PublishedFingerprintMatcher.match(samples: samples, sampleRate: 8000, index: index)
            print("published replay offset=\(offset) result=\(result)")
            #expect(result.matched)
            #expect(abs(try #require(result.offsetSeconds) - Double(offset)) < 0.15)
        }
        let silent = try PublishedFingerprintMatcher.match(samples: Array(repeating: 0, count: 80_000), sampleRate: 8000, index: index)
        #expect(!silent.matched)
    }

}
