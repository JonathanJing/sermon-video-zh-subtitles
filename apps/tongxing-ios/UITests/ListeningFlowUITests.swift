import XCTest

/// Real application UI and AVPlayer, with generated silence and an injected
/// URLSession transport. The offline relaunch simulates transport failure;
/// these tests do not establish real-network, audible, lock-screen, or venue QA.
@MainActor
final class ListeningFlowUITests: XCTestCase {
    func testSelectTrackDownloadPlayPauseAndSeekToSubtitle() throws {
        let app = launchFixture()
        try selectSecondTrack(in: app)
        try downloadSelection(in: app)

        let play = app.buttons["playback-toggle"]
        play.tap()
        try waitFor(play, "label == '暂停播放'")
        try waitFor(element("playback-progress", in: app), "value CONTAINS '正在收听'")
        try waitFor(element("playback-progress", in: app), "NOT (value BEGINSWITH '00:00，')")
        play.tap()
        try waitFor(play, "label == '开始播放'")
        try waitFor(element("playback-progress", in: app), "value CONTAINS '已暂停'")

        try seekToSecondSubtitle(in: app)
        let current = app.buttons["current-cue"]
        XCTAssertTrue(current.isHittable)
        current.tap()
        let currentMode = app.segmentedControls["listening-display"].buttons["现场收听"]
        try reveal(currentMode, in: app, direction: .down)
        currentMode.tap()
        try waitFor(element("current-subtitle", in: app), "value == '乙音轨：第二句，用于验证时间定位。'")
        XCTAssertEqual(play.label, "开始播放", "字幕定位必须保留暂停状态")
        screenshot("selected-track-paused-at-second-subtitle", app: app)
    }

    func testDownloadedTrackAndBookmarkSurviveOfflineRelaunch() throws {
        let app = launchFixture()
        try selectSecondTrack(in: app)
        try downloadSelection(in: app)
        try seekToSecondSubtitle(in: app)
        screenshot("downloaded-track-bookmark-before-relaunch", app: app)

        app.terminate()
        app.launchArguments.append("--ui-testing-offline")
        app.launch()
        try waitFor(element("sermon-title", in: app), "label == '界面测试证道'")
        try waitFor(element("catalog-notice", in: app), "label CONTAINS '上次保存的证道目录'")

        // The product starts on the catalog default track. Re-select the actual
        // downloaded second track through its ordinary menu after relaunch.
        try selectSecondTrack(in: app)
        let restoredDownload = element("download-status", in: app)
        try waitFor(restoredDownload, "label CONTAINS '正在使用已下载音频'")
        let saved = element("resume-position", in: app)
        try waitFor(saved, "label CONTAINS '00:12'")
        let restore = app.buttons["restore-position"]
        try reveal(restore, in: app, direction: .down)
        try waitFor(restore, "enabled == true")
        restore.tap()
        try waitFor(element("playback-progress", in: app), "value BEGINSWITH '00:12，'")
        try waitFor(element("current-subtitle", in: app), "value == '乙音轨：第二句，用于验证时间定位。'")
        XCTAssertFalse(saved.exists, "恢复后应关闭旧的位置卡片")
        let play = app.buttons["playback-toggle"]
        play.tap()
        try waitFor(element("playback-progress", in: app), "value CONTAINS '正在收听'")
        try waitFor(element("playback-progress", in: app), "NOT (value BEGINSWITH '00:12，')")
        play.tap()
        try waitFor(element("playback-progress", in: app), "value CONTAINS '已暂停'")
        screenshot("offline-catalog-downloaded-audio-and-restored-position", app: app)
    }

    func testAccessibilityTextKeepsDownloadAndPlaybackControlsReachable() throws {
        let app = launchFixture(largeText: true)
        try downloadSelection(in: app)
        let play = app.buttons["playback-toggle"]
        let forward = app.buttons["nudge-forward"]
        let backward = app.buttons["nudge-backward"]
        for control in [play, forward, backward] {
            XCTAssertTrue(control.isHittable, "大字模式的主要播放控件必须可点击：\(control.identifier)")
            XCTAssertGreaterThanOrEqual(control.frame.minX, app.frame.minX)
            XCTAssertLessThanOrEqual(control.frame.maxX, app.frame.maxX)
            XCTAssertLessThanOrEqual(control.frame.maxY, app.frame.maxY)
        }
        forward.tap()
        try waitFor(element("playback-progress", in: app), "value BEGINSWITH '00:01，'")
        backward.tap()
        try waitFor(element("playback-progress", in: app), "value BEGINSWITH '00:00，'")
        play.tap()
        try waitFor(element("playback-progress", in: app), "value CONTAINS '正在收听'")
        play.tap()
        try waitFor(element("playback-progress", in: app), "value CONTAINS '已暂停'")
        screenshot("accessibility3-download-and-playback-controls", app: app)
    }

    private func launchFixture(largeText: Bool = false) -> XCUIApplication {
        continueAfterFailure = false
        let app = XCUIApplication()
        app.launchArguments = ["--ui-testing"] + (largeText ? ["--ui-testing-large-text"] : [])
        app.launchEnvironment["TONGXING_TEST_HOST"] = "0"
        app.launchEnvironment["TONGXING_UI_TEST_RUN_ID"] = UUID().uuidString
        addTeardownBlock { [weak self] in
            guard let self else { return }
            await MainActor.run {
                self.screenshot("final-ui-state", app: app)
                let hierarchy = XCTAttachment(string: app.debugDescription)
                hierarchy.name = "final-accessibility-hierarchy"
                hierarchy.lifetime = .keepAlways
                self.add(hierarchy)
                app.terminate()
            }
        }
        app.launch()
        XCTAssertTrue(element("sermon-title", in: app).waitForExistence(timeout: 15))
        XCTAssertEqual(element("sermon-title", in: app).label, "界面测试证道")
        return app
    }

