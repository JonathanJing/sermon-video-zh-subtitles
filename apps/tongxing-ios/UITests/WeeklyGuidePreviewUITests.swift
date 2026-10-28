import XCTest

@MainActor
final class WeeklyGuidePreviewUITests: XCTestCase {
    // These two tests use the real local Chinese payload and verified Dev
    // sermon identities, rather than the synthetic guide fixture.
    func testLiveChineseWeekFiveShowsIndependentLists() {
        let app = XCUIApplication()
        app.launchArguments = ["-AppleLanguages", "(zh-Hans)", "-AppleLocale", "zh_CN"]
        app.launchEnvironment["TONGXING_TEST_HOST"] = "0"
        app.launch()
        defer { app.terminate() }
        let choose = app.buttons["choose-sermon"]
        XCTAssertTrue(choose.waitForExistence(timeout: 30))
        choose.tap()
        let week = app.buttons["published-page-resi-20261011-54475d42"]
        let chooser = app.scrollViews.firstMatch
        for _ in 0..<35 {
            if week.exists && week.isHittable { break }
            chooser.swipeUp()
        }
        XCTAssertTrue(week.exists && week.isHittable)
        week.tap()
        let language = app.buttons["choose-content-language"]
        XCTAssertTrue(language.waitForExistence(timeout: 15))
        language.tap()
        let chinese = app.buttons["content-language-zh-Hans"]
        XCTAssertTrue(chinese.waitForExistence(timeout: 10))
        chinese.tap()
        let entry = app.buttons["open-guide-beta-preview"]
        XCTAssertTrue(entry.waitForExistence(timeout: 10))
        entry.tap()
        let section = app.buttons["guide-section-page-83"]
        let scroll = app.scrollViews["guide-scroll"]
        XCTAssertTrue(section.waitForExistence(timeout: 20))
        for _ in 0..<10 {
            if section.isHittable { break }
            scroll.swipeUp()
        }
        XCTAssertTrue(section.isHittable)
        section.tap()
        XCTAssertTrue(app.staticTexts["创造之日"].waitForExistence(timeout: 10))
        XCTAssertTrue(app.staticTexts["“反创造”之号"].exists)
        let image = XCTAttachment(screenshot: app.screenshot())
        image.name = "live-chinese-week-five-structured-table"
        image.lifetime = .keepAlways
        add(image)
    }

    func testLiveChineseWeekOneImageCanBeOpenedAndClosed() {
        let app = XCUIApplication()
        app.launchArguments = ["-AppleLanguages", "(zh-Hans)", "-AppleLocale", "zh_CN"]
        app.launchEnvironment["TONGXING_TEST_HOST"] = "0"
        app.launch()
        defer { app.terminate() }
        let choose = app.buttons["choose-sermon"]
        XCTAssertTrue(choose.waitForExistence(timeout: 30))
        choose.tap()
        let week = app.buttons["legacy-week-2026-09-13-same_video-weekendlive-a9e91f52eb4c2484"]
        let chooser = app.scrollViews.firstMatch
        for _ in 0..<35 {
            if week.exists && week.isHittable { break }
            chooser.swipeUp()
        }
        XCTAssertTrue(week.exists && week.isHittable)
        week.tap()
        let entry = app.buttons["open-guide-beta-preview"]
        XCTAssertTrue(entry.waitForExistence(timeout: 15))
        let playback = app.buttons["playback-toggle"].label
        entry.tap()
        let section = app.buttons["guide-section-page-31"]
        let scroll = app.scrollViews["guide-scroll"]
        XCTAssertTrue(section.waitForExistence(timeout: 20))
        for _ in 0..<10 {
            if section.isHittable { break }
            scroll.swipeUp()
        }
        XCTAssertTrue(section.isHittable)
        section.tap()
        // The outer section groups accessibility identifiers; select the
        // image by its source-backed alternative text instead.
        let image = app.buttons["尼布甲尼撒梦中巨像的插画，五个部位对应的解释见本页文字。"]
        XCTAssertTrue(image.waitForExistence(timeout: 10))
        for _ in 0..<4 {
            if image.isHittable { break }
            scroll.swipeUp()
        }
        XCTAssertTrue(image.isHittable)
        image.tap()
        let zoomIn = app.buttons["放大图片"]
        XCTAssertTrue(zoomIn.waitForExistence(timeout: 10))
        zoomIn.tap()
        XCTAssertTrue(app.buttons["缩小图片"].isEnabled)
        let shot = XCTAttachment(screenshot: app.screenshot())
        shot.name = "live-chinese-week-one-image-zoom"
        shot.lifetime = .keepAlways
        add(shot)
        app.buttons["关闭"].tap()
        let visiblePlay = app.buttons.matching(identifier: "playback-toggle").allElementsBoundByIndex.first(where: { $0.isHittable })
        XCTAssertEqual(visiblePlay?.label, playback)
    }

