import Foundation
import ActivityKit
import TongxingCore
import XCTest
@testable import Tongxing

final class ListeningActivityStateTests: XCTestCase {
    @MainActor
    func testActualActivityReceivesBilingualCueAndPausedState() async throws {
        guard ActivityAuthorizationInfo().areActivitiesEnabled else { throw XCTSkip("Live Activities disabled by system") }
        let coordinator = ListeningLiveActivityCoordinator(allowSystemActivitiesInTests: true)
        let title = "Synthetic bilingual \(UUID().uuidString)"
        let source = UUID().uuidString
        defer { coordinator.end() }
        coordinator.update(title: title, speaker: "Synthetic fixture", position: 12, duration: 300,
            isPlaying: true, sourceKey: source, subtitleID: "unit-1",
            chineseSubtitle: "合成中文句", englishSubtitle: "Synthetic English sentence")
        var observed: Activity<ListeningActivityAttributes>?
        for _ in 0..<100 {
            observed = Activity<ListeningActivityAttributes>.activities.first { $0.content.state.title == title }
            if observed != nil { break }
            try await Task.sleep(for: .milliseconds(25))
        }
        let activity = try XCTUnwrap(observed)
        XCTAssertEqual(activity.content.state.chineseSubtitle, "合成中文句")
        XCTAssertEqual(activity.content.state.englishSubtitle, "Synthetic English sentence")
        coordinator.update(title: title, speaker: "Synthetic fixture", position: 12, duration: 300,
            isPlaying: false, sourceKey: source, subtitleID: "unit-1",
            chineseSubtitle: "合成中文句", englishSubtitle: "Synthetic English sentence")
        for _ in 0..<100 {
            if !activity.content.state.isPlaying { break }
            try await Task.sleep(for: .milliseconds(25))
        }
        XCTAssertFalse(activity.content.state.isPlaying)
        XCTAssertEqual(activity.content.state.position, 12)
        XCTAssertEqual(activity.content.state.subtitleID, "unit-1")
    }

    func testActualEncodedPayloadBoundsEscapedTextAndUnlimitedUnitID() throws {
        let escaped = String(repeating: "\u{0000}\u{0001}\n\t\"\\中👨‍👩‍👧‍👦", count: 1000)
        let input = ListeningActivityAttributes.ContentState(
            title: escaped, speaker: escaped, position: 42, duration: 300,
            isPlaying: true, isWaiting: true, sampledAt: Date(), languageCode: escaped,
            subtitleID: escaped, chineseSubtitle: escaped, englishSubtitle: escaped)
        let bounded = try XCTUnwrap(ListeningLiveActivityCoordinator.boundedState(input))
        let encoded = try JSONEncoder().encode(bounded)
        XCTAssertLessThanOrEqual(encoded.count, 3500)
        XCTAssertLessThan(bounded.title.count, input.title.count)
        XCTAssertLessThan(try XCTUnwrap(bounded.subtitleID).count, escaped.count)
        XCTAssertLessThanOrEqual(try JSONEncoder().encode(bounded.languageCode).count, 40)
        XCTAssertEqual(bounded.position, input.position)
        XCTAssertEqual(bounded.isPlaying, input.isPlaying)
        XCTAssertEqual(bounded.isWaiting, input.isWaiting)
        // Swift Character truncation never slices an extended grapheme cluster.
        XCTAssertTrue(escaped.hasPrefix(try XCTUnwrap(bounded.chineseSubtitle)))
        XCTAssertEqual(try JSONDecoder().decode(ListeningActivityAttributes.ContentState.self, from: encoded), bounded)
    }

    func testSmallPayloadIsUnchangedAndNilMappingsRemainNil() throws {
        let input = ListeningActivityAttributes.ContentState(
            title: "已审核证道", speaker: "Speaker", position: 42, duration: 300,
            isPlaying: false, isWaiting: false, sampledAt: Date(), languageCode: "zh",
            subtitleID: "unit-1", chineseSubtitle: "当前中文", englishSubtitle: nil)
        XCTAssertEqual(ListeningLiveActivityCoordinator.boundedState(input), input)
        var invalid = input
        invalid.position = .nan
        XCTAssertNil(ListeningLiveActivityCoordinator.boundedState(invalid), "Invalid Codable payload must not reach ActivityKit")
    }

    func testBilingualSubtitleRoundTripKeepsMissingMappingAndCompactState() throws {
        var state = ListeningActivityAttributes.ContentState(
            title: "完整标题", speaker: "Speaker", position: 42, duration: 300,
            isPlaying: false, isWaiting: false, sampledAt: Date(), languageCode: "zh",
            subtitleID: "reviewed-unit", chineseSubtitle: "当前中文句", englishSubtitle: nil)
        let decoded = try JSONDecoder().decode(ListeningActivityAttributes.ContentState.self,
            from: JSONEncoder().encode(state))
        XCTAssertEqual(decoded.chineseSubtitle, "当前中文句")
        XCTAssertNil(decoded.englishSubtitle)
        XCTAssertEqual(decoded.compactStatusText, "暂停")
        state.isWaiting = true
        XCTAssertEqual(state.compactStatusText, "等待")
        state.isWaiting = false
        state.isPlaying = true
        XCTAssertEqual(state.compactStatusText, "播放")
        state.alignmentPhase = .matching
        XCTAssertEqual(state.compactStatusText, ListeningAlignmentPhase.matching.compactText(english: false))
    }

