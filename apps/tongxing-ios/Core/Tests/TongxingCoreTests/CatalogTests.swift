import Foundation
import Testing
@testable import TongxingCore

struct CatalogTests {
    func fixture() throws -> Data {
        let url = try #require(Bundle.module.url(forResource: "catalog.synthetic", withExtension: "json", subdirectory: "Fixtures"))
        return try Data(contentsOf: url)
    }

    func modified(_ change: (inout [String: Any]) -> Void) throws -> Data {
        var object = try #require(JSONSerialization.jsonObject(with: fixture()) as? [String: Any])
        change(&object)
        return try JSONSerialization.data(withJSONObject: object)
    }

    func modifiedTrack(_ change: (inout [String: Any]) -> Void) throws -> Data {
        try modified { object in
            var weeks = object["weeks"] as! [[String: Any]]
            var tracks = weeks[0]["tracks"] as! [[String: Any]]
            change(&tracks[0])
            weeks[0]["tracks"] = tracks
            object["weeks"] = weeks
        }
    }

    @Test func testSyntheticCatalogPreservesSourceAndCandidateEvidence() throws {
        let catalog = try WeeklyCatalog.decode(fixture())
        #expect(catalog.defaultWeek.sourceId == "synthetic-source")
        #expect(catalog.defaultWeek.humanApproval == .bool(false))
        #expect(catalog.defaultWeek.tracks[0].scope == "full_candidate")
        #expect(catalog.defaultWeek.tracks[0].subtitleTiming == "source_video_aligned_candidate")
        #expect(catalog.defaultWeek.outline?.first?.sourceSliceIndexes == [0])
        #expect(try WeeklyCatalog.decode(JSONEncoder().encode(catalog)) == catalog)
    }

    @Test func testUnknownApprovalMetadataIsPreservedAsData() throws {
        let data = try modified { object in
            var weeks = object["weeks"] as! [[String: Any]]
            weeks[0]["humanApproval"] = ["newReviewType": "machine", "accepted": true]
            object["weeks"] = weeks
            object["futureField"] = "ignored"
        }
        let week = try WeeklyCatalog.decode(data).defaultWeek
        #expect(week.humanApproval == .object(["newReviewType": .string("machine"), "accepted": .bool(true)]))
        #expect(week.contentReview == "synthetic fixture; no human approval")
    }

    @Test func testUnsupportedSchemaAndMissingDefaultFailClosed() throws {
        for mutation in [
            { (object: inout [String: Any]) in object["schemaVersion"] = "future-v2" },
            { (object: inout [String: Any]) in object["defaultWeekId"] = "missing" },
            { (object: inout [String: Any]) in object["weeks"] = [] }
        ] {
            #expect(throws: (any Error).self) { try WeeklyCatalog.decode(modified(mutation)) }
        }
    }

