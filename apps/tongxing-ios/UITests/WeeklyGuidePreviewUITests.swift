import XCTest

@MainActor
final class WeeklyGuidePreviewUITests: XCTestCase {
    // Actual Dev catalog and same-origin v2 guide, not a UI fixture.
    func testLiveDevKoreanWeekThreeOpensMatchingRemoteGuide() {
        let app = XCUIApplication()
        app.launchArguments = ["-AppleLanguages", "(zh-Hans)", "-AppleLocale", "zh_CN"]
        app.launchEnvironment["TONGXING_TEST_HOST"] = "0"
        app.launch()
        defer { app.terminate() }

        let choose = app.buttons["choose-sermon"]
        XCTAssertTrue(choose.waitForExistence(timeout: 30))
        choose.tap()
        let week = app.buttons["published-page-2026-09-27-weekend-sermon-drive-530"]
        let scroll = app.scrollViews.firstMatch
        XCTAssertTrue(scroll.waitForExistence(timeout: 10))
        for _ in 0..<35 {
            if week.exists && week.isHittable { break }
            scroll.swipeUp()
        }
        XCTAssertTrue(week.exists && week.isHittable)
        week.tap()
        let language = app.buttons["choose-content-language"]
        XCTAssertTrue(language.waitForExistence(timeout: 15))
        language.tap()
        let korean = app.buttons["content-language-ko"]
        XCTAssertTrue(korean.waitForExistence(timeout: 10))
        korean.tap()
        let entry = app.buttons["open-guide-beta-preview"]
        XCTAssertTrue(entry.waitForExistence(timeout: 10))
        entry.tap()
        XCTAssertTrue(app.staticTexts["韩语机器翻译 · 未经人工审校"].waitForExistence(timeout: 20))
        XCTAssertTrue(app.staticTexts["第 3 周 · 예수님은 합당하십니다"].exists)
        let section = app.buttons["guide-section-source-page-56"]
        XCTAssertTrue(section.exists)
        XCTAssertTrue(section.label.contains("합당하신 분"))
        XCTAssertFalse(app.staticTexts["本周研读手册尚不可用"].exists)
        let screenshot = XCTAttachment(screenshot: app.screenshot())
        screenshot.name = "live-dev-korean-week-three-guide"
        screenshot.lifetime = .keepAlways
        add(screenshot)
    }

    func testGuideNavigationKeepsPlaybackAndShowsReviewDisclosure() {
        let app = XCUIApplication()
        app.launchArguments = ["--ui-testing", "--ui-testing-study-guide", "-AppleLanguages", "(zh-Hans)", "-AppleLocale", "zh_CN"]
        app.launchEnvironment["TONGXING_UI_TEST_RUN_ID"] = UUID().uuidString
        app.launchEnvironment["TONGXING_TEST_HOST"] = "0"
        app.launch()
        defer { app.terminate() }
        let entry = app.buttons["open-guide-beta-preview"]
        XCTAssertTrue(entry.waitForExistence(timeout: 20))
        XCTAssertTrue(entry.label.contains("本周研读手册"))
        let play = app.buttons["playback-toggle"]
        XCTAssertTrue(play.waitForExistence(timeout: 10))
        let playLabel = play.label
        entry.tap()
        XCTAssertTrue(app.staticTexts["中文机器翻译 · 未经人工审校"].waitForExistence(timeout: 10))
        let visiblePlay = app.buttons.matching(identifier: "playback-toggle").allElementsBoundByIndex.first(where: { $0.isHittable })
        XCTAssertEqual(visiblePlay?.label, playLabel)
        XCTAssertFalse(app.buttons["playback-dock-collapse-toggle"].exists)
        let group = app.buttons["guide-section-group"]
        XCTAssertTrue(group.exists)
        group.tap()
        XCTAssertTrue(app.staticTexts["测试用讨论内容，不代表教会手册。"].waitForExistence(timeout: 5))
        let question = app.staticTexts["测试用讨论内容，不代表教会手册。"]
        let visible = expectation(for: NSPredicate(format: "hittable == true"), evaluatedWith: question)
        wait(for: [visible], timeout: 5)
        let image = XCTAttachment(screenshot: app.screenshot())
        image.name = "guide-test-discussion"
        image.lifetime = .keepAlways
        add(image)
        let close = app.buttons["guide-close-bottom"]
        if !close.isHittable { app.scrollViews["guide-scroll"].swipeUp() }
        XCTAssertTrue(close.isHittable)
        close.tap()
        XCTAssertTrue(entry.waitForExistence(timeout: 5))
        XCTAssertEqual(app.buttons["playback-toggle"].label, playLabel)
    }
    func testUnmappedSermonShowsUnavailableInsteadOfAnotherWeek() {
        let app = XCUIApplication()
        app.launchArguments = ["--ui-testing", "-AppleLanguages", "(zh-Hans)", "-AppleLocale", "zh_CN"]
        app.launchEnvironment["TONGXING_UI_TEST_RUN_ID"] = UUID().uuidString
        app.launchEnvironment["TONGXING_TEST_HOST"] = "0"
        app.launch()
        defer { app.terminate() }
        let entry = app.buttons["open-guide-beta-preview"]
        XCTAssertTrue(entry.waitForExistence(timeout: 20))
        entry.tap()
        XCTAssertTrue(app.staticTexts["本周研读手册尚不可用"].waitForExistence(timeout: 10))
        XCTAssertFalse(app.staticTexts["第 7 周 · 耶稣得胜"].exists)
        app.buttons["guide-close"].tap()
        XCTAssertTrue(entry.waitForExistence(timeout: 5))
    }

