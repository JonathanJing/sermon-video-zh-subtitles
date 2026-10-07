import XCTest
@testable import Tongxing

@MainActor
final class DownloadBackgroundAssertionTests: XCTestCase {
    func testExpirationEndsBeforeUnresponsiveWorkAndCompletionDoesNotEndTwice() {
        var expire: (@MainActor () -> Void)?
        var events: [String] = []
        let assertion = DownloadBackgroundAssertion(begin: { expire = $0; return 7 },
            end: { events.append("end-\($0)") })
        assertion.start { events.append("cancel-network") }
        expire?()
        XCTAssertEqual(events, ["end-7", "cancel-network"])
        XCTAssertTrue(assertion.didExpire)
        assertion.finish()
        XCTAssertEqual(events.count, 2)
    }

    func testNormalCompletionAndUnavailableAssertionDoNotLeak() {
        var ended: [Int] = []
        var lateExpiration: (@MainActor () -> Void)?
        let normal = DownloadBackgroundAssertion(begin: { lateExpiration = $0; return 8 }, end: { ended.append($0) })
        normal.start { XCTFail("Normal completion must not expire") }
        normal.finish()
        normal.finish()
        lateExpiration?()
        XCTAssertFalse(normal.didExpire)
        let unavailable = DownloadBackgroundAssertion(begin: { _ in -1 }, end: { ended.append($0) })
        unavailable.start {}
        unavailable.finish()
        XCTAssertEqual(ended, [8])
    }

    func testImmediateExpirationBalancesReturnedIdentifier() {
        var ended: [Int] = []
        let assertion = DownloadBackgroundAssertion(begin: { callback in callback(); return 9 },
            end: { ended.append($0) })
        assertion.start {}
        assertion.finish()
        XCTAssertEqual(ended, [9])
    }
}
