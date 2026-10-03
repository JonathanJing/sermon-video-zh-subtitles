import XCTest

@MainActor
final class BetaNotificationUITests: XCTestCase {
    func testBetaSettingsRequireExplicitOptInWithoutRequestingSystemPermission() throws {
        let app = XCUIApplication()
        app.launchArguments = ["--ui-testing"]
        app.launchEnvironment["TONGXING_UI_TEST_RUN_ID"] = UUID().uuidString
        app.launch()
        XCTAssertTrue(app.buttons["more-options"].waitForExistence(timeout: 10))
        app.buttons["more-options"].tap()
        let link = app.buttons["beta-notification-settings"]
        let beta = ProcessInfo.processInfo.environment["TONGXING_EXPECTED_CHANNEL"] == "beta"
        if !beta {
            XCTAssertFalse(link.exists, "正式渠道不能显示 Beta 通知实验入口")
            return
        }
        XCTAssertTrue(link.waitForExistence(timeout: 5))
        link.tap()
        let toggle = app.switches["beta-notification-opt-in"]
        XCTAssertTrue(toggle.waitForExistence(timeout: 5))
        XCTAssertEqual(toggle.value as? String, "0")
        XCTAssertFalse(app.buttons["beta-notification-permission"].isEnabled)
        toggle.coordinate(withNormalizedOffset: CGVector(dx: 0.92, dy: 0.5)).tap()
        XCTAssertEqual(toggle.value as? String, "1")
        XCTAssertTrue(app.buttons["beta-notification-permission"].isEnabled)
        toggle.coordinate(withNormalizedOffset: CGVector(dx: 0.92, dy: 0.5)).tap()
        XCTAssertFalse(app.buttons["beta-notification-permission"].isEnabled)
        XCTAssertTrue(app.staticTexts["beta-notification-status"].label.contains("已退出"))
        let shot = XCTAttachment(screenshot: app.screenshot())
        shot.name = "beta-notifications-opt-out"
        shot.lifetime = .keepAlways
        add(shot)
    }

    func testLocalNotificationDisplaysAndRoutesVerifiedFixture() throws {
        try XCTSkipUnless(ProcessInfo.processInfo.environment["TONGXING_EXPECTED_CHANNEL"] == "beta",
                          "Local notification delivery is a Beta-only experiment")
        let app = XCUIApplication()
        app.launchArguments = ["--ui-testing", "--ui-testing-notification"]
        app.launchEnvironment["TONGXING_UI_TEST_RUN_ID"] = UUID().uuidString
        app.launch()
        XCTAssertTrue(app.buttons["more-options"].waitForExistence(timeout: 10))
        app.buttons["more-options"].tap()
        app.buttons["beta-notification-settings"].tap()
        let toggle = app.switches["beta-notification-opt-in"]
        XCTAssertTrue(toggle.waitForExistence(timeout: 5))
        toggle.coordinate(withNormalizedOffset: CGVector(dx: 0.92, dy: 0.5)).tap()
        let springboard = XCUIApplication(bundleIdentifier: "com.apple.springboard")
        app.buttons["beta-notification-permission"].tap()
        let allow = springboard.buttons["允许"].exists ? springboard.buttons["允许"] : springboard.buttons["Allow"]
        if allow.waitForExistence(timeout: 3) { allow.tap() }
        let status = app.staticTexts["beta-notification-status"]
        let authorized = NSPredicate(format: "label CONTAINS %@", "系统通知已允许")
        expectation(for: authorized, evaluatedWith: status)
        waitForExpectations(timeout: 8)
        let preview = app.buttons["beta-notification-preview"]
        XCTAssertTrue(preview.waitForExistence(timeout: 5))
        if !preview.isHittable { app.swipeUp() }
        preview.tap()
        expectation(for: NSPredicate(format: "label CONTAINS %@", "已安排 5 秒"), evaluatedWith: status)
        waitForExpectations(timeout: 5)
        XCUIDevice.shared.press(.home)
        let notice = springboard.staticTexts["[Beta 测试] 新内容已上架"].firstMatch
        // The simulator's first Springboard notification arrived about 15 s
        // after scheduling in the observed run; five seconds is the earliest
        // trigger time, not an OS display deadline.
        guard notice.waitForExistence(timeout: 30) else {
            XCTFail("必须实际看到系统通知，不能只检查 schedule 返回值")
            return
        }
        let screenshot = XCTAttachment(screenshot: springboard.screenshot())
        screenshot.name = "beta-local-notification-visible"
        screenshot.lifetime = .keepAlways
        add(screenshot)
        notice.tap()
        XCTAssertTrue(app.buttons["more-options"].waitForExistence(timeout: 10))
        app.buttons["more-options"].tap()
        app.buttons["beta-notification-settings"].tap()
        // Settings refreshes permissions on entry; use the verified landing
        // marker exposed by the controller instead of a mutable status label.
        XCTAssertTrue(app.staticTexts["beta-notification-last-opened"].waitForExistence(timeout: 5))
        XCTAssertEqual(app.staticTexts["beta-notification-last-opened"].label, "ui-test-full-video · zh-Hans")
        let cleanupToggle = app.switches["beta-notification-opt-in"]
        cleanupToggle.coordinate(withNormalizedOffset: CGVector(dx: 0.92, dy: 0.5)).tap()
    }
}