    @Test func testDuplicateWeekAndTrackIDsFailClosed() throws {
        #expect(throws: (any Error).self) { try WeeklyCatalog.decode(modified { object in
            let weeks = object["weeks"] as! [[String: Any]]
            object["weeks"] = weeks + weeks
        }) }
        #expect(throws: (any Error).self) { try WeeklyCatalog.decode(modified { object in
            var weeks = object["weeks"] as! [[String: Any]]
            let tracks = weeks[0]["tracks"] as! [[String: Any]]
            weeks[0]["tracks"] = tracks + tracks
            object["weeks"] = weeks
        }) }
    }

    @Test func testInvalidDatesAndSourceURLsFailClosed() throws {
        for (key, badValue) in [("date", "2026-02-30"), ("date", "2026-9-5"),
                                ("sourceUrl", "http://example.org"), ("sourceUrl", "https://user:secret@example.org"),
                                ("sourceId", "") ] {
            #expect(throws: (any Error).self) { try WeeklyCatalog.decode(modified { object in
                var weeks = object["weeks"] as! [[String: Any]]
                weeks[0][key] = badValue
                object["weeks"] = weeks
            }) }
        }
    }

    @Test func testHashAndDurationValidation() throws {
        for hash in ["", String(repeating: "a", count: 63), String(repeating: "g", count: 64)] {
            #expect(throws: (any Error).self) { try WeeklyCatalog.decode(modifiedTrack { $0["sha256"] = hash }) }
        }
        for duration in [0, -1, 11] {
            #expect(throws: (any Error).self) { try WeeklyCatalog.decode(modifiedTrack { $0["durationSeconds"] = duration }) }
        }
        let track = try WeeklyCatalog.decode(fixture()).defaultWeek.tracks[0]
        let invalid = SermonTrack(id: track.id, label: track.label, voiceLabel: track.voiceLabel,
                                  audioUrl: track.audioUrl, file: track.file, sha256: track.sha256,
                                  durationSeconds: .infinity, cues: [], subtitleTiming: "candidate", scope: "candidate")
        #expect(throws: (any Error).self) { try invalid.validate() }
    }

    @Test func testMediaURLCannotEscapeConfiguredHostOrDirectory() throws {
        let filenames = ["../secret.mp3", "file%2Emp3", "file\\secret.mp3", "..mp3", "a/track.mp3", "audio.mp3?token=secret"]
        for filename in filenames {
            #expect(throws: (any Error).self) { try WeeklyCatalog.decode(modifiedTrack {
                $0["file"] = filename; $0["audioUrl"] = "/media/" + filename
            }) }
        }
        for url in ["https://other.example/media/0123456789abcdef-synthetic.mp3", "//other.example/x.mp3",
                    "/media/../0123456789abcdef-synthetic.mp3", "/media/0123456789abcdef-synthetic.mp3?x=1",
                    "/media/different.mp3", "/%6dedia/0123456789abcdef-synthetic.mp3"] {
            #expect(throws: (any Error).self) { try WeeklyCatalog.decode(modifiedTrack { $0["audioUrl"] = url }) }
        }
        let track = try WeeklyCatalog.decode(fixture()).defaultWeek.tracks[0]
        let resolved = try track.mediaURL(relativeTo: URL(string: "https://example.org/ignored?query=1#fragment")!)
        #expect(resolved.absoluteString == "https://example.org/media/0123456789abcdef-synthetic.mp3")
        #expect(throws: (any Error).self) { try track.mediaURL(relativeTo: URL(string: "http://example.org")!) }
    }

    @Test func testOverlappingReversedAndDuplicateCuesFailClosed() throws {
        for change in [
            { (cues: inout [[String: Any]]) in cues[1]["start"] = 2 },
            { (cues: inout [[String: Any]]) in cues[0]["start"] = -1 },
            { (cues: inout [[String: Any]]) in cues[0]["end"] = 0 },
            { (cues: inout [[String: Any]]) in cues[2]["end"] = 13 },
            { (cues: inout [[String: Any]]) in cues[1]["unitId"] = 0 },
            { (cues: inout [[String: Any]]) in cues[1]["text"] = "  " },
            { (cues: inout [[String: Any]]) in cues.reverse() }
        ] {
            #expect(throws: (any Error).self) { try WeeklyCatalog.decode(modifiedTrack { track in
                var cues = track["cues"] as! [[String: Any]]
                change(&cues)
                track["cues"] = cues
            }) }
        }
    }

    @Test func testCueLookupRespectsGapEndAndSharedBoundary() throws {
        let track = try WeeklyCatalog.decode(fixture()).defaultWeek.tracks[0]
        #expect(track.cue(at: 0)?.unitId == 0)
        #expect(track.cue(at: 3) == nil)
        #expect(track.cue(at: 3.99) == nil)
        #expect(track.cue(at: 4)?.unitId == 1)
        #expect(track.cue(at: 8)?.unitId == 2)
        for time in [-1, 12, .nan, .infinity] { #expect(track.cue(at: time) == nil) }
    }

    @Test(.enabled(if: ProcessInfo.processInfo.environment["TONGXING_CATALOG_SMOKE_PATH"] != nil))
    func testOptionalFrozenPublishedCatalogSmoke() throws {
        guard let path = ProcessInfo.processInfo.environment["TONGXING_CATALOG_SMOKE_PATH"] else {
            return
        }
        let catalog = try WeeklyCatalog.decode(Data(contentsOf: URL(fileURLWithPath: path)))
        #expect(!(catalog.weeks.isEmpty))
        #expect(catalog.defaultWeek.id == catalog.defaultWeekId)
    }
}
