import Foundation
import Testing
@testable import TongxingCore

struct SharedCatalogTargetTests {
    @Test func identicalWebAndNativeCatalogTargets() throws {
        let url = try #require(Bundle.module.url(forResource: "shared-catalog-targets", withExtension: "json", subdirectory: "Fixtures"))
        let matrix = try #require(JSONSerialization.jsonObject(with: Data(contentsOf: url)) as? [String: Any])
        #expect(matrix["schemaVersion"] as? String == "sermon-shared-catalog-target-fixtures-v1")
        #expect(matrix["scope"] as? String == "synthetic_decoder_tests_not_production_approval")
        let cases = try #require(matrix["cases"] as? [[String: Any]])
        #expect(cases.count == 31)
        for row in cases {
            let id = try #require(row["id"] as? String)
            let expected = try #require(row["expected"] as? String)
            let target = try #require(row["target"] as? [String: Any])
            var accepted = false
            do {
                let decoded = try JSONDecoder().decode(PageTarget.self, from: JSONSerialization.data(withJSONObject: target))
                try decoded.validate(pageID: try #require(row["pageId"] as? String),
                                     locale: try #require(row["locale"] as? String),
                                     catalogSchemaVersion: MultilingualCatalog.dualScriptSchemaVersion)
                accepted = true
            } catch { }
            #expect(["accept", "reject"].contains(expected), "fixture: \(id)")
            #expect(accepted == (expected == "accept"), "fixture: \(id)")
        }
    }
}