    private func selectSecondTrack(in app: XCUIApplication) throws {
        app.buttons["more-options"].tap()
        let track = app.buttons["track-option-fixture-second"]
        try waitFor(track, "exists == true AND hittable == true")
        track.tap()
        try waitFor(element("current-subtitle", in: app), "value == '乙音轨：第一句，用于验证选轨。'")
    }

    private func downloadSelection(in app: XCUIApplication) throws {
        let download = app.buttons["download-audio"]
        try reveal(download, in: app, direction: .up)
        download.tap()
        try waitFor(element("download-status", in: app), "label CONTAINS '正在使用已下载音频'")
        try waitFor(app.buttons["playback-toggle"], "enabled == true AND hittable == true")
    }

    private func seekToSecondSubtitle(in app: XCUIApplication) throws {
        let transcriptMode = app.segmentedControls["listening-display"].buttons["字幕全文"]
        try reveal(transcriptMode, in: app, direction: .down)
        transcriptMode.tap()
        let timestamp = app.buttons["subtitle-cue-1"]
        try reveal(timestamp, in: app, direction: .up)
        XCTAssertTrue(timestamp.isEnabled)
        timestamp.tap()
        try waitFor(element("playback-progress", in: app), "value BEGINSWITH '00:12，'")
        try waitFor(element("playback-progress", in: app), "value CONTAINS '已定位 00:12'")
    }

    private enum ScrollDirection { case up, down }

    private func reveal(_ target: XCUIElement, in app: XCUIApplication, direction: ScrollDirection) throws {
        let scroll = app.scrollViews["listening-scroll"]
        for _ in 0..<10 {
            // safeAreaBar leaves the ScrollView's accessibility frame extending
            // beneath the floating dock. Clip to actual visible reading bounds;
            // a whole-ScrollView percentage can land on the large-text play button.
            let visibleFrame = scroll.frame.intersection(app.frame)
            let top = max(visibleFrame.minY, app.navigationBars.firstMatch.frame.maxY) + 16
            let bottom = min(visibleFrame.maxY, element("playback-progress", in: app).frame.minY - 36)
            guard bottom - top >= 80 else {
                screenshot("insufficient-reading-region", app: app)
                XCTFail("实际界面没有足够的阅读区域供滚动")
                throw FlowFailure.unreachable
            }
            let readingFrame = CGRect(x: visibleFrame.minX, y: top,
                                      width: visibleFrame.width, height: bottom - top)
            let targetFrame = target.exists ? target.frame : nil
            // XCTest can report hittable for controls hidden behind Liquid Glass.
            // Every control used by these flows fits in this viewport, so require
            // the whole control to enter the reading region before its normal tap.
            if let targetFrame, !targetFrame.isEmpty, readingFrame.contains(targetFrame), target.isHittable {
                return
            }
            let upwards = targetFrame.map { $0.midY > readingFrame.midY } ?? (direction == .up)
            let requestedDistance = targetFrame.map { abs($0.midY - readingFrame.midY) } ?? readingFrame.height
            let distance = min(readingFrame.height * 0.72, max(40, requestedDistance))
            let startY = upwards ? bottom - readingFrame.height * 0.12 : top + readingFrame.height * 0.12
            let origin = app.coordinate(withNormalizedOffset: .zero)
            let x = visibleFrame.midX - app.frame.minX
            let start = origin.withOffset(CGVector(dx: x, dy: startY - app.frame.minY))
            let end = origin.withOffset(CGVector(dx: x, dy: startY + (upwards ? -distance : distance) - app.frame.minY))
            // Holding briefly at the destination avoids a fling past the target;
            // the next iteration still re-evaluates direction from its new frame.
            start.press(forDuration: 0.05, thenDragTo: end, withVelocity: .slow, thenHoldForDuration: 0.15)
        }
        screenshot("unreachable-\(target.identifier)", app: app)
        XCTFail("实际界面无法滚动到可点击控件：\(target.identifier)")
        throw FlowFailure.unreachable
    }

    private func element(_ identifier: String, in app: XCUIApplication) -> XCUIElement {
        app.descendants(matching: .any).matching(identifier: identifier).firstMatch
    }

    private func waitFor(_ element: XCUIElement, _ predicate: String,
                         timeout: TimeInterval = 15, file: StaticString = #filePath, line: UInt = #line) throws {
        let expectation = XCTNSPredicateExpectation(predicate: NSPredicate(format: predicate), object: element)
        guard XCTWaiter.wait(for: [expectation], timeout: timeout) == .completed else {
            XCTFail("界面条件未满足：\(element.identifier), \(predicate)", file: file, line: line)
            throw FlowFailure.timeout
        }
    }

    private func screenshot(_ name: String, app: XCUIApplication) {
        let attachment = XCTAttachment(screenshot: app.screenshot())
        attachment.name = name
        attachment.lifetime = .keepAlways
        add(attachment)
    }

    private enum FlowFailure: Error { case unreachable, timeout }
}
