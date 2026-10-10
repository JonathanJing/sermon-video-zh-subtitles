import XCTest

@MainActor
final class WeeklyUpdateUITests: XCTestCase {
    func testPosterPromptPersistsDismissalAndCanReopen() {
        let app = XCUIApplication()
        app.launchArguments = ["--ui-testing", "--ui-testing-weekly-update", "-AppleLanguages", "(zh-Hans)", "-AppleLocale", "zh_CN"]
        app.launchEnvironment["TONGXING_UI_TEST_RUN_ID"] = UUID().uuidString
        app.launch()
        XCTAssertTrue(app.buttons["weekly-update-open"].waitForExistence(timeout: 15))
        let play = app.buttons["playback-toggle"]
        XCTAssertTrue(play.waitForExistence(timeout: 10))
        let ready = NSPredicate(format: "enabled == true")
        expectation(for: ready, evaluatedWith: play)
        waitForExpectations(timeout: 10)
        play.tap()
        XCTAssertTrue(app.buttons["playback-toggle"].label.contains("暂停"))
        capture(app, "weekly-update-new-synthetic")
        app.buttons["weekly-update-open"].tap()
        XCTAssertTrue(app.staticTexts["weekly-update-title"].waitForExistence(timeout: 5))
        XCTAssertFalse(app.staticTexts["海报暂不可用，仍可打开本周内容。"].exists)
        XCTAssertTrue(app.images["weekly-update-poster"].exists)
        capture(app, "weekly-update-poster-synthetic")
        app.buttons["weekly-update-done"].tap()
        XCTAssertTrue(app.buttons["weekly-update-reopen"].waitForExistence(timeout: 5))
        XCTAssertFalse(app.buttons["weekly-update-open"].exists)
        XCTAssertTrue(app.buttons["playback-toggle"].label.contains("暂停"), "Viewing a poster must preserve playback")
        app.terminate()
        app.launch()
        XCTAssertTrue(app.buttons["weekly-update-reopen"].waitForExistence(timeout: 15))
        XCTAssertFalse(app.buttons["weekly-update-open"].exists, "Seen receipt must survive cold launch")
        app.buttons["weekly-update-reopen"].tap()
        XCTAssertTrue(app.buttons["weekly-update-read"].waitForExistence(timeout: 5))
        app.buttons["weekly-update-read"].tap()
        XCTAssertTrue(app.buttons["weekly-update-reopen"].waitForExistence(timeout: 5))
    }

    func testMissingPosterStillOffersContent() {
        let app = XCUIApplication()
        app.launchArguments = ["--ui-testing", "--ui-testing-weekly-update", "--ui-testing-poster-missing", "-AppleLanguages", "(zh-Hans)", "-AppleLocale", "zh_CN"]
        app.launchEnvironment["TONGXING_UI_TEST_RUN_ID"] = UUID().uuidString
        app.launch()
        XCTAssertTrue(app.buttons["weekly-update-open"].waitForExistence(timeout: 15))
        app.buttons["weekly-update-open"].tap()
        XCTAssertTrue(app.staticTexts["海报暂不可用，仍可打开本周内容。"].waitForExistence(timeout: 10))
        XCTAssertTrue(app.buttons["weekly-update-read"].isEnabled)
        capture(app, "weekly-update-poster-unavailable-synthetic")
        app.buttons["weekly-update-read"].tap()
        XCTAssertTrue(app.buttons["weekly-update-reopen"].waitForExistence(timeout: 5))
    }

    private func capture(_ app: XCUIApplication, _ name: String) {
        let attachment = XCTAttachment(screenshot: app.screenshot())
        attachment.name = name; attachment.lifetime = .keepAlways; add(attachment)
    }
}
