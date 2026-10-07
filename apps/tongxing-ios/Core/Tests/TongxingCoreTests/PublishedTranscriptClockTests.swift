import Foundation
import Testing
@testable import TongxingCore

struct PublishedTranscriptClockTests {
    private func data(_ value: Any) throws -> Data { try JSONSerialization.data(withJSONObject: value, options: .sortedKeys) }

    private func fixture(schema: String = "sermon-full-video-text-content-v2") throws -> (MultilingualPage, TargetLanguageReleasePackage, [String: Any], [String: Any]) {
        let url = try #require(Bundle.module.url(forResource: "dev-candidate-catalog-readback", withExtension: "json", subdirectory: "Fixtures"))
        let fixture = try #require(JSONSerialization.jsonObject(with: Data(contentsOf: url)) as? [String: Any])
        let catalog = try MultilingualCatalog.decode(data(fixture["catalog"]!), allowDevCandidates: true)
        let page = catalog.pages[1]
        let releases = fixture["releases"] as! [String: [String: Any]]
        var release = releases["zh-Hans"]!
        release["status"] = "published_http_verified"
        release["httpVerification"] = ["status": "pass", "evidenceSha256": String(repeating: "a", count: 64)]
        release["assets"] = (release["assets"] as! [[String: Any]]).map { asset in
            var asset = asset
            if asset["role"] as? String == "audio" { asset["path"] = "/media/\(page.id)/zh-Hans.mp3" }
            return asset
        }
        let package = try TargetLanguageReleasePackage.decode(data(release))
        let cue: [String: Any] = ["textGroupId": "group-1", "sourceUnitIds": ["source-1"], "text": "Complete source sentence.", "start": 0.0, "end": 180.0]
        let content: [String: Any] = ["schemaVersion": schema, "pageId": page.id, "sourceLocale": "en", "targetLocale": "zh-Hans", "status": "human_reviewed", "englishSourcePackageJsonSha256": page.sourceIdentitySha256, "targetLanguageCandidateJsonSha256": package.targetLanguageCandidateJsonSha256, "sourceMediaSha256": page.sourceMediaSha256 ?? String(repeating: "b", count: 64), "durationSeconds": 180.013167, "audioDurationSeconds": 215.2, "reviewMode": "formal", "title": "Independent clocks", "cues": [cue]]
        var spoken = cue
        spoken["text"] = "Complete spoken sentence."
        spoken["end"] = 215.2
        return (page, package, content, ["cues": [spoken]])
    }

    private func decode(_ f: (MultilingualPage, TargetLanguageReleasePackage, [String: Any], [String: Any]), allowDev: Bool = false) throws -> VerifiedPublishedTranscript {
        try VerifiedPublishedTranscript.decode(content: data(f.2), captions: data(f.3), package: f.1, page: f.0, allowDevCandidate: allowDev)
    }

    @Test func naturalAudioMayOutlastSourceWithoutChangingSourceClock() throws {
        let result = try decode(fixture())
        #expect(result.durationSeconds == 180.013167)
        #expect(result.audioDurationSeconds == 215.2)
        #expect(result.fullText.last?.end == 180)
        #expect(result.captions.last?.end == 215.2)
    }

    @Test func shorterAudioStillLeavesFullTextOnSourceTimeline() throws {
        var f = try fixture()
        f.2["audioDurationSeconds"] = 100.0
        var cues = f.3["cues"] as! [[String: Any]]
        cues[0]["end"] = 100.0; f.3["cues"] = cues
        #expect(try decode(f).audioDurationSeconds == 100)
        #expect(try decode(f).fullText.last?.end == 180)
    }

    @Test func eachCueSetMustStayWithinItsOwnClock() throws {
        var spokenOverflow = try fixture()
        spokenOverflow.2["audioDurationSeconds"] = 215.0
        #expect(throws: (any Error).self) { try decode(spokenOverflow) }
        var sourceOverflow = try fixture()
        var cues = sourceOverflow.2["cues"] as! [[String: Any]]
        cues[0]["end"] = 190.0; sourceOverflow.2["cues"] = cues
        #expect(throws: (any Error).self) { try decode(sourceOverflow) }
    }

