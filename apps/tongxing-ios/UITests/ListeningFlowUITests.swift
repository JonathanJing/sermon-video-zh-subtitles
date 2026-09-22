import XCTest

/// Real application UI and AVPlayer, with generated silence and an injected
/// URLSession transport. The offline relaunch simulates transport failure;
/// these tests do not establish real-network, audible, lock-screen, or venue QA.
@MainActor
final class ListeningFlowUITests: XCTestCase {
    func testTargetLanguageSheetShowsOnlyPublishedCapabilities() throws {
        let app = launchFixture()
        let chooser = app.buttons["choose-content-language"]
        XCTAssertTrue(chooser.isHittable)
        XCTAssertTrue(chooser.value as? String == "简体中文，Text only" || chooser.value as? String == "简体中文，仅文字")
        chooser.tap()
        let chinese = app.buttons["content-language-zh-Hans"]
        let korean = app.buttons["content-language-ko"]
        XCTAssertTrue(chinese.waitForExistence(timeout: 5))
        XCTAssertTrue(korean.exists)
        XCTAssertEqual(chinese.value as? String, "已选择")
        XCTAssertTrue(korean.label.contains("한국어"))
        XCTAssertTrue(korean.label.contains("仅文字"))
        screenshot("target-language-sheet-published-capabilities", app: app)
    }

    func testUnavailableAlignmentExplainsReason() throws {
        let app = launchFixture()
        let alignment = app.buttons["align-live-audio"]
        try waitFor(alignment, "exists == true AND enabled == true AND hittable == true")
        alignment.tap()
        let explanation = app.alerts["现场自动对齐暂不可用"]
        XCTAssertTrue(explanation.waitForExistence(timeout: 5))
        XCTAssertTrue(explanation.staticTexts["本篇尚未提供现场对齐资料，请刷新目录或手动定位。"].exists)
        screenshot("unavailable-alignment-explanation", app: app)
        explanation.buttons["关闭"].tap()
        XCTAssertFalse(explanation.exists)
    }

    func testPlaybackDockSwipeCollapsesWithoutPausingAndExpands() throws {
        let app = launchFixture()
        try downloadSelection(in: app)
        let play = app.buttons["playback-toggle"]
        play.tap()
        try waitFor(play, "label == '暂停播放'")
        try waitFor(element("playback-progress", in: app), "NOT (value BEGINSWITH '00:00，')")
        let expandedPlayFrame = play.frame
        collapseDock(in: app)
        try waitFor(element("playback-progress", in: app), "exists == false")
        XCTAssertFalse(app.buttons["nudge-forward"].exists)
        XCTAssertFalse(app.buttons["align-live-audio"].exists)
        XCTAssertEqual(app.buttons.matching(identifier: "playback-toggle").count, 1)
        XCTAssertEqual(play.label, "暂停播放", "收起操作不能暂停音频")
        XCTAssertLessThan(play.frame.width, expandedPlayFrame.width)
        XCTAssertTrue(play.isHittable)
        play.tap()
        try waitFor(play, "label == '开始播放'")
        screenshot("collapsed-player-paused", app: app)
        expandDock(in: app)
        try waitFor(element("playback-progress", in: app), "exists == true")
        try assertAlignmentBelowPlayback(in: app)
        XCTAssertEqual(play.label, "开始播放", "展开操作不能改变暂停状态")
        screenshot("expanded-player-restored", app: app)
    }

    func testAccessibilityTextDockCanCollapseAndExpand() throws {
        let app = launchFixture(largeText: true)
        collapseDock(in: app)
        try waitFor(element("playback-progress", in: app), "exists == false")
        let play = app.buttons["playback-toggle"]
        XCTAssertTrue(play.isHittable)
        XCTAssertGreaterThanOrEqual(play.frame.width, 44)
        XCTAssertGreaterThanOrEqual(play.frame.height, 44)
        XCTAssertTrue(app.frame.contains(play.frame))
        expandDock(in: app)
        try waitFor(element("playback-progress", in: app), "exists == true")
        try assertAlignmentBelowPlayback(in: app)
    }

