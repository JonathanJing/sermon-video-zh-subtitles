import XCTest

@MainActor
final class WeeklyUpdateUITests: XCTestCase {
    func testPosterPromptPersistsDismissalAndCanReopen() {
        // A future service date keeps the 08:00 automatic offer out of the way
        // so this test still covers the manual card, playback and receipts.
        let app = launch(["--ui-testing-weekly-update", "--ui-testing-weekly-update-pending"])
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
        let app = launch(["--ui-testing-weekly-update", "--ui-testing-poster-missing"])
        XCTAssertTrue(app.buttons["weekly-update-open"].waitForExistence(timeout: 15))
        XCTAssertFalse(app.staticTexts["weekly-update-title"].exists, "A missing poster must never auto-open a sheet")
        app.buttons["weekly-update-open"].tap()
        XCTAssertTrue(app.staticTexts["海报暂不可用，仍可打开本周内容。"].waitForExistence(timeout: 10))
        XCTAssertTrue(app.buttons["weekly-update-read"].isEnabled)
        capture(app, "weekly-update-poster-unavailable-synthetic")
        app.buttons["weekly-update-read"].tap()
        XCTAssertTrue(app.buttons["weekly-update-reopen"].waitForExistence(timeout: 5))
    }

    func testPosterOpensByItselfAfterEightOnServiceDate() {
        let app = launch(["--ui-testing-weekly-update"])
        // No tap: the verified poster must present itself once the page's
        // service date has reached 08:00 local time.
        XCTAssertTrue(app.staticTexts["weekly-update-title"].waitForExistence(timeout: 30))
        let image = app.images["weekly-update-poster"]
        let verified = XCTNSPredicateExpectation(predicate: NSPredicate(format: "value == %@", "本周海报"), object: image)
        XCTAssertEqual(XCTWaiter.wait(for: [verified], timeout: 30), .completed)
        capture(app, "weekly-update-auto-presented")
        app.buttons["weekly-update-done"].tap()
        XCTAssertTrue(app.buttons["weekly-update-reopen"].waitForExistence(timeout: 5))
        XCTAssertFalse(app.buttons["weekly-update-open"].exists)
        app.terminate()
        app.launch()
        XCTAssertTrue(app.buttons["weekly-update-reopen"].waitForExistence(timeout: 15),
                      "Seen receipt must survive cold launch")
        XCTAssertFalse(app.staticTexts["weekly-update-title"].exists,
                       "The same release must not auto-open again after it was seen")
    }

    func testPosterStaysManualBeforeItsServiceDate() {
        let app = launch(["--ui-testing-weekly-update", "--ui-testing-weekly-update-pending"])
        XCTAssertTrue(app.buttons["weekly-update-open"].waitForExistence(timeout: 15))
        // The poster is verified and announced, but 08:00 local on the service
        // date has not arrived, so the sheet must stay closed until a tap.
        XCTAssertFalse(app.staticTexts["weekly-update-title"].exists)
        capture(app, "weekly-update-card-before-service-date")
        app.buttons["weekly-update-open"].tap()
        XCTAssertTrue(app.staticTexts["weekly-update-title"].waitForExistence(timeout: 5))
        XCTAssertTrue(app.images["weekly-update-poster"].exists)
        capture(app, "weekly-update-manual-before-service-date")
    }

    private func launch(_ extraArguments: [String]) -> XCUIApplication {
        let app = XCUIApplication()
        app.launchArguments = ["--ui-testing"] + extraArguments + ["-AppleLanguages", "(zh-Hans)", "-AppleLocale", "zh_CN"]
        app.launchEnvironment["TONGXING_UI_TEST_RUN_ID"] = UUID().uuidString
        app.launch()
        return app
    }

    private func capture(_ app: XCUIApplication, _ name: String) {
        let attachment = XCTAttachment(screenshot: app.screenshot())
        attachment.name = name; attachment.lifetime = .keepAlways; add(attachment)
    }
}
