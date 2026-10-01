import Foundation
import XCTest
@testable import Tongxing

final class AppIdentityTests: XCTestCase {
    func testLiveActivityOpensMatchingAppWhenBothChannelsAreInstalled() {
        let expectedChannel = ProcessInfo.processInfo.environment["TONGXING_EXPECTED_CHANNEL"]
        XCTAssertTrue(["beta", "production"].contains(expectedChannel ?? ""),
                      "Test scheme must explicitly select the expected app channel")
        let isBeta = expectedChannel == "beta"
        let expectedScheme = isBeta ? "tongxing-beta" : "tongxing"
        XCTAssertEqual(Bundle.main.bundleIdentifier,
                       isBeta ? "com.jonathanjing.tongxing.beta" : "com.jonathanjing.tongxing.dev")
        let urlTypes = Bundle.main.object(forInfoDictionaryKey: "CFBundleURLTypes") as? [[String: Any]]
        let registeredSchemes = urlTypes?.flatMap { $0["CFBundleURLSchemes"] as? [String] ?? [] }
        XCTAssertEqual(registeredSchemes, [expectedScheme])
        XCTAssertEqual(ListeningActivityAttributes.widgetURL.scheme, expectedScheme)
        XCTAssertEqual(ListeningActivityAttributes.widgetURL.host, "listening")
        XCTAssertEqual(Bundle.main.object(forInfoDictionaryKey: "CFBundleDisplayName") as? String,
                       isBeta ? "同行-beta" : "同行")
    }
}
