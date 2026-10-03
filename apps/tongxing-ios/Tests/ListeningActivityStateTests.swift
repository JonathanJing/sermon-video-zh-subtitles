import Foundation
import TongxingCore
import XCTest
@testable import Tongxing

final class ListeningActivityStateTests: XCTestCase {
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

    func testOlderPlaybackPayloadStillDecodesAndTerminalPhasesAreInactive() throws {
        let state = ListeningActivityAttributes.ContentState(
            title: "Sermon", speaker: "Speaker", position: 0, duration: 300,
            isPlaying: true, isWaiting: false, sampledAt: Date(), languageCode: "en")
        var old = try XCTUnwrap(JSONSerialization.jsonObject(with: JSONEncoder().encode(state)) as? [String: Any])
        old.removeValue(forKey: "alignmentPhase")
        let decoded = try JSONDecoder().decode(ListeningActivityAttributes.ContentState.self,
            from: JSONSerialization.data(withJSONObject: old))
        XCTAssertNil(decoded.alignmentPhase)
        XCTAssertEqual(decoded.statusText(isStale: false), "Playing")
        for phase in [ListeningAlignmentPhase.aligned, .cancelled, .failed] {
            XCTAssertFalse(phase.isActive)
            XCTAssertNotEqual(phase.symbolName, "mic.fill")
        }
    }
}
