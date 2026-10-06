import XCTest
import CoreGraphics
@testable import Tongxing

final class PlaybackPanelLayoutTests: XCTestCase {
    func testFullHeightFoldMovesToFreeSideInsteadOfClampingBackAcrossFold() throws {
        let bounds = CGRect(x: 0, y: 0, width: 1000, height: 600)
        let fold = CGRect(x: 490, y: 0, width: 20, height: 600)
        let preferred = CGRect(x: 440, y: 52, width: 320, height: 176)
        let frame = try XCTUnwrap(PlaybackPanelLayout.viewport(preferred: preferred, in: bounds, avoiding: [fold]))
        XCTAssertEqual(frame.size, preferred.size)
        XCTAssertGreaterThanOrEqual(frame.minX, fold.maxX + 8)
        XCTAssertFalse(frame.intersects(fold))
        XCTAssertTrue(bounds.insetBy(dx: 12, dy: 12).contains(frame))
    }

    func testAllBarriersRemainExcludedAfterChoosingAnotherRegion() throws {
        let bounds = CGRect(x: 0, y: 0, width: 900, height: 600)
        let barriers = [CGRect(x: 440, y: 0, width: 20, height: 600),
                        CGRect(x: 570, y: 120, width: 170, height: 180)]
        let frame = try XCTUnwrap(PlaybackPanelLayout.viewport(
            preferred: CGRect(x: 430, y: 100, width: 320, height: 176), in: bounds, avoiding: barriers))
        XCTAssertTrue(bounds.insetBy(dx: 12, dy: 12).contains(frame))
        for barrier in barriers { XCTAssertFalse(frame.intersects(barrier.insetBy(dx: -8, dy: -8))) }
    }

    func testLargeTextPanelUsesContainedScrollableViewportOnShortScreen() throws {
        let bounds = CGRect(x: 0, y: 0, width: 400, height: 260)
        let fold = CGRect(x: 0, y: 125, width: 400, height: 10)
        let frame = try XCTUnwrap(PlaybackPanelLayout.viewport(
            preferred: CGRect(x: 30, y: -400, width: 320, height: 700), in: bounds, avoiding: [fold]))
        XCTAssertEqual(frame.width, 320)
        XCTAssertLessThan(frame.height, 700)
        XCTAssertGreaterThanOrEqual(frame.height, 68)
        XCTAssertFalse(frame.intersects(fold))
        XCTAssertTrue(bounds.insetBy(dx: 12, dy: 12).contains(frame))
    }

    func testNoUsableRegionRequestsSystemPresentationInsteadOfOverlapping() {
        let bounds = CGRect(x: 0, y: 0, width: 400, height: 300)
        XCTAssertNil(PlaybackPanelLayout.viewport(
            preferred: CGRect(x: 30, y: 30, width: 320, height: 176), in: bounds, avoiding: [bounds]))
    }

    func testUnobstructedPreferredPositionIsPreserved() {
        let preferred = CGRect(x: 40, y: 50, width: 320, height: 176)
        XCTAssertEqual(PlaybackPanelLayout.viewport(preferred: preferred,
            in: CGRect(x: 0, y: 0, width: 500, height: 500), avoiding: []), preferred)
    }
}
