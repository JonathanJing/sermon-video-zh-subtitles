import Foundation
import CoreGraphics
import Testing
@testable import TongxingCore

struct PlaybackControlRegionTests {
    let bounds = CGRect(x: 0, y: 0, width: 900, height: 700)

    @Test func flatAndInactiveRegionsDoNotDisplaceControls() {
        #expect(PlaybackControlRegion.resolve(in: bounds, excluding: []) == bounds)
        #expect(PlaybackControlRegion.resolve(in: bounds, excluding: [CGRect(x: 450, y: 0, width: 0, height: 700)]) == bounds)
    }

    @Test func bookAndTabletopKeepControlsTogetherAwayFromFold() {
        let book = CGRect(x: 430, y: 0, width: 40, height: 700)
        let table = CGRect(x: 0, y: 330, width: 900, height: 40)
        #expect(PlaybackControlRegion.resolve(in: bounds, excluding: [book]) == CGRect(x: 470, y: 0, width: 430, height: 700))
        #expect(PlaybackControlRegion.resolve(in: bounds, excluding: [table]) == CGRect(x: 0, y: 370, width: 900, height: 330))
    }

    @Test func cameraAndFoldAreBothExcludedWithoutChangingSafeBounds() {
        let fold = CGRect(x: 430, y: 0, width: 40, height: 700)
        let camera = CGRect(x: 820, y: 600, width: 80, height: 100)
        let result = PlaybackControlRegion.resolve(in: bounds, excluding: [fold, camera])
        #expect(bounds.contains(result))
        #expect(result.intersection(fold).isEmpty)
        #expect(result.intersection(camera).isEmpty)
        #expect(result.width >= 240)
        #expect(result.maxY == bounds.maxY)
    }

    @Test func shortNarrowAndInvalidBoundsRemainBounded() {
        let narrow = CGRect(x: 0, y: 0, width: 200, height: 80)
        #expect(PlaybackControlRegion.resolve(in: narrow, excluding: []) == narrow)
        #expect(PlaybackControlRegion.resolve(in: bounds, excluding: [bounds]) == .zero)
        #expect(PlaybackControlRegion.resolve(in: .zero, excluding: []) == .zero)
    }
}
