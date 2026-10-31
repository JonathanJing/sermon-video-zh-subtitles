import Foundation
import CryptoKit
import TongxingCore
import XCTest
@testable import Tongxing

final class WeeklyGuideDataTests: XCTestCase {
    private let fixture = """
    {"guides":[{"id":"synthetic-sermon","week":7,"title":"Sample",
    "scripture":"Example 1","sections":[
    {"id":"page-1","title":"First","subtitle":"One","symbol":"doc.text","body":"A"},
    {"id":"page-2","title":"Second","subtitle":"Two","symbol":"doc.text","body":"B"}]},
    {"id":"another-sermon","week":3,"title":"Another sample","scripture":"Example 2",
    "sections":[{"id":"page-3","title":"Third","subtitle":"Three","symbol":"doc.text","body":"C"}]}]}
    """.data(using: .utf8)!

    func testOnlyExactSermonAndSimplifiedChineseMatch() {
        let guide = WeeklyGuideRepository.load(pageID: "synthetic-sermon", locale: "zh-Hans", data: fixture)
        XCTAssertEqual(guide?.week, 7)
        XCTAssertEqual(guide?.sections.map(\.id), ["page-1", "page-2"])
        let other = WeeklyGuideRepository.load(pageID: "another-sermon", locale: "zh-Hans", data: fixture)
        XCTAssertEqual(other?.week, 3)
        XCTAssertEqual(other?.sections.map(\.id), ["page-3"])
        XCTAssertNil(WeeklyGuideRepository.load(pageID: "other-sermon", locale: "zh-Hans", data: fixture))
        XCTAssertNil(WeeklyGuideRepository.load(pageID: nil, locale: "zh-Hans", data: fixture))
        XCTAssertNil(WeeklyGuideRepository.load(pageID: "synthetic-sermon", locale: "zh-Hant", data: fixture))
        XCTAssertNil(WeeklyGuideRepository.load(pageID: "synthetic-sermon", locale: "en", data: fixture))
    }

    func testInvalidOrAmbiguousPayloadDoesNotDisplayGuide() {
        XCTAssertNil(WeeklyGuideRepository.load(pageID: "synthetic-sermon", locale: "zh-Hans", data: Data()))
        XCTAssertNil(WeeklyGuideRepository.load(pageID: "synthetic-sermon", locale: "zh-Hans", data: Data("{bad".utf8)))
        let duplicated = """
        {"guides":[
          {"id":"x","week":1,"title":"A","scripture":"X","sections":[{"id":"1","title":"A","subtitle":"A","symbol":"book","body":"A"}]},
          {"id":"x","week":2,"title":"B","scripture":"Y","sections":[{"id":"2","title":"B","subtitle":"B","symbol":"book","body":"B"}]}
        ]}
        """.data(using: .utf8)!
        XCTAssertNil(WeeklyGuideRepository.load(pageID: "x", locale: "zh-Hans", data: duplicated))
    }

