import Foundation
import Testing
@testable import TongxingCore

struct WeeklyAnnouncementTests {
    let hash = String(repeating: "a", count: 64)
    func catalog(hash: String? = nil, sourceHash: String? = nil) throws -> MultilingualCatalog {
        try MultilingualCatalog.decode(JSONSerialization.data(withJSONObject: [
            "schemaVersion": MultilingualCatalog.dualScriptSchemaVersion,
            "generatedAt": "2026-10-07T00:00:00Z", "defaultPageId": "week-1",
            "pages": [["id": "week-1", "title": "Test sermon", "date": "2026-10-04", "sourceLocale": "en",
                "sourceIdentitySha256": sourceHash ?? self.hash, "defaultTargetLocale": "zh-Hans",
                "targets": ["zh-Hans": ["releasePackageUrl": "/releases-v2/week-1/zh-Hans.json",
                    "releasePackageJsonSha256": hash ?? self.hash, "contentStatus": "human_reviewed",
                    "audioStatus": "unavailable", "capabilities": ["text"]]]]]]))
    }
    func announcement(locale: String = "zh-Hans", url: String = "/posters/week-1/zh-Hans.png", id: String = "week-1") -> WeeklyAnnouncement {
        .init(id: id, pageID: "week-1", locale: locale, releaseSHA256: hash,
            sourceIdentitySHA256: hash, title: "耶稣审判并保守", publishedAt: "2026-10-07T00:00:00Z",
            poster: .init(url: url, sha256: hash, bytes: 12, width: 1080, height: 1920))
    }
    @Test func sidecarMatchesExactReleaseLanguageAndSource() throws {
        let value = announcement()
        let sidecar = try WeeklyAnnouncementCatalog.decode(JSONEncoder().encode(WeeklyAnnouncementCatalog(announcements: [value])))
        #expect(sidecar.matchedAnnouncement(pageID: "week-1", locale: "zh-Hans", catalog: try catalog()) == value)
        #expect(sidecar.matchedAnnouncement(pageID: "week-1", locale: "ko", catalog: try catalog()) == nil)
        #expect(throws: WeeklyAnnouncementError.staleRelease) { try value.matchedPage(in: catalog(hash: String(repeating: "b", count: 64))) }
        #expect(throws: WeeklyAnnouncementError.staleRelease) { try announcement(locale: "es").matchedPage(in: catalog()) }
        #expect(throws: WeeklyAnnouncementError.staleRelease) { try value.matchedPage(in: catalog(sourceHash: String(repeating: "c", count: 64))) }
    }
    @Test func changedArtworkDoesNotReannounceAndDuplicateBindingFails() throws {
        #expect(announcement().deduplicationKey == announcement(id: "new-art").deduplicationKey)
        #expect(throws: WeeklyAnnouncementError.invalidBinding) {
            try WeeklyAnnouncementCatalog.decode(JSONEncoder().encode(WeeklyAnnouncementCatalog(announcements: [announcement(), announcement(id: "new-art")])))
        }
    }
    @Test func rejectsForeignTraversalQueriesAndHugeImages() throws {
        for url in ["https://foreign.test/a.png", "//foreign.test/a.png", "/posters/../a.png", "/posters/a.png?x=1", "/posters/%2e/a.png", "/posters/a.svg"] {
            #expect(throws: WeeklyAnnouncementError.invalidBinding) { try announcement(url: url).validate() }
        }
        #expect(throws: WeeklyAnnouncementError.invalidBinding) {
            try WeeklyPoster(url: "/posters/a.png", sha256: hash, bytes: WeeklyPoster.maximumBytes + 1, width: 1, height: 1).validate()
        }
        #expect(throws: WeeklyAnnouncementError.invalidBinding) {
            try WeeklyPoster(url: "/posters/a.png", sha256: hash, bytes: 10, width: 8192, height: 8192).validate()
        }
    }
}
