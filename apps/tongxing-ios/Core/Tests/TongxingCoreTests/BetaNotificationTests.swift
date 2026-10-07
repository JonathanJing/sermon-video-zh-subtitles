import Foundation
import Testing
@testable import TongxingCore

struct BetaNotificationTests {
    private let hash = String(repeating: "a", count: 64)

    private func catalog(locale: String = "zh-Hans", hash: String? = nil) throws -> MultilingualCatalog {
        try MultilingualCatalog.decode(JSONSerialization.data(withJSONObject: [
            "schemaVersion": MultilingualCatalog.dualScriptSchemaVersion,
            "generatedAt": "2026-10-03T00:00:00Z", "defaultPageId": "beta-test",
            "pages": [["id": "beta-test", "title": "Synthetic test", "date": "2026-10-03", "sourceLocale": "en",
                       "sourceIdentitySha256": self.hash, "defaultTargetLocale": locale,
                       "targets": [locale: ["releasePackageUrl": "/releases-v2/beta-test/\(locale).json",
                                            "releasePackageJsonSha256": hash ?? self.hash,
                                            "contentStatus": "human_reviewed", "audioStatus": "unavailable", "capabilities": ["text"]]]]]
        ]))
    }

    @Test func admittedReleaseUsesExactContentLanguageAndVersion() throws {
        let value = BetaNotification(pageID: "beta-test", locale: "es", releaseSHA256: hash)
        let page = try value.matchedPage(in: catalog(locale: "es"), subscriptionLocale: "es", enabled: true, betaChannel: true)
        #expect(page.id == "beta-test")
        #expect(value.title.contains("Prueba Beta"))
        #expect(value.body(date: page.date, audioAvailable: false).contains("El audio no está disponible"))
    }

    @Test func rejectsOptOutWrongLanguageAndProductionChannel() throws {
        let value = BetaNotification(pageID: "beta-test", locale: "zh-Hans", releaseSHA256: hash)
        let catalog = try catalog()
        #expect(throws: BetaNotificationError.notSubscribed) {
            try value.matchedPage(in: catalog, subscriptionLocale: "zh-Hans", enabled: false, betaChannel: true)
        }
        #expect(throws: BetaNotificationError.notSubscribed) {
            try value.matchedPage(in: catalog, subscriptionLocale: "ko", enabled: true, betaChannel: true)
        }
        #expect(throws: BetaNotificationError.notSubscribed) {
            try value.matchedPage(in: catalog, subscriptionLocale: "zh-Hans", enabled: true, betaChannel: false)
        }
    }

    @Test func rejectsStaleHashMissingPageAndForeignEnvironment() throws {
        let value = BetaNotification(pageID: "beta-test", locale: "zh-Hans", releaseSHA256: hash)
        let changed = try catalog(hash: String(repeating: "b", count: 64))
        #expect(throws: BetaNotificationError.staleRelease) {
            try value.matchedPage(in: changed, subscriptionLocale: "zh-Hans", enabled: true, betaChannel: true)
        }
        let absent = BetaNotification(pageID: "removed-page", locale: "zh-Hans", releaseSHA256: hash)
        let catalog = try catalog()
        #expect(throws: BetaNotificationError.staleRelease) {
            try absent.matchedPage(in: catalog, subscriptionLocale: "zh-Hans", enabled: true, betaChannel: true)
        }
        let data = try JSONEncoder().encode(value)
        var json = try #require(JSONSerialization.jsonObject(with: data) as? [String: Any])
        json["environment"] = "production"
        let foreign = try JSONDecoder().decode(BetaNotification.self, from: JSONSerialization.data(withJSONObject: json))
        #expect(throws: BetaNotificationError.invalidBinding) { try foreign.validate() }
    }

    @Test func deduplicationSeparatesVersionLanguageAndRecipient() {
        let recipient = UUID()
        let value = BetaNotification(pageID: "beta-test", locale: "zh-Hans", releaseSHA256: hash)
        #expect(value.deduplicationKey(recipient: recipient) == value.deduplicationKey(recipient: recipient))
        #expect(value.deduplicationKey(recipient: recipient) != value.deduplicationKey(recipient: UUID()))
        #expect(value.deduplicationKey(recipient: recipient) != BetaNotification(pageID: "beta-test", locale: "ko", releaseSHA256: hash).deduplicationKey(recipient: recipient))
        #expect(value.deduplicationKey(recipient: recipient) != BetaNotification(pageID: "beta-test", locale: "zh-Hans", releaseSHA256: String(repeating: "b", count: 64)).deduplicationKey(recipient: recipient))
    }

    @Test func localizedTextOnlyCopyAndMalformedBindings() throws {
        for locale in ["en", "zh-Hans", "es", "ko", "vi"] {
            let value = BetaNotification(pageID: "beta-test", locale: locale, releaseSHA256: hash)
            try value.validate()
            #expect(!value.title.isEmpty)
            #expect(value.body(date: "2026-10-03", audioAvailable: false) != value.body(date: "2026-10-03", audioAvailable: true))
            #expect(try JSONDecoder().decode(BetaNotification.self, from: JSONEncoder().encode(value)) == value)
        }
        #expect(throws: BetaNotificationError.invalidBinding) { try BetaNotification(pageID: "../escape", locale: "es", releaseSHA256: hash).validate() }
        #expect(throws: BetaNotificationError.invalidBinding) { try BetaNotification(pageID: "beta-test", locale: "fr", releaseSHA256: hash).validate() }
    }
}
