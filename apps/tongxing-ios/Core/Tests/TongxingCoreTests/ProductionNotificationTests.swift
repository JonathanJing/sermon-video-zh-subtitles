import Foundation
import Testing
@testable import TongxingCore

struct ProductionNotificationTests {
    private let hash = String(repeating: "a", count: 64)

    private func catalog(hash: String? = nil) throws -> MultilingualCatalog {
        try MultilingualCatalog.decode(JSONSerialization.data(withJSONObject: [
            "schemaVersion": MultilingualCatalog.dualScriptSchemaVersion,
            "generatedAt": "2026-10-21T00:00:00Z", "defaultPageId": "published-page",
            "pages": [["id": "published-page", "title": "Published", "date": "2026-10-21",
                       "sourceLocale": "en", "sourceIdentitySha256": self.hash,
                       "defaultTargetLocale": "zh-Hans",
                       "targets": ["zh-Hans": ["releasePackageUrl": "/releases-v2/published-page/zh-Hans.json",
                                               "releasePackageJsonSha256": hash ?? self.hash,
                                               "contentStatus": "human_reviewed", "audioStatus": "unavailable",
                                               "capabilities": ["text"]]]]]
        ]))
    }

    @Test func acceptsOnlyCurrentPublishedProductionBinding() throws {
        let notice = ProductionNotification(pageID: "published-page", locale: "zh-Hans", releaseSHA256: hash)
        #expect(try notice.matchedPage(in: catalog(), subscriptionLocale: "zh-Hans",
                                       enabled: true, productionOrigin: true).id == "published-page")
        #expect(try JSONDecoder().decode(ProductionNotification.self, from: JSONEncoder().encode(notice)) == notice)
        #expect(throws: ProductionNotificationError.notSubscribed) {
            try notice.matchedPage(in: catalog(), subscriptionLocale: "ko", enabled: true, productionOrigin: true)
        }
        #expect(throws: ProductionNotificationError.notSubscribed) {
            try notice.matchedPage(in: catalog(), subscriptionLocale: "zh-Hans", enabled: false, productionOrigin: true)
        }
        #expect(throws: ProductionNotificationError.notSubscribed) {
            try notice.matchedPage(in: catalog(), subscriptionLocale: "zh-Hans", enabled: true, productionOrigin: false)
        }
        #expect(throws: ProductionNotificationError.staleRelease) {
            try notice.matchedPage(in: catalog(hash: String(repeating: "b", count: 64)),
                                   subscriptionLocale: "zh-Hans", enabled: true, productionOrigin: true)
        }
    }

    @Test func rejectsForeignOrMalformedPayload() throws {
        let notice = ProductionNotification(pageID: "published-page", locale: "zh-Hans", releaseSHA256: hash)
        var json = try #require(JSONSerialization.jsonObject(with: JSONEncoder().encode(notice)) as? [String: Any])
        json["environment"] = "beta-dev"
        let foreign = try JSONDecoder().decode(ProductionNotification.self, from: JSONSerialization.data(withJSONObject: json))
        #expect(throws: ProductionNotificationError.invalidBinding) { try foreign.validate() }
        #expect(throws: ProductionNotificationError.invalidBinding) {
            try ProductionNotification(pageID: "../escape", locale: "zh-Hans", releaseSHA256: hash).validate()
        }
    }
}
