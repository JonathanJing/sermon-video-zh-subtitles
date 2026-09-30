import Foundation
import Testing
@testable import TongxingCore

struct SharedReleaseContractTests {
    @Test func identicalWebAndNativeReleaseFixtures() throws {
        let url = try #require(Bundle.module.url(forResource: "shared-release-contracts", withExtension: "json", subdirectory: "Fixtures"))
        let matrix = try #require(JSONSerialization.jsonObject(with: Data(contentsOf: url)) as? [String: Any])
        #expect(matrix["schemaVersion"] as? String == "sermon-shared-release-contract-fixtures-v1")
        #expect(matrix["scope"] as? String == "synthetic_decoder_tests_not_production_approval")
        let cases = try #require(matrix["cases"] as? [[String: Any]])
        #expect(cases.count == 18)
        for row in cases {
            let id = try #require(row["id"] as? String)
            let expected = try #require(row["expected"] as? String)
            let release = try #require(row["release"] as? [String: Any])
            let data = try JSONSerialization.data(withJSONObject: release)
            var accepted = false
            do {
                let package = try TargetLanguageReleasePackage.decode(data)
                accepted = true
                #expect(package.deviceAcceptance.status == "not_run", "fixture: \(id)")
                #expect(package.venueAcceptance.status == "not_run", "fixture: \(id)")
            } catch { }
            #expect(["accept", "reject"].contains(expected), "fixture: \(id)")
            #expect(accepted == (expected == "accept"), "fixture: \(id)")
        }
    }
}