    func testAlignmentOverridesPausedPlaybackAndStaleOverridesListening() {
        var state = ListeningActivityAttributes.ContentState(
            title: "Sermon", speaker: "Speaker", position: 42, duration: 300,
            isPlaying: false, isWaiting: false, sampledAt: Date(), languageCode: "zh",
            alignmentPhase: .listening)
        XCTAssertEqual(state.statusText(isStale: false), "正在听现场 · 保持前台")
        XCTAssertEqual(state.statusText(isStale: true), "打开同行更新状态")
        state.alignmentPhase = .failed
        XCTAssertFalse(state.alignmentPhase!.isActive)
        XCTAssertEqual(state.statusText(isStale: false), "对齐未完成 · 打开 App")
        state.alignmentPhase = nil
        XCTAssertEqual(state.statusText(isStale: false), "已暂停")
    }

    func testPermissionInactivityDoesNotSuppressInitialListeningButLeavingDoes() {
        XCTAssertFalse(ListeningLiveActivityCoordinator.suppressesAlignmentAfterLeaving(phase: .preparing, isBackground: false))
        XCTAssertTrue(ListeningLiveActivityCoordinator.suppressesAlignmentAfterLeaving(phase: .preparing, isBackground: true))
        for phase in [ListeningAlignmentPhase.listening, .matching, .aligned, .unmatched, .failed] {
            XCTAssertFalse(ListeningLiveActivityCoordinator.suppressesAlignmentAfterLeaving(phase: phase, isBackground: false))
            XCTAssertTrue(ListeningLiveActivityCoordinator.suppressesAlignmentAfterLeaving(phase: phase, isBackground: false, hasPresented: true))
            XCTAssertTrue(ListeningLiveActivityCoordinator.suppressesAlignmentAfterLeaving(phase: phase, isBackground: true))
        }
    }

    func testSubtitleSnapshotLabelsExplainFreshnessInBothLanguages() {
        var state = ListeningActivityAttributes.ContentState(title: "Fixture", speaker: "", position: 0,
            duration: 300, isPlaying: true, isWaiting: false, sampledAt: Date(), languageCode: "zh")
        XCTAssertEqual(state.subtitleSnapshotLabel, "最近同步字幕")
        XCTAssertEqual(state.subtitleStaleMessage, "字幕尚未刷新，打开同行查看实时字幕。")
        state.languageCode = "en"
        XCTAssertEqual(state.subtitleSnapshotLabel, "Last synced captions")
        XCTAssertEqual(state.subtitleStaleMessage, "Captions haven't refreshed. Open Tongxing for live captions.")
    }

    func testNoMatchIsDistinctFromTechnicalFailure() {
        XCTAssertEqual(ListeningAlignmentPhase.unmatched.symbolName, "questionmark.circle")
        XCTAssertEqual(ListeningAlignmentPhase.failed.symbolName, "exclamationmark.triangle")
        XCTAssertEqual(ListeningAlignmentPhase.unmatched.statusText(english: false), "未找到匹配 · 请重试")
    }

    func testOlderPlaybackPayloadStillDecodesAndTerminalPhasesAreInactive() throws {
        let state = ListeningActivityAttributes.ContentState(
            title: "Sermon", speaker: "Speaker", position: 0, duration: 300,
            isPlaying: true, isWaiting: false, sampledAt: Date(), languageCode: "en")
        var old = try XCTUnwrap(JSONSerialization.jsonObject(with: JSONEncoder().encode(state)) as? [String: Any])
        old.removeValue(forKey: "alignmentPhase")
        old.removeValue(forKey: "subtitleID")
        old.removeValue(forKey: "chineseSubtitle")
        old.removeValue(forKey: "englishSubtitle")
        let decoded = try JSONDecoder().decode(ListeningActivityAttributes.ContentState.self,
            from: JSONSerialization.data(withJSONObject: old))
        XCTAssertNil(decoded.alignmentPhase)
        XCTAssertNil(decoded.chineseSubtitle)
        XCTAssertNil(decoded.englishSubtitle)
        XCTAssertEqual(decoded.statusText(isStale: false), "Playing")
        for phase in [ListeningAlignmentPhase.aligned, .unmatched, .cancelled, .failed] {
            XCTAssertFalse(phase.isActive)
            XCTAssertNotEqual(phase.symbolName, "mic.fill")
        }
    }
}