    func testLiveChineseWeekOneMapAndSecondImage() {
        let app = XCUIApplication()
        app.launchArguments = ["-AppleLanguages", "(zh-Hans)", "-AppleLocale", "zh_CN"]
        app.launchEnvironment["TONGXING_TEST_HOST"] = "0"
        app.launch()
        defer { app.terminate() }
        let choose = app.buttons["choose-sermon"]
        XCTAssertTrue(choose.waitForExistence(timeout: 30))
        choose.tap()
        let week = app.buttons["legacy-week-2026-09-13-same_video-weekendlive-a9e91f52eb4c2484"]
        let chooser = app.scrollViews.firstMatch
        for _ in 0..<35 {
            if week.exists && week.isHittable { break }
            chooser.swipeUp()
        }
        XCTAssertTrue(week.exists && week.isHittable)
        week.tap()
        let entry = app.buttons["open-guide-beta-preview"]
        XCTAssertTrue(entry.waitForExistence(timeout: 15))
        entry.tap()
        let section = app.buttons["guide-section-page-33"]
        let scroll = app.scrollViews["guide-scroll"]
        XCTAssertTrue(section.waitForExistence(timeout: 20))
        for _ in 0..<10 {
            if section.isHittable { break }
            scroll.swipeUp()
        }
        XCTAssertTrue(section.isHittable)
        section.tap()
        XCTAssertTrue(app.staticTexts["七教会与拔摩岛"].waitForExistence(timeout: 10))
        XCTAssertTrue(app.staticTexts["1. 别迦摩"].exists)
        XCTAssertTrue(app.staticTexts["8. 拔摩岛"].exists)
        XCTAssertTrue(app.staticTexts["地点约略位置示意，并非教会建筑精确位置。"].exists)
        let sources = app.staticTexts["查看地图来源"]
        for _ in 0..<6 {
            if sources.isHittable { break }
            scroll.swipeUp()
        }
        XCTAssertTrue(sources.isHittable)
        sources.tap()
        XCTAssertTrue(app.links["别迦摩"].waitForExistence(timeout: 5))
        let mapShot = XCTAttachment(screenshot: app.screenshot())
        mapShot.name = "live-chinese-week-one-map-source"
        mapShot.lifetime = .keepAlways
        add(mapShot)
        let secondImage = app.buttons["原手册中人子形象的插画。"]
        for _ in 0..<20 {
            if secondImage.exists && secondImage.isHittable { break }
            scroll.swipeUp()
        }
        XCTAssertTrue(secondImage.exists && secondImage.isHittable)
        secondImage.tap()
        XCTAssertTrue(app.buttons["放大图片"].waitForExistence(timeout: 10))
        app.buttons["关闭"].tap()
    }

