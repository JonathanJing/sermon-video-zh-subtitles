import XCTest

/// Synthetic transaction, real ActivityKit and Springboard presentation.
/// This test does not represent microphone capture or physical-device acceptance.
@MainActor
final class ListeningActivityUITests: XCTestCase {
    func testForegroundAlignmentIslandShowsPhasesAndNewTransaction() throws {
        guard #available(iOS 18.0, *) else { throw XCTSkip("Foreground transient activity requires iOS 18") }
        try XCTSkipUnless(ProcessInfo.processInfo.environment["TONGXING_LIVE_ACTIVITY_SMOKE"] == "1",
                          "Explicit opt-in required to create system Live Activities")
        let app = XCUIApplication()
        app.launchArguments = ["--ui-testing", "--ui-testing-live-activity",
                               "-AppleLanguages", "(zh-Hans)", "-AppleLocale", "zh_CN"]
        app.launchEnvironment["TONGXING_UI_TEST_RUN_ID"] = UUID().uuidString
        app.launch()
        let system = XCUIApplication(bundleIdentifier: "com.apple.springboard")
        for (phase, name) in [("正在听现场 · 保持前台", "listening"),
                              ("正在本机匹配", "matching"), ("已对齐", "aligned")] {
            let visible = system.staticTexts[phase].firstMatch
            let appeared = visible.waitForExistence(timeout: 15)
            let shot = XCTAttachment(screenshot: XCUIScreen.main.screenshot())
            shot.name = "foreground-island-\(name)"
            shot.lifetime = .keepAlways
            add(shot)
            XCTAssertTrue(appeared, "必须观察系统前台展示，不能仅检查状态回调：\(phase)")
            if !appeared { return }
        }
        let aligned = system.staticTexts["已对齐"].firstMatch
        expectation(for: NSPredicate(format: "exists == false"), evaluatedWith: aligned)
        waitForExpectations(timeout: 12)
        XCTAssertTrue(system.staticTexts["正在听现场 · 保持前台"].firstMatch.waitForExistence(timeout: 10),
                      "清理上一事务后，同来源的新事务必须可以显示")
    }
}
