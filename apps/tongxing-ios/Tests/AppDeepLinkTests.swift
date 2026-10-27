import Foundation
import XCTest
@testable import Tongxing

final class AppDeepLinkTests: XCTestCase {
    private let host = "ai-for-god-sermon-audio.web.app"
    private let schemes: Set<String> = ["tongxing", "tongxing-beta"]

    private func url(_ value: String) -> URL { URL(string: value)! }

    func testQueryLinkFromPoster() {
        let link = AppDeepLink.parse(url("https://\(host)/?week=if-i-had-more-time-jesus-wins&contentLang=zh-Hans&lang=zh"),
                                     allowedHost: host, allowedSchemes: schemes)
        XCTAssertEqual(link, AppDeepLink(pageID: "if-i-had-more-time-jesus-wins", locale: "zh-Hans", source: .universalLink))
    }

    func testPathLink() {
        let link = AppDeepLink.parse(url("https://\(host)/pages/if-i-had-more-time-jesus-wins/ko/"),
                                     allowedHost: host, allowedSchemes: schemes)
        XCTAssertEqual(link, AppDeepLink(pageID: "if-i-had-more-time-jesus-wins", locale: "ko", source: .universalLink))
    }

    func testPathWithoutLocaleUsesDefault() {
        let link = AppDeepLink.parse(url("https://\(host)/pages/if-i-had-more-time-jesus-wins"),
                                     allowedHost: host, allowedSchemes: schemes)
        XCTAssertEqual(link, AppDeepLink(pageID: "if-i-had-more-time-jesus-wins", locale: nil, source: .universalLink))
    }

    func testCustomScheme() {
        let link = AppDeepLink.parse(url("tongxing://page/if-i-had-more-time-jesus-wins?contentLang=es"),
                                     allowedHost: host, allowedSchemes: schemes)
        XCTAssertEqual(link, AppDeepLink(pageID: "if-i-had-more-time-jesus-wins", locale: "es", source: .customScheme))
    }

    func testRejectsForeignHost() {
        XCTAssertNil(AppDeepLink.parse(url("https://evil.example/?week=if-i-had-more-time-jesus-wins"),
                                       allowedHost: host, allowedSchemes: schemes))
    }

    func testRejectsUnsafePageID() {
        XCTAssertNil(AppDeepLink.parse(url("https://\(host)/?week=../other-page"),
                                       allowedHost: host, allowedSchemes: schemes))
    }

    func testRejectsUnknownLocaleButKeepsPage() {
        let link = AppDeepLink.parse(url("https://\(host)/?week=page&contentLang=fr"),
                                     allowedHost: host, allowedSchemes: schemes)
        XCTAssertEqual(link, AppDeepLink(pageID: "page", locale: nil, source: .universalLink))
    }
}
