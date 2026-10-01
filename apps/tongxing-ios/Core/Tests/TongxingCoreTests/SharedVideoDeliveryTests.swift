import Foundation
import Testing
@testable import TongxingCore

struct SharedVideoDeliveryTests {
    @Test func sharedVideoDeliveryCatalogAdmission() throws {
        let url = try #require(Bundle.module.url(
            forResource: "shared-video-delivery", withExtension: "json", subdirectory: "Fixtures"))
        let matrix = try #require(JSONSerialization.jsonObject(with: Data(contentsOf: url)) as? [String: Any])
        #expect(matrix["schemaVersion"] as? String == "sermon-shared-video-delivery-fixtures-v1")
        #expect(matrix["scope"] as? String == "synthetic_decoder_tests_not_production_approval")
        let cases = try #require(matrix["cases"] as? [[String: Any]])
        #expect(cases.count == 61)
        let ids = try cases.map { try #require($0["id"] as? String) }
        #expect(Set(ids).count == cases.count)

        for row in cases {
            let id = try #require(row["id"] as? String)
            let expected = try #require(row["swiftAcceptance"] as? String)
            #expect(["accept", "reject"].contains(expected), "fixture: \(id)")
            let payload = try #require(row["catalog"] as? [String: Any])
            let data = try JSONSerialization.data(withJSONObject: payload)
            var decoded: MultilingualCatalog?
            var failure = "none"
            do { decoded = try MultilingualCatalog.decode(data) }
            catch { failure = String(describing: error) }
            #expect((decoded != nil) == (expected == "accept"), "fixture: \(id); decode error: \(failure)")

            // Admission must retain the known page/target identities. It does
            // not establish that ignored video metadata is safe or playable.
            if let decoded {
                let pages = try #require(payload["pages"] as? [[String: Any]])
                let page = try #require(pages.first)
                let targets = try #require(page["targets"] as? [String: Any])
                #expect(decoded.pages.count == 1, "fixture: \(id)")
                #expect(decoded.defaultPage.id == page["id"] as? String, "fixture: \(id)")
                #expect(decoded.defaultPage.sourceMediaSha256 == page["sourceMediaSha256"] as? String, "fixture: \(id)")
                #expect(decoded.defaultPage.defaultTargetLocale == page["defaultTargetLocale"] as? String, "fixture: \(id)")
                #expect(Set(decoded.defaultPage.targets.keys) == Set(targets.keys), "fixture: \(id)")
            }
        }
    }
}
