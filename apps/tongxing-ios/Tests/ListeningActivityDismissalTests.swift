import ActivityKit
import XCTest
@testable import Tongxing

#if DEBUG
/// Explicit opt-in verifies real ActivityKit ownership, not visual acceptance.
@MainActor
final class ListeningActivityDismissalTests: XCTestCase {
    private typealias ListeningActivity = Activity<ListeningActivityAttributes>

    func testAlignmentCannotStartOrdinaryActivityWithoutPlaybackOrTransaction() async throws {
        try requireOptIn()
        let title = "Synthetic activity \(UUID().uuidString)"
        let coordinator = ListeningLiveActivityCoordinator(allowSystemActivitiesInTests: true)
        defer { coordinator.end() }
        coordinator.update(title: title, speaker: "Synthetic fixture", position: 42,
                           duration: 300, isPlaying: false, sourceKey: UUID().uuidString,
                           alignmentPhase: .listening)
        try await eventually { !coordinator.isReconcilingForTesting }
        XCTAssertFalse(ListeningActivity.activities.contains { $0.content.state.title == title })
    }

    func testPlaybackActivityDoesNotCarryAlignmentFeedbackAndClearEndsIt() async throws {
        try requireOptIn()
        let title = "Synthetic activity \(UUID().uuidString)"
        let coordinator = ListeningLiveActivityCoordinator(allowSystemActivitiesInTests: true)
        defer { coordinator.end() }
        coordinator.update(title: title, speaker: "Synthetic fixture", position: 42,
                           duration: 300, isPlaying: true, sourceKey: UUID().uuidString,
                           alignmentPhase: .unmatched)
        try await eventually { ListeningActivity.activities.contains { $0.content.state.title == title } }
        let activity = try XCTUnwrap(ListeningActivity.activities.first { $0.content.state.title == title })
        XCTAssertNil(activity.content.state.alignmentPhase)
        coordinator.end()
        try await eventually { activity.activityState == .ended || activity.activityState == .dismissed }
    }

    func testExplicitForegroundTransactionUpdatesFromListeningToNoMatch() async throws {
        try requireOptIn()
        guard #available(iOS 18.0, *) else { throw XCTSkip("Transient presentation requires iOS 18") }
        let title = "Synthetic foreground \(UUID().uuidString)"
        let source = UUID().uuidString, transaction = UUID()
        let coordinator = ListeningLiveActivityCoordinator(allowSystemActivitiesInTests: true)
        defer { coordinator.end() }
        coordinator.update(title: title, speaker: "Synthetic fixture", position: 42,
                           duration: 300, isPlaying: false, sourceKey: source,
                           alignmentPhase: .preparing, alignmentSessionID: transaction)
        try await eventually { !coordinator.isReconcilingForTesting }
        XCTAssertFalse(ListeningActivity.activities.contains { $0.content.state.title == title })
        coordinator.update(title: title, speaker: "Synthetic fixture", position: 42,
                           duration: 300, isPlaying: false, sourceKey: source,
                           alignmentPhase: .listening, alignmentSessionID: transaction)
        try await eventually { ListeningActivity.activities.contains { $0.content.state.title == title } }
        let activity = try XCTUnwrap(ListeningActivity.activities.first { $0.content.state.title == title })
        XCTAssertEqual(activity.content.state.alignmentPhase, .listening)
        coordinator.update(title: title, speaker: "Synthetic fixture", position: 42,
                           duration: 300, isPlaying: false, sourceKey: source,
                           alignmentPhase: .unmatched, alignmentSessionID: transaction)
        try await eventually { activity.content.state.alignmentPhase == .unmatched }
        XCTAssertEqual(activity.content.state.alignmentPhase?.symbolName, "questionmark.circle")
        coordinator.end()
        try await eventually { activity.activityState == .ended || activity.activityState == .dismissed }
    }

    private func requireOptIn() throws {
        try XCTSkipUnless(ProcessInfo.processInfo.environment["TONGXING_ACTIVITY_DISMISSAL_SMOKE"] == "1",
                          "Explicit opt-in required for real ActivityKit")
    }

    private func eventually(_ predicate: () -> Bool) async throws {
        for _ in 0..<100 {
            if predicate() { return }
            try await Task.sleep(for: .milliseconds(25))
        }
        throw NSError(domain: "ListeningActivityDismissalTests", code: 1,
                      userInfo: [NSLocalizedDescriptionKey: "Activity lifecycle condition timed out"])
    }
}
#endif