    // This verifies the real locally staged bundle against the live Dev page.
    // A clean checkout has no licensed payload and skips this optional readback.
    func testLocalGuideBundleDisplaysCurrentDevWeekWhenAvailable() throws {
        let app = XCUIApplication()
        app.launchArguments = ["-AppleLanguages", "(zh-Hans)", "-AppleLocale", "zh_CN"]
        app.launchEnvironment["TONGXING_TEST_HOST"] = "0"
        app.launch()
        defer { app.terminate() }
        guard app.staticTexts["published-page-title"].waitForExistence(timeout: 30) ||
              app.otherElements["published-page"].waitForExistence(timeout: 5) else {
            throw XCTSkip("Live Dev published page was not available")
        }
        let choose = app.buttons["choose-sermon"]
        XCTAssertTrue(choose.waitForExistence(timeout: 10))
        choose.tap()
        let week = app.buttons["published-page-resi-20261018-15030286"]
        guard week.waitForExistence(timeout: 10) else {
            throw XCTSkip("The checked Dev page is no longer in the live catalog")
        }
        week.tap()
        let language = app.buttons["choose-content-language"]
        XCTAssertTrue(language.waitForExistence(timeout: 10))
        language.tap()
        let chinese = app.buttons["content-language-zh-Hans"]
        XCTAssertTrue(chinese.waitForExistence(timeout: 10))
        chinese.tap()
        let entry = app.buttons["open-guide-beta-preview"]
        XCTAssertTrue(entry.waitForExistence(timeout: 10))
        entry.tap()
        let unavailable = app.staticTexts["本周研读手册尚不可用"]
        if unavailable.waitForExistence(timeout: 3) {
            throw XCTSkip("Local guide payload or mapping is not available for the live Dev page")
        }
        XCTAssertTrue(app.staticTexts["中文机器翻译 · 未经人工审校"].waitForExistence(timeout: 10))
        XCTAssertTrue(app.buttons["guide-section-scripture-cuv1919"].exists)
        XCTAssertTrue(app.buttons["guide-close"].exists)
        let image = XCTAttachment(screenshot: app.screenshot())
        image.name = "local-guide-real-bundle"
        image.lifetime = .keepAlways
        add(image)
    }

    // Live Dev readback; uses the real app catalog and staged Bundle, not UI fixtures.
    func testLiveDevLegacyWeekOneOpensMatchingGuide() throws {
        let app = XCUIApplication()
        app.launchArguments = ["-AppleLanguages", "(zh-Hans)", "-AppleLocale", "zh_CN"]
        app.launchEnvironment["TONGXING_TEST_HOST"] = "0"
        app.launch()
        defer { app.terminate() }

        let choose = app.buttons["choose-sermon"]
        guard choose.waitForExistence(timeout: 30) else {
            throw XCTSkip("Live Dev sermon selector is unavailable")
        }
        choose.tap()
        let week = app.buttons["legacy-week-2026-09-13-same_video-weekendlive-a9e91f52eb4c2484"]
        let scroll = app.scrollViews.firstMatch
        guard scroll.waitForExistence(timeout: 10) else {
            throw XCTSkip("Live Dev sermon list is unavailable")
        }
        for _ in 0..<35 {
            if week.exists && week.isHittable { break }
            scroll.swipeUp()
        }
        guard week.exists && week.isHittable else {
            throw XCTSkip("The verified legacy week-one sermon is absent or cannot be reached in the live Dev catalog")
        }
        week.tap()
        let heading = app.staticTexts["sermon-title"]
        XCTAssertTrue(heading.waitForExistence(timeout: 20))
        let entry = app.buttons["open-guide-beta-preview"]
        XCTAssertTrue(entry.waitForExistence(timeout: 10))
        entry.tap()
        XCTAssertTrue(app.staticTexts["第 1 周 · 耶稣与你同在"].waitForExistence(timeout: 20))
        XCTAssertTrue(app.staticTexts["中文机器翻译 · 未经人工审校"].exists)
        let screenshot = XCTAttachment(screenshot: app.screenshot())
        screenshot.name = "live-dev-legacy-week-one-guide"
        screenshot.lifetime = .keepAlways
        add(screenshot)
    }

}
