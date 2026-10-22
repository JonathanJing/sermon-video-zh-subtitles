import XCTest

@MainActor
final class ProductionPushUITests: XCTestCase {
    func testFormalSettingsStartUnsubscribedAndExplainOptIn() throws {
        let app = XCUIApplication()
        app.launchArguments = ["--ui-testing", "-AppleLanguages", "(zh-Hans)", "-AppleLocale", "zh_CN"]
        app.launch()

        XCTAssertTrue(app.buttons["more-options"].waitForExistence(timeout: 20))
        app.buttons["more-options"].tap()
        XCTAssertFalse(app.buttons["beta-notification-settings"].exists)
        let link = app.buttons["production-push-settings"]
        XCTAssertTrue(link.waitForExistence(timeout: 8))
        link.tap()

        XCTAssertTrue(app.buttons["production-push-enable"].waitForExistence(timeout: 8))
        XCTAssertFalse(app.buttons["production-push-disable"].exists)
        XCTAssertTrue(app.buttons["production-push-locale"].exists)
        let status = app.staticTexts["production-push-status"].label
        XCTAssertTrue(status.contains("默认关闭") || status.contains("off by default"))

        let shot = XCTAttachment(screenshot: app.screenshot())
        shot.name = "production-push-default-off"
        shot.lifetime = .keepAlways
        add(shot)
    }
}
