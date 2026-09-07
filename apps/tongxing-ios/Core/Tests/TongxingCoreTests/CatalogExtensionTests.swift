import Foundation
import Testing
@testable import TongxingCore

struct CatalogExtensionTests {
    private func extended(_ change: (inout [String: Any]) -> Void = { _ in }) throws -> Data {
        var catalog = try #require(JSONSerialization.jsonObject(with: CatalogTests().fixture()) as? [String: Any])
        var weeks = catalog["weeks"] as! [[String: Any]], week = weeks[0]
        var tracks = week["tracks"] as! [[String: Any]], track = tracks[0]
        let hash = track["sha256"] as! String
        week["videoSynchronization"] = "candidate_aligned"
        week["candidateEvidence"] = ["syncMp3Sha256": hash]
        week["transcript"] = ["schemaVersion": BilingualTranscript.supportedSchemaVersion, "blocks": [
            ["blockId": "1", "english": "Second source block.", "sourceTextOrigin": "job.blocks", "reviewState": "unspecified"],
            ["blockId": "0", "english": "First source block.", "chinese": "测试原文。", "sourceTextOrigin": "job.blocks", "reviewState": "candidate"],
        ]]
        let fingerprint = String(repeating: "a", count: 64)
        track["alignment"] = ["schemaVersion": SermonAudioAlignment.supportedSchemaVersion,
            "method": SermonAudioAlignment.supportedMethod, "fingerprintSha256": fingerprint,
            "fingerprintUrl": "/alignment/\(fingerprint)-fingerprint.json", "sourceId": "synthetic-source",
            "referenceAudioSha256": String(repeating: "b", count: 64), "referenceDurationSeconds": 12,
            "timeOrigin": "approved_sermon_clip_start", "sourceVideoOffsetSeconds": 1200,
            "trackSha256": hash, "timeline": "source_clip", "reviewState": "candidate"]
        tracks[0] = track; week["tracks"] = tracks; change(&week)
        weeks[0] = week; catalog["weeks"] = weeks
        return try JSONSerialization.data(withJSONObject: catalog)
    }

    @Test func optionalExtensionsRoundTripAndOriginalEnglishAppearsOnlyAtMatchingBlockEnd() throws {
        let catalog = try WeeklyCatalog.decode(extended()), week = catalog.defaultWeek, track = week.tracks[0]
        let result = week.bilingualCueRows(for: track)
        #expect(result.hasEnglish); #expect(!result.missingEnglish)
        #expect(result.rows.map(\.english) == [nil, "First source block.", "Second source block."])
        #expect(result.rows.map(\.index) == [0, 1, 2]); #expect(result.rows[1].cue.unitId == 1)
        #expect(result.rows[1].reviewState == "candidate")
        #expect(try WeeklyCatalog.decode(JSONEncoder().encode(catalog)) == catalog)
        let legacy = try WeeklyCatalog.decode(CatalogTests().fixture()).defaultWeek
        #expect(legacy.transcript == nil); #expect(legacy.tracks[0].alignment == nil)
        #expect(!legacy.bilingualCueRows(for: legacy.tracks[0]).hasEnglish)
    }

    @Test func numericAndStringCueIDsAssociateByDeclaredIdentityRatherThanArrayPosition() throws {
        let catalog = try WeeklyCatalog.decode(extended { week in
            var tracks = week["tracks"] as! [[String: Any]], track = tracks[0]
            var cues = track["cues"] as! [[String: Any]]
            cues[0]["blockId"] = "0"; cues[1]["blockId"] = "0"
            track["cues"] = cues; tracks[0] = track; week["tracks"] = tracks
        })
        let rows = catalog.defaultWeek.bilingualCueRows(for: catalog.defaultWeek.tracks[0])
        #expect(rows.rows[0].cue.blockId == "0"); #expect(rows.rows[2].english == "Second source block.")
    }

    @Test func missingEnglishStaysMissingAndDoesNotInventOriginalText() throws {
        let catalog = try WeeklyCatalog.decode(extended { week in
            var transcript = week["transcript"] as! [String: Any], blocks = transcript["blocks"] as! [[String: Any]]
            blocks[1].removeValue(forKey: "english"); transcript["blocks"] = blocks; week["transcript"] = transcript
        })
        let rows = catalog.defaultWeek.bilingualCueRows(for: catalog.defaultWeek.tracks[0])
        #expect(rows.missingEnglish); #expect(rows.rows[1].english == nil)
        #expect(rows.rows[1].sourceTextOrigin == nil)
        #expect(rows.rows[2].english == "Second source block.")
    }

    @Test func duplicateMissingAndInvalidTranscriptIdentitiesFailClosed() throws {
        for mutation in [
            { (source: inout [String: Any]) in source["schemaVersion"] = "future-v2" },
            { (source: inout [String: Any]) in var blocks = source["blocks"] as! [[String: Any]]; blocks[1]["blockId"] = "1"; source["blocks"] = blocks },
            { (source: inout [String: Any]) in var blocks = source["blocks"] as! [[String: Any]]; blocks[1]["blockId"] = "missing"; source["blocks"] = blocks },
            { (source: inout [String: Any]) in var blocks = source["blocks"] as! [[String: Any]]; blocks[1]["english"] = "  "; source["blocks"] = blocks },
        ] {
            #expect(throws: (any Error).self) { try WeeklyCatalog.decode(extended { week in
                var transcript = week["transcript"] as! [String: Any]; mutation(&transcript); week["transcript"] = transcript
            }) }
        }
    }

    @Test func candidateCapabilityRemainsBoundToSourceHashTimelineAndReview() throws {
        for (key, value) in [("trackSha256", String(repeating: "d", count: 64) as Any), ("sourceId", "other"),
                             ("timeline", "natural"), ("reviewState", "human_gold"), ("referenceDurationSeconds", 11),
                             ("fingerprintUrl", "https://foreign.example/index.json")] {
            #expect(throws: (any Error).self) { try WeeklyCatalog.decode(extended { week in
                var tracks = week["tracks"] as! [[String: Any]], track = tracks[0], a = track["alignment"] as! [String: Any]
                a[key] = value; track["alignment"] = a; tracks[0] = track; week["tracks"] = tracks
            }) }
        }
        for (key, value) in [("videoSynchronization", "natural" as Any), ("humanApproval", true),
                             ("candidateEvidence", ["syncMp3Sha256": String(repeating: "c", count: 64)])] {
            #expect(throws: (any Error).self) { try WeeklyCatalog.decode(extended { $0[key] = value }) }
        }
        let alignment = try #require(WeeklyCatalog.decode(extended()).defaultWeek.tracks[0].alignment)
        let url = try alignment.indexURL(relativeTo: URL(string: "https://example.org/weekly.json?old=1")!)
        #expect(url.host == "example.org"); #expect(url.path == alignment.fingerprintUrl); #expect(url.query == nil)
        #expect(throws: (any Error).self) { try alignment.indexURL(relativeTo: URL(string: "http://example.org")!) }
    }
}