    func testLiveChineseWeekSixTableRetainsUnlabeledFirstColumn() {
        let app = XCUIApplication()
        app.launchArguments = ["-AppleLanguages", "(zh-Hans)", "-AppleLocale", "zh_CN"]
        app.launchEnvironment["TONGXING_TEST_HOST"] = "0"
        app.launch()
        defer { app.terminate() }
        let choose = app.buttons["choose-sermon"]
        XCTAssertTrue(choose.waitForExistence(timeout: 30))
        choose.tap()
        let week = app.buttons["published-page-resi-20261018-15030286"]
        XCTAssertTrue(week.waitForExistence(timeout: 10))
        week.tap()
        let language = app.buttons["choose-content-language"]
        XCTAssertTrue(language.waitForExistence(timeout: 15))
        language.tap()
        let chinese = app.buttons["content-language-zh-Hans"]
        XCTAssertTrue(chinese.waitForExistence(timeout: 10))
        chinese.tap()
        let entry = app.buttons["open-guide-beta-preview"]
        XCTAssertTrue(entry.waitForExistence(timeout: 10))
        entry.tap()
        let section = app.buttons["guide-section-page-92"]
        let scroll = app.scrollViews["guide-scroll"]
        XCTAssertTrue(section.waitForExistence(timeout: 20))
        for _ in 0..<10 {
            if section.isHittable { break }
            scroll.swipeUp()
        }
        XCTAssertTrue(section.isHittable)
        section.tap()
        let row = app.descendants(matching: .any).matching(NSPredicate(format: "label CONTAINS %@", "书卷的赐予者")).firstMatch
        XCTAssertTrue(row.waitForExistence(timeout: 10))
        let shot = XCTAttachment(screenshot: app.screenshot())
        shot.name = "live-chinese-week-six-unlabeled-table"
        shot.lifetime = .keepAlways
        add(shot)
    }

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

    func testLiveDevSpanishWeekThreeOpensMatchingRemoteGuide() {
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
        let spanish = app.buttons["content-language-es"]
        XCTAssertTrue(spanish.waitForExistence(timeout: 10))
        spanish.tap()
        let entry = app.buttons["open-guide-beta-preview"]
        XCTAssertTrue(entry.waitForExistence(timeout: 10))
        entry.tap()
        XCTAssertTrue(app.staticTexts["西语机器翻译 · 未经人工审校"].waitForExistence(timeout: 20))
        XCTAssertTrue(app.staticTexts["第 3 周 · Jesús es digno"].exists)
        let section = app.buttons["guide-section-source-page-56"]
        XCTAssertTrue(section.exists)
        XCTAssertTrue(section.label.contains("Aquel que es digno"))
        XCTAssertFalse(app.staticTexts["本周研读手册尚不可用"].exists)
        let screenshot = XCTAttachment(screenshot: app.screenshot())
        screenshot.name = "live-dev-spanish-week-three-guide"
        screenshot.lifetime = .keepAlways
        add(screenshot)
    }

    // Week six is a v5 family with distinct Chinese and Korean sources.
    func testLiveDevKoreanWeekSixMatchesItsOwnSource() {
        let app = XCUIApplication()
        app.launchArguments = ["-AppleLanguages", "(zh-Hans)", "-AppleLocale", "zh_CN"]
        app.launchEnvironment["TONGXING_TEST_HOST"] = "0"
        app.launch()
        defer { app.terminate() }
        let choose = app.buttons["choose-sermon"]
        XCTAssertTrue(choose.waitForExistence(timeout: 30))
        choose.tap()
        let week = app.buttons["published-page-resi-20261018-15030286"]
        XCTAssertTrue(week.waitForExistence(timeout: 10))
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
        XCTAssertTrue(app.staticTexts["第 6 周 · 예수님은 자기 백성을 보내시고 부활시키십니다"].exists)
        XCTAssertTrue(app.buttons["guide-section-source-page-86"].exists)
        XCTAssertFalse(app.staticTexts["本周研读手册尚不可用"].exists)
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
