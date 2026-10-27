import Foundation
import XCTest
@testable import Tongxing

final class WeeklyGuideDataTests: XCTestCase {
    private let fixture = """
    {"guides":[{"id":"synthetic-sermon","week":7,"title":"Sample",
    "scripture":"Example 1","sections":[
    {"id":"page-1","title":"First","subtitle":"One","symbol":"doc.text","body":"A"},
    {"id":"page-2","title":"Second","subtitle":"Two","symbol":"doc.text","body":"B"}]},
    {"id":"another-sermon","week":3,"title":"Another sample","scripture":"Example 2",
    "sections":[{"id":"page-3","title":"Third","subtitle":"Three","symbol":"doc.text","body":"C"}]}]}
    """.data(using: .utf8)!

    func testOnlyExactSermonAndSimplifiedChineseMatch() {
        let guide = WeeklyGuideRepository.load(pageID: "synthetic-sermon", locale: "zh-Hans", data: fixture)
        XCTAssertEqual(guide?.week, 7)
        XCTAssertEqual(guide?.sections.map(\.id), ["page-1", "page-2"])
        let other = WeeklyGuideRepository.load(pageID: "another-sermon", locale: "zh-Hans", data: fixture)
        XCTAssertEqual(other?.week, 3)
        XCTAssertEqual(other?.sections.map(\.id), ["page-3"])
        XCTAssertNil(WeeklyGuideRepository.load(pageID: "other-sermon", locale: "zh-Hans", data: fixture))
        XCTAssertNil(WeeklyGuideRepository.load(pageID: nil, locale: "zh-Hans", data: fixture))
        XCTAssertNil(WeeklyGuideRepository.load(pageID: "synthetic-sermon", locale: "zh-Hant", data: fixture))
        XCTAssertNil(WeeklyGuideRepository.load(pageID: "synthetic-sermon", locale: "en", data: fixture))
    }

    func testInvalidOrAmbiguousPayloadDoesNotDisplayGuide() {
        XCTAssertNil(WeeklyGuideRepository.load(pageID: "synthetic-sermon", locale: "zh-Hans", data: Data()))
        XCTAssertNil(WeeklyGuideRepository.load(pageID: "synthetic-sermon", locale: "zh-Hans", data: Data("{bad".utf8)))
        let duplicated = """
        {"guides":[
          {"id":"x","week":1,"title":"A","scripture":"X","sections":[{"id":"1","title":"A","subtitle":"A","symbol":"book","body":"A"}]},
          {"id":"x","week":2,"title":"B","scripture":"Y","sections":[{"id":"2","title":"B","subtitle":"B","symbol":"book","body":"B"}]}
        ]}
        """.data(using: .utf8)!
        XCTAssertNil(WeeklyGuideRepository.load(pageID: "x", locale: "zh-Hans", data: duplicated))
    }
}
