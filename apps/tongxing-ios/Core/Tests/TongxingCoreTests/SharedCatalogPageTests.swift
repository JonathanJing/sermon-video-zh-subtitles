import Foundation
import Testing
@testable import TongxingCore

struct SharedCatalogPageTests {
    @Test func identicalWebAndNativeCatalogHeadersAndPages() throws {
        let url = try #require(Bundle.module.url(forResource: "shared-catalog-pages", withExtension: "json", subdirectory: "Fixtures"))
        let matrix = try #require(JSONSerialization.jsonObject(with: Data(contentsOf: url)) as? [String: Any])
        #expect(matrix["schemaVersion"] as? String == "sermon-shared-catalog-page-fixtures-v1")
        #expect(matrix["scope"] as? String == "synthetic_decoder_tests_not_production_approval")
        let cases = try #require(matrix["cases"] as? [[String: Any]])
        #expect(cases.count == 33)
        for row in cases {
            let id = try #require(row["id"] as? String)
            let expected = try #require(row["expected"] as? String)
            let target = try #require(row["catalog"] as? [String: Any])
            var accepted = false
            do {
                _ = try MultilingualCatalog.decode(JSONSerialization.data(withJSONObject: target))
                accepted = true
            } catch { }
            #expect(["accept", "reject"].contains(expected), "fixture: \(id)")
            #expect(accepted == (expected == "accept"), "fixture: \(id)")
        }
    }
}