    @Test func v2RequiresAudioDurationAndRejectsInvalidDeclaredClocks() throws {
        var missing = try fixture()
        missing.2.removeValue(forKey: "audioDurationSeconds")
        #expect(throws: (any Error).self) { try decode(missing) }
        for schema in ["sermon-full-video-text-content-v1", "sermon-full-video-text-content-v2"] {
            for invalid: Any in [0.0, -1.0, 86400.1, NSNull(), "215.2"] {
                var f = try fixture(schema: schema)
                f.2["audioDurationSeconds"] = invalid
                #expect(throws: (any Error).self) { try decode(f) }
            }
            var f = try fixture(schema: schema)
            f.2["audioDurationSeconds"] = "overflow-duration"
            let valid = String(decoding: try data(f.2), as: UTF8.self)
            // Non-finite numeric overflow must fail even before cue validation.
            let overflowing = Data(valid.replacingOccurrences(of: "\"overflow-duration\"", with: "1e400").utf8)
            #expect(throws: (any Error).self) {
                try VerifiedPublishedTranscript.decode(content: overflowing, captions: data(f.3), package: f.1, page: f.0)
            }
        }
    }

    @Test func legacyAbsentAudioClockFallsBackButDeclaredClockIsHonored() throws {
        var legacy = try fixture(schema: "sermon-full-video-text-content-v1")
        #expect(try decode(legacy).audioDurationSeconds == 215.2)
        legacy.2.removeValue(forKey: "audioDurationSeconds")
        #expect(throws: (any Error).self) { try decode(legacy) }
        var cues = legacy.3["cues"] as! [[String: Any]]
        cues[0]["end"] = 180.0; legacy.3["cues"] = cues
        #expect(try decode(legacy).audioDurationSeconds == 180.013167)
    }

    @Test func v2RequiresKnownReviewModeAndExplicitDevSimulationContext() throws {
        for invalid: Any in ["approved", NSNull(), 1] {
            var f = try fixture()
            f.2["reviewMode"] = invalid
            #expect(throws: (any Error).self) { try decode(f) }
        }
        var missing = try fixture()
        missing.2.removeValue(forKey: "reviewMode")
        #expect(throws: (any Error).self) { try decode(missing) }
        var f = try fixture()
        f.2["reviewMode"] = "simulation"
        #expect(throws: (any Error).self) { try decode(f, allowDev: true) }
        var page = try JSONSerialization.jsonObject(with: JSONEncoder().encode(f.0)) as! [String: Any]
        page["simulationOnly"] = true; page["diagnosticOnly"] = true
        var targets = page["targets"] as! [String: [String: Any]]
        targets["zh-Hans"]!["simulationOnly"] = true
        targets["zh-Hans"]!["diagnosticOnly"] = true
        page["targets"] = targets
        f.0 = try JSONDecoder().decode(MultilingualPage.self, from: data(page))
        #expect(throws: (any Error).self) { try decode(f) }
        #expect(try decode(f, allowDev: true).audioDurationSeconds == 215.2)
        f.2["reviewMode"] = "formal"
        #expect(throws: (any Error).self) { try decode(f, allowDev: true) }
        f.2["reviewMode"] = "simulation"
        for flag in ["simulationOnly", "diagnosticOnly"] {
            var wrongPage = page
            wrongPage.removeValue(forKey: flag)
            f.0 = try JSONDecoder().decode(MultilingualPage.self, from: data(wrongPage))
            #expect(throws: (any Error).self) { try decode(f, allowDev: true) }
            wrongPage = page
            var wrongTargets = targets
            wrongTargets["zh-Hans"]!.removeValue(forKey: flag)
            wrongPage["targets"] = wrongTargets
            f.0 = try JSONDecoder().decode(MultilingualPage.self, from: data(wrongPage))
            #expect(throws: (any Error).self) { try decode(f, allowDev: true) }
        }
    }
}
