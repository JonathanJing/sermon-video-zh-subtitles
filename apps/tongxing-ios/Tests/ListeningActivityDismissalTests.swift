import ActivityKit
import TongxingCore
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

    func testFastMatchCoalescesIntermediateStatesButKeepsOneResult() async throws {
        try requireOptIn()
        guard #available(iOS 18.0, *) else { throw XCTSkip("Transient presentation requires iOS 18") }
        for result in [ListeningAlignmentPhase.aligned, .unmatched, .failed] {
            let title = "Synthetic fast result \(UUID().uuidString)"
            let source = UUID().uuidString, transaction = UUID()
            let coordinator = ListeningLiveActivityCoordinator(allowSystemActivitiesInTests: true)
            // Intentionally no suspension: capture and matching finish before
            // ActivityKit's worker gets scheduled, just as a fast local match can.
            for phase in [ListeningAlignmentPhase.preparing, .listening, .matching, result] {
                coordinator.update(title: title, speaker: "Synthetic fixture", position: 42,
                                   duration: 300, isPlaying: false, sourceKey: source,
                                   alignmentPhase: phase, alignmentSessionID: transaction)
            }
            try await eventually { ListeningActivity.activities.contains { $0.content.state.title == title } }
            let activities = ListeningActivity.activities.filter { $0.content.state.title == title }
            XCTAssertEqual(activities.count, 1)
            XCTAssertEqual(activities.first?.content.state.alignmentPhase, result)
            coordinator.end()
            try await eventually { activities.first?.activityState == .ended || activities.first?.activityState == .dismissed }
        }
    }

    func testTerminalWithoutCaptureCannotCreateForegroundFeedback() async throws {
        try requireOptIn()
        let title = "Synthetic no capture \(UUID().uuidString)"
        let coordinator = ListeningLiveActivityCoordinator(allowSystemActivitiesInTests: true)
        defer { coordinator.end() }
        coordinator.update(title: title, speaker: "Synthetic fixture", position: 42,
                           duration: 300, isPlaying: false, sourceKey: UUID().uuidString,
                           alignmentPhase: .failed, alignmentSessionID: UUID())
        try await eventually { !coordinator.isReconcilingForTesting }
        XCTAssertFalse(ListeningActivity.activities.contains { $0.content.state.title == title })
    }

    func testCoalescedBackgroundDepartureCannotReopenResult() async throws {
        try requireOptIn()
        let title = "Synthetic departure \(UUID().uuidString)"
        let source = UUID().uuidString, transaction = UUID()
        let coordinator = ListeningLiveActivityCoordinator(allowSystemActivitiesInTests: true)
        defer { coordinator.end() }
        coordinator.setApplicationStateForTesting(.active)
        for phase in [ListeningAlignmentPhase.preparing, .listening] {
            coordinator.update(title: title, speaker: "Fixture", position: 42, duration: 300,
                               isPlaying: false, sourceKey: source, alignmentPhase: phase, alignmentSessionID: transaction)
        }
        coordinator.setApplicationStateForTesting(.background)
        coordinator.update(title: title, speaker: "Fixture", position: 42, duration: 300,
                           isPlaying: false, sourceKey: source, alignmentPhase: .matching, alignmentSessionID: transaction)
        coordinator.setApplicationStateForTesting(.active)
        coordinator.update(title: title, speaker: "Fixture", position: 42, duration: 300,
                           isPlaying: false, sourceKey: source, alignmentPhase: .aligned, alignmentSessionID: transaction)
        try await eventually { !coordinator.isReconcilingForTesting }
        XCTAssertFalse(ListeningActivity.activities.contains { $0.content.state.title == title })
    }

    func testPermissionInactivityStillAllowsFirstCaptureResult() async throws {
        try requireOptIn()
        guard #available(iOS 18.0, *) else { throw XCTSkip("Transient presentation requires iOS 18") }
        let title = "Synthetic permission \(UUID().uuidString)"
        let source = UUID().uuidString, transaction = UUID()
        let coordinator = ListeningLiveActivityCoordinator(allowSystemActivitiesInTests: true)
        defer { coordinator.end() }
        coordinator.setApplicationStateForTesting(.inactive)
        coordinator.update(title: title, speaker: "Fixture", position: 42, duration: 300,
                           isPlaying: false, sourceKey: source, alignmentPhase: .preparing, alignmentSessionID: transaction)
        coordinator.setApplicationStateForTesting(.active)
        for phase in [ListeningAlignmentPhase.listening, .aligned] {
            coordinator.update(title: title, speaker: "Fixture", position: 42, duration: 300,
                               isPlaying: false, sourceKey: source, alignmentPhase: phase, alignmentSessionID: transaction)
        }
        try await eventually { ListeningActivity.activities.contains { $0.content.state.title == title } }
        XCTAssertEqual(ListeningActivity.activities.first { $0.content.state.title == title }?.content.state.alignmentPhase, .aligned)
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
