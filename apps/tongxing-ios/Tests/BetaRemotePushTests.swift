import Foundation
import XCTest
@testable import Tongxing

@MainActor
final class BetaRemotePushTests: XCTestCase {
    private func profile(_ environment: String?) throws -> Data {
        var entitlements: [String: String] = [:]
        if let environment { entitlements["aps-environment"] = environment }
        let xml = try PropertyListSerialization.data(fromPropertyList: ["Entitlements": entitlements], format: .xml, options: 0)
        return Data([0, 255, 1]) + xml + Data([3, 255])
    }

    func testActualProfileControlsEnvironmentAndRejectsDistributionMismatch() throws {
        XCTAssertEqual(BetaRemotePush.environment(profile: try profile("development"), productionDistribution: false), "sandbox")
        XCTAssertEqual(BetaRemotePush.environment(profile: try profile("production"), productionDistribution: false), "production")
        XCTAssertEqual(BetaRemotePush.environment(profile: try profile("production"), productionDistribution: true), "production")
        XCTAssertNil(BetaRemotePush.environment(profile: try profile("development"), productionDistribution: true))
    }

    func testMissingOrMalformedEntitlementDoesNotUseDistributionFallback() throws {
        XCTAssertNil(BetaRemotePush.environment(profile: try profile(nil), productionDistribution: true))
        XCTAssertNil(BetaRemotePush.environment(profile: try profile("invalid"), productionDistribution: true))
        XCTAssertNil(BetaRemotePush.environment(profile: Data("broken".utf8), productionDistribution: true))
    }

    func testAbsentProfileRequiresExplicitVerifiedProductionDistribution() {
        XCTAssertNil(BetaRemotePush.environment(profile: nil, productionDistribution: false))
        XCTAssertEqual(BetaRemotePush.environment(profile: nil, productionDistribution: true), "production")
    }
}