    private func collapseDock(in app: XCUIApplication) {
        let progress = element("playback-progress", in: app)
        let start = progress.coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: 0.5))
        start.press(forDuration: 0.05, thenDragTo: start.withOffset(CGVector(dx: 0, dy: 70)))
    }

    private func expandDock(in app: XCUIApplication) {
        let start = app.buttons["playback-toggle"].coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: 0.5))
        start.press(forDuration: 0.05, thenDragTo: start.withOffset(CGVector(dx: 0, dy: -100)))
    }

    func testLiveAlignmentStaysBelowPlaybackOnFirstScreenAndTranscript() throws {
        let app = launchFixture()
        try assertAlignmentBelowPlayback(in: app)
        app.segmentedControls["listening-display"].buttons["字幕全文"].tap()
        try assertAlignmentBelowPlayback(in: app)
        screenshot("alignment-below-playback-transcript", app: app)
    }

    func testLandscapeKeepsLiveAlignmentBelowPlayback() throws {
        XCUIDevice.shared.orientation = .landscapeLeft
        defer { XCUIDevice.shared.orientation = .portrait }
        let app = launchFixture()
        try assertAlignmentBelowPlayback(in: app)
        screenshot("landscape-alignment-below-playback", app: app)
    }

    func testOpeningTranscriptWhilePlayingLocatesCurrentCueOnlyOnce() throws {
        let app = launchFixture(largeText: true)
        try selectSecondTrack(in: app)
        try downloadSelection(in: app)
        try seekToSecondSubtitle(in: app)
        let modes = app.segmentedControls["listening-display"]
        let currentMode = modes.buttons["现场收听"]
        try reveal(currentMode, in: app, direction: .down)
        currentMode.tap()
        let play = app.buttons["playback-toggle"]
        play.tap()
        try waitFor(play, "label == '暂停播放'")
        modes.buttons["字幕全文"].tap()

        // Do not use reveal here: it would conceal a missing automatic scroll.
        let timestamp = app.buttons["subtitle-cue-1"]
        let located = XCTNSPredicateExpectation(predicate: NSPredicate { _, _ in
            let top = app.navigationBars.firstMatch.frame.maxY
            let bottom = self.element("playback-progress", in: app).frame.minY - 36
            return timestamp.exists && timestamp.isHittable
                && timestamp.frame.minY >= top && timestamp.frame.maxY <= bottom
        }, object: nil)
        XCTAssertEqual(XCTWaiter.wait(for: [located], timeout: 5), .completed)
        screenshot("playing-transcript-auto-located-current-cue", app: app)

        try reveal(currentMode, in: app, direction: .down)
        let movedAway = XCTNSPredicateExpectation(predicate: NSPredicate { _, _ in
            currentMode.frame.minY < app.navigationBars.firstMatch.frame.maxY
        }, object: nil)
        movedAway.isInverted = true
        XCTAssertEqual(XCTWaiter.wait(for: [movedAway], timeout: 2), .completed,
                       "播放推进不能抢走手动滚动位置")
        play.tap()
        try waitFor(play, "label == '开始播放'")
        currentMode.tap()
        modes.buttons["字幕全文"].tap()
        XCTAssertGreaterThanOrEqual(currentMode.frame.minY, app.navigationBars.firstMatch.frame.maxY,
                                    "暂停时打开全文应保留阅读入口位置")
        XCTAssertEqual(play.label, "开始播放")
        screenshot("paused-transcript-preserves-reading-position", app: app)
    }

    func testEnglishInterfaceAndOriginalTranscriptPreserveSelectedPosition() throws {
        let app = launchFixture()
        try selectSecondTrack(in: app)
        try downloadSelection(in: app)
        try seekToSecondSubtitle(in: app)
        let english = element("transcript-english-1", in: app)
        let comparison = element("transcript-english-toggle-1", in: app)
        try reveal(comparison, in: app, direction: .up)
        XCTAssertFalse(english.exists)
        comparison.tap()
        try reveal(english, in: app, direction: .up)
        XCTAssertTrue(english.label.contains("Second synthetic source sentence"))
        try waitFor(element("playback-progress", in: app), "value BEGINSWITH '00:12'")
        comparison.tap()
        XCTAssertFalse(english.exists)
        comparison.tap()
        app.buttons["more-options"].tap()
        let language = element("interface-language", in: app)
        try reveal(language, in: app, direction: .up)
        language.tap()
        app.buttons["English"].tap()
        app.buttons["Done"].tap()
        try waitFor(app.buttons["playback-toggle"], "label == 'Play'")
        try waitFor(element("playback-progress", in: app), "value BEGINSWITH '00:12'")
        XCTAssertEqual(element("sermon-title", in: app).label, "界面测试证道")
        XCTAssertTrue(english.label.contains("Second synthetic source sentence"))
        screenshot("english-interface-source-bilingual-transcript", app: app)
    }

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
        try assertAlignmentBelowPlayback(in: app)
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

    private func assertAlignmentBelowPlayback(in app: XCUIApplication,
                                              file: StaticString = #filePath, line: UInt = #line) throws {
        let align = app.buttons["align-live-audio"]
        try waitFor(align, "exists == true AND hittable == true")
        let play = app.buttons["playback-toggle"]
        XCTAssertEqual(app.buttons.matching(identifier: "align-live-audio").count, 1,
                       "首页只能出现一个现场对齐入口", file: file, line: line)
        XCTAssertGreaterThanOrEqual(align.frame.minY, play.frame.maxY,
                                    "现场对齐按钮应在播放按钮下方", file: file, line: line)
        XCTAssertTrue(app.frame.contains(align.frame),
                      "无需滚动就应完整显示现场对齐按钮", file: file, line: line)
    }

    private func launchFixture(largeText: Bool = false) -> XCUIApplication {
        continueAfterFailure = false
        let app = XCUIApplication()
        app.launchArguments = ["--ui-testing"] + (largeText ? ["--ui-testing-large-text"] : [])
        app.launchArguments += ["-AppleLanguages", "(zh-Hans)", "-AppleLocale", "zh_CN"]
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