    func testStructuredContentKeepsTableRowsAndFlowOrder() throws {
        let json = #"""
        {"id":"p","title":"来源表格","subtitle":"页 1","symbol":"book","body":"完整纯文字",
         "blocks":[
            {"type":"paragraph","text":"介绍"},
            {"type":"table","title":"对照","columns":["","含义"],"rows":[["甲","乙"],["丙",""]],"footnote":"出处"},
            {"type":"list","title":"项目","items":["第一","第二"]},
            {"type":"flow","title":"次序","items":["光","水","地"]},
            {"type":"image","assetID":"weekly-guide-statue.jpg","alt":"图像文字说明","caption":"图注"}
         ]}
        """#
        let section = try JSONDecoder().decode(WeeklyGuideSection.self, from: Data(json.utf8))
        XCTAssertEqual(section.body, "完整纯文字")
        XCTAssertEqual(section.blocks, [
            .paragraph(text: "介绍"),
            .table(title: "对照", columns: ["", "含义"], rows: [["甲", "乙"], ["丙", ""]], footnote: "出处"),
            .list(title: "项目", items: ["第一", "第二"]),
            .flow(title: "次序", items: ["光", "水", "地"]),
            .image(assetID: "weekly-guide-statue.jpg", alt: "图像文字说明", caption: "图注")
        ])
    }

    func testUnsupportedOrMalformedBlocksFallBackToEntirePlainBody() throws {
        for blocks in [
            #"[{"type":"paragraph","text":"partial"},{"type":"future"}]"#,
            #"[{"type":"table","title":"bad","columns":["A","B"],"rows":[["one"]]}]"#,
            #"[{"type":"flow","items":[]}]"#,
            #"[{"type":"paragraph","text":"部分文字","newContent":"不可丢失"}]"#,
            #"[{"type":"image","assetID":"../../secret.jpg","alt":"x","caption":"x"}]"#,
            #"[{"type":"image","assetID":"weekly-guide-statue.jpg","alt":"x"}]"#,
            #"[]"#,
            #"null"#
        ] {
            let json = """
            {"id":"p","title":"T","subtitle":"S","symbol":"book","body":"完整纯文字", "blocks":\(blocks)}
            """
            let section = try JSONDecoder().decode(WeeklyGuideSection.self, from: Data(json.utf8))
            XCTAssertNil(section.blocks, blocks)
            XCTAssertEqual(section.body, "完整纯文字")
        }
        let missingBody = #"{"id":"p","title":"T","subtitle":"S","symbol":"book","body":"", "blocks":[{"type":"future"}]}"#
        XCTAssertThrowsError(try JSONDecoder().decode(WeeklyGuideSection.self, from: Data(missingBody.utf8)))
    }

    func testOnlyKnownBundledImageBytesCanBeUsed() {
        XCTAssertTrue(WeeklyGuideImageAssets.isAllowed("weekly-guide-statue.jpg"))
        XCTAssertTrue(WeeklyGuideImageAssets.isAllowed("weekly-guide-son-of-man.jpg"))
        XCTAssertFalse(WeeklyGuideImageAssets.isAllowed("../weekly-guide-statue.jpg"))
        XCTAssertFalse(WeeklyGuideImageAssets.isAllowed("https://example.com/statue.jpg"))
        XCTAssertFalse(WeeklyGuideImageAssets.verifies(Data("bad bytes".utf8), assetID: "weekly-guide-statue.jpg"))
    }

    func testSourceBackedMapDecodesAndRejectsUntrustedPoints() throws {
        func section(_ points: String) throws -> WeeklyGuideSection {
            let json = """
            {"id":"p","title":"地图","subtitle":"来源","symbol":"book","body":"完整的地点列表",
             "blocks":[{"type":"map","title":"地点","caption":"地点约略位置示意，并非教会建筑精确位置",
             "attribution":"Pleiades CC BY 3.0","points":\(points)}]}
            """
            return try JSONDecoder().decode(WeeklyGuideSection.self, from: Data(json.utf8))
        }
        let valid = #"[{"name":"甲","latitude":37.9,"longitude":27.3,"sourceURL":"https://pleiades.stoa.org/places/599612","credit":"Contributor A"},{"name":"乙","latitude":38.4,"longitude":27.1,"sourceURL":"https://pleiades.stoa.org/places/550893","credit":"Contributor B"}]"#
        guard case .map(_, let points, _, _) = try XCTUnwrap(section(valid).blocks?.first) else {
            return XCTFail("Expected a source-backed map")
        }
        XCTAssertEqual(points.map(\.name), ["甲", "乙"])
        for invalid in [
            valid.replacingOccurrences(of: "https://pleiades.stoa.org", with: "https://example.com"),
            valid.replacingOccurrences(of: "37.9", with: "137.9"),
            valid.replacingOccurrences(of: "\"乙\"", with: "\"甲\""),
            valid.replacingOccurrences(of: "Contributor A", with: "")
        ] {
            XCTAssertNil(try section(invalid).blocks)
            XCTAssertEqual(try section(invalid).body, "完整的地点列表")
        }
    }
}

final class WeeklyGuideRemoteTests: XCTestCase {
    private let origin = URL(string: "https://example.org")!
    private let source = String(repeating: "a", count: 64)
    private let release = String(repeating: "b", count: 64)
    private var selection: WeeklyGuideSelection {
        WeeklyGuideSelection(pageID: "test-sermon", locale: "zh-Hans", editionId: "test-edition",
                             sourceIdentitySha256: source, releasePackageJsonSha256: release)
    }
    private var payload: Data {
        Data("""
        {"id":"test-sermon","week":8,"title":"Example","scripture":"Example 1",
         "sections":[{"id":"s1","title":"Section","subtitle":"Example","symbol":"book","body":"Synthetic"}]}
        """.utf8)
    }
    private func manifest(payload: Data, pageID: String = "test-sermon", week: Int = 8,
                          hash: String? = nil, path: String = "/weekly-guides/published/example.json",
                          schema: String = "tongxing-weekly-guide-manifest-v1", status: String = "available",
                          edition: String = "test-edition", sourceSHA: String? = nil,
                          releaseSHA: String? = nil, review: String = "machine_translation_not_human_reviewed") throws -> Data {
        let sha = hash ?? WeeklyGuideRepository.sha256(payload)
        return try JSONSerialization.data(withJSONObject: [
            "schemaVersion": schema, "seriesID": "revelation-comfort-and-hope",
            "translationSHA256": "d6c6064e8fab11ab012edd9535372a9f99b83cd5240b6014f5451795a9198f86",
            "cuvSHA256": "363afb38148f150b30fee727f4818faa821a0d17b4888c16be3e05bd462503bb",
            "review": review, "humanApproval": false, "entries": [[
                "pageID": pageID, "locale": "zh-Hans", "week": week, "status": status,
                "editionId": edition, "sourceIdentitySha256": sourceSHA ?? source,
                "releasePackageJsonSha256": releaseSHA ?? release, "path": path,
                "bytes": payload.count, "sha256": sha
            ]]
        ])
    }
    private func loader(manifest: Data, body: Data, bodyURL: URL? = nil,
                        status: Int = 200) -> WeeklyGuideRepository.Fetch {
        return { url, _, _ in
            if url.path == "/weekly-guides/manifest-v1.json" {
                return WeeklyGuideResponse(data: manifest, url: url, statusCode: status)
            }
            return WeeklyGuideResponse(data: body, url: bodyURL ?? url, statusCode: status)
        }
    }

    func testV2LanguageAndProvenanceAreBoundToTheSelectedSermon() async throws {
        let englishSHA = "3eb6cca50c898c8fcb82be73bcdce67deaad64267ad7041581e363aa39757708"
        let translationSHA = String(repeating: "d", count: 64)
        let korean = WeeklyGuideSelection(pageID: "test-sermon", locale: "ko", editionId: "test-edition",
                                          sourceIdentitySha256: source, releasePackageJsonSha256: release)
        let spanish = WeeklyGuideSelection(pageID: "test-sermon", locale: "es", editionId: "test-edition",
                                           sourceIdentitySha256: source, releasePackageJsonSha256: release)
        func makePayload(locale: String = "ko", review: String = "machine_translation_not_human_reviewed",
                         human: Any = false, sourceSHA: String? = nil, translation: String? = nil) throws -> Data {
            try JSONSerialization.data(withJSONObject: ["id": "test-sermon", "locale": locale, "week": 8,
                "title": "Title", "scripture": "Reference", "sections": [["id": "s", "title": "Section",
                "subtitle": "Subtitle", "symbol": "book", "body": "Synthetic"]], "review": review,
                "humanApproval": human, "sourceSHA256": sourceSHA ?? englishSHA,
                "translationSHA256": translation ?? translationSHA])
        }
        func entry(_ data: Data, locale: String = "ko") -> [String: Any] {
            let sha = WeeklyGuideRepository.sha256(data)
            return ["pageID": "test-sermon", "locale": locale, "week": 8, "status": "available",
                "editionId": "test-edition", "sourceIdentitySha256": source, "releasePackageJsonSha256": release,
                "path": "/weekly-guides/published/\(sha).json", "bytes": data.count, "sha256": sha,
                "review": "machine_translation_not_human_reviewed", "humanApproval": false,
                "sourceSHA256": englishSHA, "translationSHA256": translationSHA]
        }
        func load(_ entries: [[String: Any]], _ data: Data, selected: WeeklyGuideSelection? = nil) async throws -> WeeklyGuideRemoteResult {
            let manifest = try JSONSerialization.data(withJSONObject: ["schemaVersion": "tongxing-weekly-guide-manifest-v2",
                "seriesID": "revelation-comfort-and-hope", "entries": entries])
            return await WeeklyGuideRepository.loadRemote(selection: selected ?? korean, origin: origin) { url, _, _ in
                WeeklyGuideResponse(data: url.path.hasSuffix("manifest-v2.json") ? manifest : data, url: url, statusCode: 200)
            }
        }
        func check(_ expected: WeeklyGuideRemoteResult, _ entries: [[String: Any]], _ data: Data,
                   selected: WeeklyGuideSelection? = nil, message: String = "") async throws {
            let result = try await load(entries, data, selected: selected)
            XCTAssertEqual(result, expected, message)
        }
        let body = try makePayload()
        let validEntry = entry(body)
        guard case .available = try await load([validEntry], body) else { return XCTFail("Expected Korean guide") }
        try await check(.notDeclared, [validEntry], body, selected: spanish)
        try await check(.invalidDeclared, [validEntry, validEntry], body)
        for badBody in [try makePayload(locale: "es"), try makePayload(review: "human_reviewed"),
                        try makePayload(human: 0), try makePayload(sourceSHA: String(repeating: "0", count: 64)),
                        try makePayload(translation: String(repeating: "0", count: 64))] {
            try await check(.invalidDeclared, [entry(badBody)], badBody)
        }
        for (key, value) in [("sourceIdentitySha256", String(repeating: "0", count: 64)),
                             ("releasePackageJsonSha256", String(repeating: "0", count: 64)),
                             ("sourceSHA256", String(repeating: "0", count: 64)),
                             ("review", "human_reviewed"), ("path", "/weekly-guides/published/other.json")] {
            var bad = validEntry; bad[key] = value
            try await check(.invalidDeclared, [bad], body, message: key)
        }
        var numeric = validEntry; numeric["humanApproval"] = 0
        try await check(.invalidDeclared, [numeric], body)
        var revoked = validEntry; revoked["status"] = "revoked"
        try await check(.revoked, [revoked], body)
        let name = "WeeklyGuideV2.\(UUID().uuidString)"
        let defaults = try XCTUnwrap(UserDefaults(suiteName: name))
        defer { defaults.removePersistentDomain(forName: name) }
        let ledger = WeeklyGuideDenyLedger(defaults: defaults)
        ledger.apply(.revoked, selection: korean, origin: origin)
        XCTAssertTrue(ledger.isDenied(korean, origin: origin))
        XCTAssertFalse(ledger.isDenied(spanish, origin: origin))
        let bundled = Data("{\"guides\":[\(String(decoding: payload, as: UTF8.self))]}".utf8)
        XCTAssertNil(WeeklyGuideRepository.load(pageID: "test-sermon", locale: "ko", data: bundled))
        XCTAssertNil(WeeklyGuideRepository.load(pageID: "test-sermon", locale: "es", data: bundled))
    }

    func testRemoteGuideIsBoundToExactIdentityAndBytes() async throws {
        let data = payload
        let info = try manifest(payload: data)
        let result = await WeeklyGuideRepository.loadRemote(selection: selection, origin: origin,
                                                            fetch: loader(manifest: info, body: data))
        guard case .available(let guide) = result else { return XCTFail("Expected verified content") }
        XCTAssertEqual(guide.id, "test-sermon")
        XCTAssertEqual(guide.week, 8)
        XCTAssertEqual(guide.sections.first?.body, "Synthetic")
    }

    func testNetworkAndMissingManifestAreDistinctFromDeclaredCorruption() async throws {
        let data = payload
        let failed = await WeeklyGuideRepository.loadRemote(selection: selection, origin: origin) { _, _, _ in
            throw URLError(.notConnectedToInternet)
        }
        XCTAssertEqual(failed, .manifestUnavailable)
        let missing = try manifest(payload: data, pageID: "other-page")
        let undeclared = await WeeklyGuideRepository.loadRemote(selection: selection, origin: origin,
                                                               fetch: loader(manifest: missing, body: data))
        XCTAssertEqual(undeclared, .notDeclared)
        let wrongHash = try manifest(payload: data, hash: String(repeating: "0", count: 64))
        let hashResult = await WeeklyGuideRepository.loadRemote(selection: selection, origin: origin,
                                                                fetch: loader(manifest: wrongHash, body: data))
        XCTAssertEqual(hashResult, .invalidDeclared)
        let otherData = Data(String(decoding: data, as: UTF8.self).replacingOccurrences(of: "test-sermon", with: "other-page").utf8)
        let mismatch = try manifest(payload: otherData)
        let idResult = await WeeklyGuideRepository.loadRemote(selection: selection, origin: origin,
                                                              fetch: loader(manifest: mismatch, body: otherData))
        XCTAssertEqual(idResult, .invalidDeclared)
        let weekMismatch = try manifest(payload: data, week: 9)
        let weekResult = await WeeklyGuideRepository.loadRemote(selection: selection, origin: origin,
                                                                fetch: loader(manifest: weekMismatch, body: data))
        XCTAssertEqual(weekResult, .invalidDeclared)
        let badProvenance = try manifest(payload: data, review: "human_reviewed")
        let provenanceResult = await WeeklyGuideRepository.loadRemote(selection: selection, origin: origin,
                                                                      fetch: loader(manifest: badProvenance, body: data))
        XCTAssertEqual(provenanceResult, .invalidDeclared)
    }

    func testEachSourceIdentityMismatchIsRejected() async throws {
        let data = payload
        for info in [try manifest(payload: data, edition: "other-edition"),
                     try manifest(payload: data, sourceSHA: String(repeating: "c", count: 64)),
                     try manifest(payload: data, releaseSHA: String(repeating: "d", count: 64))] {
            let result = await WeeklyGuideRepository.loadRemote(selection: selection, origin: origin,
                                                                fetch: loader(manifest: info, body: data))
            XCTAssertEqual(result, .invalidDeclared)
        }
    }

    func testRevocationPersistsAcrossOfflineAndUndeclaredResults() async throws {
        let data = payload
        let info = try manifest(payload: data, status: "revoked")
        let result = await WeeklyGuideRepository.loadRemote(selection: selection, origin: origin,
                                                            fetch: loader(manifest: info, body: data))
        XCTAssertEqual(result, .revoked)
        let name = "WeeklyGuideRemoteTests.\(UUID().uuidString)"
        let defaults = try XCTUnwrap(UserDefaults(suiteName: name))
        defer { defaults.removePersistentDomain(forName: name) }
        let ledger = WeeklyGuideDenyLedger(defaults: defaults)
        ledger.apply(result, selection: selection, origin: origin)
        XCTAssertTrue(ledger.isDenied(selection, origin: origin))
        ledger.apply(.manifestUnavailable, selection: selection, origin: origin)
        ledger.apply(.notDeclared, selection: selection, origin: origin)
        XCTAssertTrue(WeeklyGuideDenyLedger(defaults: defaults).isDenied(selection, origin: origin))
        ledger.apply(.invalidDeclared, selection: selection, origin: origin)
        XCTAssertTrue(ledger.isDenied(selection, origin: origin))
        let guide = try JSONDecoder().decode(WeeklyGuide.self, from: data)
        ledger.apply(.available(guide), selection: selection, origin: origin)
        XCTAssertFalse(ledger.isDenied(selection, origin: origin))
    }

    func testResolutionDoesNotShowBundleBeforeNetworkAndPreservesDenialsOffline() throws {
        let guide = try JSONDecoder().decode(WeeklyGuide.self, from: payload)
        let name = "WeeklyGuideResolution.\(UUID().uuidString)"
        let defaults = try XCTUnwrap(UserDefaults(suiteName: name))
        defer { defaults.removePersistentDomain(forName: name) }
        let ledger = WeeklyGuideDenyLedger(defaults: defaults)
        // Until a request has settled for this exact selection, the view has no visible guide.
        XCTAssertNil(WeeklyGuideRepository.matchingRemote(guide, resultFor: nil, current: selection))
        XCTAssertEqual(WeeklyGuideRepository.resolvedGuide(.manifestUnavailable, selection: selection, origin: origin,
                                                          ledger: ledger) { guide }, guide)
        XCTAssertNil(WeeklyGuideRepository.resolvedGuide(.revoked, selection: selection, origin: origin,
                                                          ledger: ledger) { guide })
        var bundleRead = false
        XCTAssertNil(WeeklyGuideRepository.resolvedGuide(.manifestUnavailable, selection: selection, origin: origin,
                                                          ledger: ledger) { bundleRead = true; return guide })
        XCTAssertFalse(bundleRead)
        XCTAssertNil(WeeklyGuideRepository.resolvedGuide(.notDeclared, selection: selection, origin: origin,
                                                          ledger: ledger) { guide })
        XCTAssertEqual(WeeklyGuideRepository.resolvedGuide(.available(guide), selection: selection, origin: origin,
                                                           ledger: ledger) { nil }, guide)
        XCTAssertNil(WeeklyGuideRepository.resolvedGuide(.invalidDeclared, selection: selection, origin: origin,
                                                          ledger: ledger) { guide })
        XCTAssertNil(WeeklyGuideRepository.resolvedGuide(.manifestUnavailable, selection: selection, origin: origin,
                                                          ledger: WeeklyGuideDenyLedger(defaults: defaults)) { guide })
    }

    func testLegacyExactSourceTombstoneBlocksOfflineFallback() async throws {
        let origin = URL(string: "https://ai-for-god-sermon-audio.web.app")!
        let legacy = WeeklyGuideLegacyIdentity(
            sourceIdSHA256: "40982af8843db9416e7162e1e6a78138b1e6880dec2dad65a5ec85cba950bce2",
            sourceUrlSHA256: "a681ffe1ecd1c7dd1d8f18f15bf835d3663400aba7f828a3ec4755e02e986624",
            sourceMediaSHA256: "a9e91f52eb4c24845d0e31f5300a352e8d4b84b59231b1c4ae5112aceb907567",
            sourceStartSeconds: 1793, sourceEndSeconds: 4033)
        let selected = WeeklyGuideSelection(pageID: "2026-09-13-same_video-weekendlive-a9e91f52eb4c2484",
                                            locale: "zh-Hans", legacy: legacy)
        let fields: [String: Any] = ["sourceIdSHA256": legacy.sourceIdSHA256,
            "sourceUrlSHA256": legacy.sourceUrlSHA256, "sourceMediaSHA256": legacy.sourceMediaSHA256,
            "sourceStartSeconds": legacy.sourceStartSeconds, "sourceEndSeconds": legacy.sourceEndSeconds]
        var root = try XCTUnwrap(JSONSerialization.jsonObject(with: manifest(payload: payload)) as? [String: Any])
        var entry: [String: Any] = ["pageID": selected.pageID!, "locale": "zh-Hans", "week": 1,
                                    "status": "revoked", "legacy": fields]
        root["entries"] = [entry]
        let tombstone = try JSONSerialization.data(withJSONObject: root)
        let result = await WeeklyGuideRepository.loadRemote(selection: selected, origin: origin,
                                                             fetch: loader(manifest: tombstone, body: payload))
        XCTAssertEqual(result, .revoked)
        let name = "WeeklyGuideLegacy.\(UUID().uuidString)"
        let defaults = try XCTUnwrap(UserDefaults(suiteName: name))
        defer { defaults.removePersistentDomain(forName: name) }
        let ledger = WeeklyGuideDenyLedger(defaults: defaults)
        let guide = try JSONDecoder().decode(WeeklyGuide.self, from: payload)
        XCTAssertNil(WeeklyGuideRepository.resolvedGuide(result, selection: selected, origin: origin,
                                                         ledger: ledger) { guide })
        XCTAssertNil(WeeklyGuideRepository.resolvedGuide(.manifestUnavailable, selection: selected, origin: origin,
                                                         ledger: WeeklyGuideDenyLedger(defaults: defaults)) { guide })
        var wrongLegacy = fields
        wrongLegacy["sourceEndSeconds"] = 4034
        entry["legacy"] = wrongLegacy
        root["entries"] = [entry]
        let mismatch = try JSONSerialization.data(withJSONObject: root)
        let mismatchResult = await WeeklyGuideRepository.loadRemote(selection: selected, origin: origin,
            fetch: loader(manifest: mismatch, body: payload))
        XCTAssertEqual(mismatchResult, .invalidDeclared)
        entry["legacy"] = fields
        entry["status"] = "available"
        root["entries"] = [entry]
        let invalidAvailable = try JSONSerialization.data(withJSONObject: root)
        let availableResult = await WeeklyGuideRepository.loadRemote(selection: selected, origin: origin,
            fetch: loader(manifest: invalidAvailable, body: payload))
        XCTAssertEqual(availableResult, .invalidDeclared)
        let incomplete = WeeklyGuideSelection(pageID: "2026-09-13-live_archive-8JYwTq1xcBE", locale: "zh-Hans")
        var requested = false
        let incompleteResult = await WeeklyGuideRepository.loadRemote(selection: incomplete, origin: origin) { url, _, _ in
            requested = true
            return WeeklyGuideResponse(data: tombstone, url: url, statusCode: 200)
        }
        XCTAssertEqual(incompleteResult, .manifestUnavailable)
        XCTAssertFalse(requested)
    }

    func testV5TombstoneNeedsExactIdentityAndNeverFetchesBody() async throws {
        let data = payload
        let info = try manifest(payload: data, status: "revoked")
        var requestedResource = false
        let result = await WeeklyGuideRepository.loadRemote(selection: selection, origin: origin) { url, _, _ in
            if url.path != "/weekly-guides/manifest-v1.json" { requestedResource = true }
            return WeeklyGuideResponse(data: info, url: url, statusCode: 200)
        }
        XCTAssertEqual(result, .revoked)
        XCTAssertFalse(requestedResource)
        let mismatch = try manifest(payload: data, status: "revoked", sourceSHA: String(repeating: "c", count: 64))
        let changed = await WeeklyGuideRepository.loadRemote(selection: selection, origin: origin,
                                                             fetch: loader(manifest: mismatch, body: data))
        XCTAssertEqual(changed, .invalidDeclared)
    }

    func testCrossOriginAndUnsafePathsFailClosed() async throws {
        let data = payload
        let info = try manifest(payload: data)
        let result = await WeeklyGuideRepository.loadRemote(selection: selection, origin: origin,
            fetch: loader(manifest: info, body: data, bodyURL: URL(string: "https://elsewhere.example/file.json")!))
        XCTAssertEqual(result, .invalidDeclared)
        for path in ["//evil.example/file.json", "/weekly-guides/published/../file.json",
                     "/weekly-guides/published/%2e%2e/file.json", "/weekly-guides/published/a.json?x=1",
                     "/weekly-guides/published/a.json#fragment", "/weekly-guides/published/a\\b.json",
                     "/weekly-guides/published/a.json\n"] {
            XCTAssertNil(WeeklyGuideRepository.publishedURL(path, origin: origin), path)
        }
    }

    func testRedirectGuardRejectsEvenSameOriginBeforeFollowing() throws {
        let url = URL(string: "https://example.org/weekly-guides/manifest-v1.json")!
        let response = try XCTUnwrap(HTTPURLResponse(url: url, statusCode: 302, httpVersion: "HTTP/1.1", headerFields: nil))
        let task = URLSession.shared.dataTask(with: url)
        let delegate = GuideRedirectGuard()
        for destination in ["https://evil.example/redirect", "https://example.org/other-path", "https://example.org/weekly-guides/manifest-v1.json?altered=1"] {
            var called = false
            delegate.urlSession(URLSession.shared, task: task, willPerformHTTPRedirection: response,
                                newRequest: URLRequest(url: URL(string: destination)!)) { request in
                called = true
                XCTAssertNil(request)
            }
            XCTAssertTrue(called)
        }
    }

    func testRealURLSessionRejectsRedirectsBeforeFollowing() async throws {
        let original = URL(string: "https://example.org/weekly-guides/manifest-v1.json")!
        for target in ["https://elsewhere.example/secret", "https://example.org/different.json", "https://example.org/weekly-guides/manifest-v1.json?query=1"] {
            GuideTestURLProtocol.configure(origin: original, target: URL(string: target)!, oversized: false)
            let config = URLSessionConfiguration.ephemeral
            config.protocolClasses = [GuideTestURLProtocol.self]
            do {
                _ = try await WeeklyGuideRepository.fetchBounded(original, origin: origin, limit: 1024, configuration: config)
                XCTFail("A redirected response must not be accepted")
            } catch { }
            XCTAssertEqual(GuideTestURLProtocol.followedCount, 0, target)
        }
    }

    func testRealURLSessionEnforcesActualStreamLimit() async throws {
        let original = URL(string: "https://example.org/weekly-guides/manifest-v1.json")!
        GuideTestURLProtocol.configure(origin: original, target: original, oversized: true)
        let config = URLSessionConfiguration.ephemeral
        config.protocolClasses = [GuideTestURLProtocol.self]
        do {
            _ = try await WeeklyGuideRepository.fetchBounded(original, origin: origin, limit: 1024, configuration: config)
            XCTFail("Oversized response bytes must not be accepted")
        } catch { }
    }

    func testOversizedOrAmbiguousManifestFailsClosed() async throws {
        let data = payload
        let oversized = Data(repeating: 0x20, count: WeeklyGuideRepository.manifestLimit + 1)
        let large = await WeeklyGuideRepository.loadRemote(selection: selection, origin: origin,
                                                          fetch: loader(manifest: oversized, body: data))
        XCTAssertEqual(large, .manifestUnavailable)
        var object = try XCTUnwrap(JSONSerialization.jsonObject(with: manifest(payload: data)) as? [String: Any])
        let entries = try XCTUnwrap(object["entries"] as? [[String: Any]])
        object["entries"] = entries + entries
        let duplicate = try JSONSerialization.data(withJSONObject: object)
        let ambiguous = await WeeklyGuideRepository.loadRemote(selection: selection, origin: origin,
                                                               fetch: loader(manifest: duplicate, body: data))
        XCTAssertEqual(ambiguous, .invalidDeclared)
    }

    func testStaleResultIsNeverDisplayedAfterIdentityOrLocaleChanges() throws {
        let guide = try JSONDecoder().decode(WeeklyGuide.self, from: payload)
        XCTAssertEqual(WeeklyGuideRepository.matchingRemote(guide, resultFor: selection, current: selection), guide)
        var changed = selection
        changed.releasePackageJsonSha256 = String(repeating: "c", count: 64)
        XCTAssertNil(WeeklyGuideRepository.matchingRemote(guide, resultFor: selection, current: changed))
        changed = selection
        changed.editionId = "other-edition"
        XCTAssertNil(WeeklyGuideRepository.matchingRemote(guide, resultFor: selection, current: changed))
        XCTAssertNil(WeeklyGuideRepository.matchingRemote(guide, resultFor: selection,
            current: WeeklyGuideSelection(pageID: "next-sermon", locale: "zh-Hans")))
        XCTAssertNil(WeeklyGuideRepository.matchingRemote(guide, resultFor: selection,
            current: WeeklyGuideSelection(pageID: "test-sermon", locale: "ko")))
    }

    func testBundledFallbackRequiresSameIdentityOriginAndHash() throws {
        let wrapped = Data("{\"guides\":[\(String(decoding: payload, as: UTF8.self))]}".utf8)
        let bindings = try JSONSerialization.data(withJSONObject: ["https://example.org": [[
            "pageID":"test-sermon", "locale":"zh-Hans", "week":8, "editionId":"test-edition",
            "sourceIdentitySha256":source, "releasePackageJsonSha256":release
        ]]])
        let expectedSHA = WeeklyGuideRepository.sha256(wrapped)
        XCTAssertNotNil(WeeklyGuideRepository.loadBundled(selection: selection, origin: origin, data: wrapped,
                                                           bindingData: bindings, expectedSHA: expectedSHA))
        var changed = selection
        changed.releasePackageJsonSha256 = String(repeating: "c", count: 64)
        XCTAssertNil(WeeklyGuideRepository.loadBundled(selection: changed, origin: origin, data: wrapped,
                                                       bindingData: bindings, expectedSHA: expectedSHA))
        XCTAssertNil(WeeklyGuideRepository.loadBundled(selection: selection, origin: URL(string: "https://wrong.example")!,
                                                       data: wrapped, bindingData: bindings, expectedSHA: expectedSHA))
        XCTAssertNil(WeeklyGuideRepository.loadBundled(selection: selection, origin: origin, data: wrapped,
                                                       bindingData: bindings, expectedSHA: String(repeating: "0", count: 64)))
    }
    func testLegacyBundleRequiresSourceHashesAndExactWindow() throws {
        let wrapped = Data("{\"guides\":[\(String(decoding: payload, as: UTF8.self))]}".utf8)
        let bindings = try JSONSerialization.data(withJSONObject: ["https://example.org": [[
            "pageID":"test-sermon", "locale":"zh-Hans", "week":8,
            "sourceIdSHA256":"a", "sourceUrlSHA256":"b", "sourceMediaSHA256":"c",
            "sourceStartSeconds":100, "sourceEndSeconds":200
        ]]])
        let legacy = WeeklyGuideLegacyIdentity(sourceIdSHA256: "a", sourceUrlSHA256: "b",
                                               sourceMediaSHA256: "c", sourceStartSeconds: 100, sourceEndSeconds: 200)
        let chosen = WeeklyGuideSelection(pageID: "test-sermon", locale: "zh-Hans", legacy: legacy)
        let hash = WeeklyGuideRepository.sha256(wrapped)
        XCTAssertNotNil(WeeklyGuideRepository.loadBundled(selection: chosen, origin: origin, data: wrapped,
                                                           bindingData: bindings, expectedSHA: hash))
        let wrongWindow = WeeklyGuideLegacyIdentity(sourceIdSHA256: "a", sourceUrlSHA256: "b",
                                                    sourceMediaSHA256: "c", sourceStartSeconds: 101, sourceEndSeconds: 200)
        XCTAssertNil(WeeklyGuideRepository.loadBundled(selection: WeeklyGuideSelection(pageID: "test-sermon", locale: "zh-Hans", legacy: wrongWindow),
                                                       origin: origin, data: wrapped, bindingData: bindings, expectedSHA: hash))
        let wrongMedia = WeeklyGuideLegacyIdentity(sourceIdSHA256: "a", sourceUrlSHA256: "b",
                                                   sourceMediaSHA256: "changed", sourceStartSeconds: 100, sourceEndSeconds: 200)
        XCTAssertNil(WeeklyGuideRepository.loadBundled(selection: WeeklyGuideSelection(pageID: "test-sermon", locale: "zh-Hans", legacy: wrongMedia),
                                                       origin: origin, data: wrapped, bindingData: bindings, expectedSHA: hash))
    }

    func testVerifiedV4AliasAndEnvironmentSpecificBindings() {
        let dev = URL(string: "https://ai-for-god-sermon-audio-dev.web.app")!
        let production = URL(string: "https://ai-for-god-sermon-audio.web.app")!
        let aliasSelection = WeeklyGuideSelection(pageID: "resi-20261018-broadcast", locale: "zh-Hans",
            editionId: "resi-20261018-broadcast",
            sourceIdentitySha256: "5dc7deb518491cef0d0c98c8c21b5c7f8aebc3730c13042afc6427b640f75e2c",
            releasePackageJsonSha256: "3b0fbbfcd668b5379f837155080e6125e1ae3fb07d6b5bf4e3c46bee7861a4b5")
        XCTAssertTrue(WeeklyGuideRepository.hasApprovedBundleIdentity(selection: aliasSelection, origin: dev, week: 6))
        XCTAssertTrue(WeeklyGuideRepository.hasApprovedBundleIdentity(selection: aliasSelection, origin: production, week: 6))
        var changed = aliasSelection
        changed.releasePackageJsonSha256 = String(repeating: "0", count: 64)
        XCTAssertFalse(WeeklyGuideRepository.hasApprovedBundleIdentity(selection: changed, origin: dev, week: 6))
        let prodWeek4 = WeeklyGuideSelection(pageID: "resi-20261004-69ba7a66", locale: "zh-Hans",
            editionId: "resi-20261004-69ba7a66",
            sourceIdentitySha256: "dc9104063404d44866f762c76af7449e4f8d25ca6dd03f2312b256fb32f88502",
            releasePackageJsonSha256: "6d85d1c27c7cfcf676c9a77bdae55153389265e0056efe2e25ba2eec30e51063")
        XCTAssertTrue(WeeklyGuideRepository.hasApprovedBundleIdentity(selection: prodWeek4, origin: production, week: 4))
        XCTAssertFalse(WeeklyGuideRepository.hasApprovedBundleIdentity(selection: prodWeek4, origin: dev, week: 4))
    }

    func testLegacyFingerprintSuppliesMissingHashOnlyWhenBoundToWeek() throws {
        let sourceSHA = String(repeating: "a", count: 64)
        let trackSHA = String(repeating: "b", count: 64)
        let indexSHA = String(repeating: "c", count: 64)
        func week(topSHA: String? = nil, fpPage: String = "legacy-sermon",
                  fpStart: Double = 100, fpEnd: Double = 200,
                  fpTrack: String? = nil, algorithm: String = "spectral-landmarks-v1",
                  sourceURL: String = "https://example.org/source") throws -> SermonWeek {
            let fpObject: [String: Any] = [
                "schemaVersion": "sermon-audio-fingerprint-binding-v1", "pageId": fpPage,
                "sourceSha256": sourceSHA, "trackSha256": fpTrack ?? trackSHA,
                "sourceStartSeconds": fpStart, "sourceEndSeconds": fpEnd,
                "algorithmVersion": algorithm, "captureSeconds": 10,
                "indexSha256": indexSHA, "indexUrl": "/fingerprints/\(indexSHA.prefix(16))-landmarks.json"
            ]
            let fingerprint = try JSONDecoder().decode(PublishedFingerprintBinding.self,
                from: JSONSerialization.data(withJSONObject: fpObject))
            let track = SermonTrack(id: "track", label: "track", voiceLabel: "voice",
                audioUrl: "/audio/test.mp3", file: "test.mp3", sha256: trackSHA,
                durationSeconds: 100, cues: [], subtitleTiming: "source_video_aligned_candidate", scope: "full_candidate")
            return SermonWeek(id: "legacy-sermon", date: "2026-09-13", sourceId: "test-source",
                sourceUrl: sourceURL, title: "Synthetic", speaker: "Synthetic", scripture: "Example",
                tracks: [track], sourceSha256: topSHA, sourceStartSeconds: 100,
                sourceEndSeconds: 200, audioFingerprint: fingerprint)
        }
        let accepted = try week()
        let identity = try XCTUnwrap(WeeklyGuideRepository.legacyIdentity(week: accepted))
        XCTAssertEqual(identity.sourceMediaSHA256, sourceSHA)
        XCTAssertEqual(identity.sourceStartSeconds, 100)
        XCTAssertEqual(identity.sourceEndSeconds, 200)
        XCTAssertNil(WeeklyGuideRepository.legacyIdentity(week: try week(topSHA: String(repeating: "d", count: 64))))
        XCTAssertNil(WeeklyGuideRepository.legacyIdentity(week: try week(fpPage: "other-sermon")))
        XCTAssertNil(WeeklyGuideRepository.legacyIdentity(week: try week(fpStart: 101)))
        XCTAssertNil(WeeklyGuideRepository.legacyIdentity(week: try week(fpEnd: 199)))
        XCTAssertNil(WeeklyGuideRepository.legacyIdentity(week: try week(fpTrack: String(repeating: "d", count: 64))))
        XCTAssertNil(WeeklyGuideRepository.legacyIdentity(week: try week(algorithm: "unrecognized")))

        // Fingerprints have no source URL field; the Bundle binding must reject
        // a changed weekly source URL even if page/window/fingerprint match.
        let wrapped = Data("{\"guides\":[\(String(decoding: payload, as: UTF8.self).replacingOccurrences(of: "test-sermon", with: "legacy-sermon"))]}".utf8)
        let bindings = try JSONSerialization.data(withJSONObject: ["https://example.org": [[
            "pageID": "legacy-sermon", "locale": "zh-Hans", "week": 8,
            "sourceIdSHA256": identity.sourceIdSHA256, "sourceUrlSHA256": identity.sourceUrlSHA256,
            "sourceMediaSHA256": identity.sourceMediaSHA256, "sourceStartSeconds": 100, "sourceEndSeconds": 200
        ]]])
        let chosen = WeeklyGuideSelection(pageID: "legacy-sermon", locale: "zh-Hans", legacy: identity)
        let hash = WeeklyGuideRepository.sha256(wrapped)
        XCTAssertNotNil(WeeklyGuideRepository.loadBundled(selection: chosen, origin: origin, data: wrapped,
                                                           bindingData: bindings, expectedSHA: hash))
        let changedURL = try XCTUnwrap(WeeklyGuideRepository.legacyIdentity(week: week(sourceURL: "https://example.org/other")))
        let changed = WeeklyGuideSelection(pageID: "legacy-sermon", locale: "zh-Hans", legacy: changedURL)
        XCTAssertNil(WeeklyGuideRepository.loadBundled(selection: changed, origin: origin, data: wrapped,
                                                       bindingData: bindings, expectedSHA: hash))
    }

}

// URLProtocol injects deterministic responses into a real URLSession; it never
// contacts a server and counts any incorrectly followed redirect.
private final class GuideTestURLProtocol: URLProtocol {
    private static let lock = NSLock()
    private static var firstURL: URL!
    private static var redirectURL: URL!
    private static var oversized = false
    private static var follows = 0
    static var followedCount: Int { lock.lock(); defer { lock.unlock() }; return follows }
    static func configure(origin: URL, target: URL, oversized: Bool) {
        lock.lock(); defer { lock.unlock() }
        firstURL = origin; redirectURL = target; self.oversized = oversized; follows = 0
    }
    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }
    override func startLoading() {
        Self.lock.lock()
        let first = Self.firstURL
        let target = Self.redirectURL!
        let large = Self.oversized
        if request.url != first { Self.follows += 1 }
        Self.lock.unlock()
        guard let url = request.url else { client?.urlProtocol(self, didFailWithError: URLError(.badURL)); return }
        if url != first {
            client?.urlProtocol(self, didFailWithError: URLError(.badServerResponse))
        } else if large {
            let response = HTTPURLResponse(url: url, statusCode: 200, httpVersion: "HTTP/1.1", headerFields: nil)!
            client?.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
            client?.urlProtocol(self, didLoad: Data(repeating: 65, count: 1025))
            client?.urlProtocolDidFinishLoading(self)
        } else {
            let response = HTTPURLResponse(url: url, statusCode: 302, httpVersion: "HTTP/1.1",
                                           headerFields: ["Location": target.absoluteString])!
            client?.urlProtocol(self, wasRedirectedTo: URLRequest(url: target), redirectResponse: response)
            client?.urlProtocolDidFinishLoading(self)
        }
    }
    override func stopLoading() { }

}

// Source-bound page 83 fixture exercises both the text and structured content pins.
extension WeeklyGuideRemoteTests {
    func testProtectedChineseRevisionsAndSafeFallback() async throws {
        let protectedOrigin = URL(string: "https://ai-for-god-sermon-audio-dev.web.app")!
        let selected = WeeklyGuideSelection(pageID: "resi-20261011-54475d42", locale: "zh-Hans",
            editionId: "resi-20261011-54475d42",
            sourceIdentitySha256: "d1734702cf39394a3f283392043d0d33ed127302df393dc16b16d737ef320ec4",
            releasePackageJsonSha256: "2503ca70abb2372d513bd9a14603d42b5aac6401d5cc0e635dbc988ec8c84e51")
        let revision = "df50f608d7a802052bdbf949aa3fb0988432c331a57a10c128160e9eb77c62de"
        let sectionData = Data(#"{"id":"page-83","title":"七号（启示录 8–9 章）与十灾（出埃及记）","subtitle":"原手册印刷页 81","symbol":"doc.text","body":"七号（启示录 8–9 章）与十灾（出埃及记）\n启示录最早的听众会立刻联想到神降在埃及的灾，那些灾使神的百姓从被掳中得释放。正如埃及的法老硬着心不悔改，敌挡神的人也\"……仍旧不悔改自己手所做的……\"（启示录 9:20）。\n\n七号：第一号：雹子、火与血\n十灾：第六灾和第七灾：疮与雹\n\n七号：第二号：海变成血\n十灾：第一灾：水变成血\n\n七号：第三号：水变苦\n十灾：第一灾：淡水受击打\n\n七号：第四号：日、月、星变黑\n十灾：第九灾：黑暗\n\n七号：第五号：蝗虫被释放\n十灾：第八灾：蝗虫\n\n七号：第六号：人类大规模死亡\n十灾：第十灾：长子之死\n\n创造（创世记 1 章）与\"反创造\"（启示录 8 章）\n随着七号的审判，我们看见三分之一的受造界在向后崩塌。\n\n创造之日\n第一日：光\n第二日：天空／水分开\n第三日：地与植物\n第四日：日、月、星\n\n“反创造”之号\n第一号：地和植物被烧\n第二号：海受击打\n第三号：淡水变毒\n第四号：黑暗\n\n创造的次序：光 → 水 → 地\n“反创造”的次序：地 → 水 → 光","blocks":[{"type":"paragraph","text":"七号（启示录 8–9 章）与十灾（出埃及记）\n启示录最早的听众会立刻联想到神降在埃及的灾，那些灾使神的百姓从被掳中得释放。正如埃及的法老硬着心不悔改，敌挡神的人也\"……仍旧不悔改自己手所做的……\"（启示录 9:20）。"},{"type":"table","title":"","columns":["七号","十灾"],"rows":[["第一号：雹子、火与血","第六灾和第七灾：疮与雹"],["第二号：海变成血","第一灾：水变成血"],["第三号：水变苦","第一灾：淡水受击打"],["第四号：日、月、星变黑","第九灾：黑暗"],["第五号：蝗虫被释放","第八灾：蝗虫"],["第六号：人类大规模死亡","第十灾：长子之死"]]},{"type":"paragraph","text":"创造（创世记 1 章）与\"反创造\"（启示录 8 章）\n随着七号的审判，我们看见三分之一的受造界在向后崩塌。"},{"type":"list","title":"创造之日","items":["第一日：光","第二日：天空／水分开","第三日：地与植物","第四日：日、月、星"]},{"type":"list","title":"“反创造”之号","items":["第一号：地和植物被烧","第二号：海受击打","第三号：淡水变毒","第四号：黑暗"]},{"type":"flow","title":"创造的次序","items":["光","水","地"]},{"type":"flow","title":"“反创造”的次序","items":["地","水","光"]}]}"#.utf8)
        let section = try XCTUnwrap(JSONSerialization.jsonObject(with: sectionData) as? [String: Any])
        let payloadObject: [String: Any] = ["id": selected.pageID!, "week": 5, "title": "test", "scripture": "test",
                                          "sections": [section], "richRevisionSHA256": revision]
        func run(_ object: [String: Any], entryRevision: String?, status: String = "available", source: String? = nil, week: Int = 5) async throws -> WeeklyGuideRemoteResult {
            let bytes = try JSONSerialization.data(withJSONObject: object)
            var root = try XCTUnwrap(JSONSerialization.jsonObject(with: manifest(payload: bytes, pageID: selected.pageID!, week: week,
                status: status, edition: selected.editionId!, sourceSHA: source ?? selected.sourceIdentitySha256!,
                releaseSHA: selected.releasePackageJsonSha256!)) as? [String: Any])
            var entries = try XCTUnwrap(root["entries"] as? [[String: Any]])
            entries[0]["richRevisionSHA256"] = entryRevision
            root["entries"] = entries
            let info = try JSONSerialization.data(withJSONObject: root)
            return await WeeklyGuideRepository.loadRemote(selection: selected, origin: protectedOrigin, fetch: loader(manifest: info, body: bytes))
        }
        let valid = try await run(payloadObject, entryRevision: revision)
        guard case .available(let bundledGuide) = valid else { return XCTFail("verified revision rejected: \(valid)") }
        let old = try await run(payloadObject, entryRevision: nil)
        XCTAssertEqual(old, .outdatedRevision(5))
        let suite = "guide-protection-\(UUID().uuidString)"
        let defaults = try XCTUnwrap(UserDefaults(suiteName: suite))
        defer { defaults.removePersistentDomain(forName: suite) }
        let ledger = WeeklyGuideDenyLedger(defaults: defaults)
        XCTAssertEqual(WeeklyGuideRepository.resolvedGuide(old, selection: selected, origin: protectedOrigin, ledger: ledger, bundled: { bundledGuide }), bundledGuide)
        var wrong = payloadObject
        wrong["richRevisionSHA256"] = String(repeating: "0", count: 64)
        let wrongRevision = try await run(wrong, entryRevision: revision)
        XCTAssertEqual(wrongRevision, .outdatedRevision(5))
        var badSection = section
        badSection["body"] = "incorrect"
        wrong = payloadObject; wrong["sections"] = [badSection]
        let wrongBody = try await run(wrong, entryRevision: revision)
        XCTAssertEqual(wrongBody, .outdatedRevision(5))
        badSection = section; badSection["blocks"] = [["type": "paragraph", "text": "incorrect"]]
        wrong["sections"] = [badSection]
        let wrongBlocks = try await run(wrong, entryRevision: revision)
        XCTAssertEqual(wrongBlocks, .outdatedRevision(5))
        let revoked = try await run(payloadObject, entryRevision: nil, status: "revoked")
        XCTAssertEqual(revoked, .revoked)
        XCTAssertNil(WeeklyGuideRepository.resolvedGuide(revoked, selection: selected, origin: protectedOrigin, ledger: ledger, bundled: { bundledGuide }))
        XCTAssertNil(WeeklyGuideRepository.resolvedGuide(old, selection: selected, origin: protectedOrigin, ledger: ledger, bundled: { bundledGuide }))
        let mismatch = try await run(payloadObject, entryRevision: nil, source: String(repeating: "e", count: 64))
        XCTAssertEqual(mismatch, .invalidDeclared)
        var wrongWeek = payloadObject; wrongWeek["week"] = 8
        let disguised = try await run(wrongWeek, entryRevision: nil, week: 8)
        XCTAssertEqual(disguised, .invalidDeclared)
        var weekNine = payloadObject; weekNine["week"] = 9; weekNine["id"] = selection.pageID!
        let ninthData = try JSONSerialization.data(withJSONObject: weekNine)
        let ninthManifest = try manifest(payload: ninthData, week: 9)
        let oldNinth = await WeeklyGuideRepository.loadRemote(selection: selection, origin: origin,
            fetch: loader(manifest: ninthManifest, body: ninthData))
        XCTAssertEqual(oldNinth, .outdatedRevision(9))
        let ninth = WeeklyGuideRepository.resolvedGuide(oldNinth, selection: selection, origin: origin, ledger: ledger, bundled: { nil })
        XCTAssertNil(ninth)
    }
}
