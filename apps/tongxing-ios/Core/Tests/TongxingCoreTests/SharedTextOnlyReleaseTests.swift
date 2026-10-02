import Foundation
import Testing
@testable import TongxingCore

struct SharedTextOnlyReleaseTests {
    @Test func sharedTextOnlyAdmissionAndReadablePage() throws {
        let url = try #require(Bundle.module.url(forResource: "shared-text-only-releases", withExtension: "json", subdirectory: "Fixtures"))
        let matrix = try #require(JSONSerialization.jsonObject(with: Data(contentsOf: url)) as? [String: Any])
        #expect(matrix["schemaVersion"] as? String == "sermon-shared-text-only-release-fixtures-v1")
        #expect(matrix["scope"] as? String == "synthetic_decoder_tests_not_production_approval")
        let cases = try #require(matrix["cases"] as? [[String: Any]])
        #expect(cases.count == 27)
        for row in cases {
            let id = try #require(row["id"] as? String)
            let expected = try #require(row["nativeAdmission"] as? String)
            let release = try #require(row["release"] as? [String: Any])
            let data = try JSONSerialization.data(withJSONObject: release)
            var package: TargetLanguageReleasePackage?
            do { package = try TargetLanguageReleasePackage.decode(data) } catch { }
            #expect(["accept", "reject"].contains(expected), "fixture: \(id)")
            #expect((package != nil) == (expected == "accept"), "fixture: \(id)")
            if let package, package.audioStatus == "unavailable" {
                #expect(package.audioLocale == nil)
                #expect(!package.assets.contains { $0.role == .audio })
                let page = try package.pageURL(relativeTo: URL(string: "https://synthetic.example.test/")!)
                #expect(page.host == "synthetic.example.test")
                #expect(page.path == "/pages/\(package.pageId)/\(package.targetLocale)/index.html")
                #expect(row["webPlaybackAdmission"] as? String == "reject")
            }
        }
    }
}
