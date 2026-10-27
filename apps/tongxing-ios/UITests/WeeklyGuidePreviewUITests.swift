import XCTest

@MainActor
final class WeeklyGuidePreviewUITests: XCTestCase {
    func testGuidePreviewNavigationKeepsPlaybackAndUsesSyntheticContent() {
        let app = XCUIApplication()
        app.launchArguments = ["--ui-testing", "--ui-testing-study-guide", "-AppleLanguages", "(zh-Hans)", "-AppleLocale", "zh_CN"]
        app.launchEnvironment["TONGXING_UI_TEST_RUN_ID"] = UUID().uuidString
        app.launchEnvironment["TONGXING_TEST_HOST"] = "0"
        app.launch()
        defer { app.terminate() }
        let entry = app.buttons["open-sermon-study"]
        XCTAssertTrue(entry.waitForExistence(timeout: 20))
        XCTAssertTrue(entry.label.contains("本周研读手册"))
        let play = app.buttons["playback-toggle"]
        XCTAssertTrue(play.waitForExistence(timeout: 10))
        let playLabel = play.label
        entry.tap()
        XCTAssertTrue(app.staticTexts["合成预览 · 非教会手册"].waitForExistence(timeout: 10))
        let visiblePlay = app.buttons.matching(identifier: "playback-toggle").allElementsBoundByIndex.first(where: { $0.isHittable })
        XCTAssertEqual(visiblePlay?.label, playLabel)
        XCTAssertFalse(app.buttons["playback-dock-collapse-toggle"].exists)
        let group = app.buttons["guide-section-group"]
        XCTAssertTrue(group.exists)
        group.tap()
        XCTAssertTrue(app.staticTexts["示意问题：请分享你在本周学习中的一个观察。"].waitForExistence(timeout: 5))
        let question = app.staticTexts["示意问题：请分享你在本周学习中的一个观察。"]
        let visible = expectation(for: NSPredicate(format: "hittable == true"), evaluatedWith: question)
        wait(for: [visible], timeout: 5)
        let image = XCTAttachment(screenshot: app.screenshot())
        image.name = "guide-synthetic-discussion"
        image.lifetime = .keepAlways
        add(image)
        let close = app.buttons["guide-close-bottom"]
        if !close.isHittable { app.scrollViews["guide-scroll"].swipeUp() }
        XCTAssertTrue(close.isHittable)
        close.tap()
        XCTAssertTrue(entry.waitForExistence(timeout: 5))
        XCTAssertEqual(app.buttons["playback-toggle"].label, playLabel)
    }
}
