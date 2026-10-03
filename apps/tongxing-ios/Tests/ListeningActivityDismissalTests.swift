import ActivityKit
import XCTest
@testable import Tongxing

#if DEBUG
/// Explicit opt-in uses real ActivityKit on the ordinary iOS 17 path.
/// Activity ownership checks do not establish Lock Screen visual acceptance.
@MainActor
final class ListeningActivityDismissalTests: XCTestCase {
    private typealias ListeningActivity = Activity<ListeningActivityAttributes>

    func testImmediateAlignmentRetryReleasesRetainedEndingActivity() async throws {
        try await checkReplacement(isPlaying: false)
    }

    func testPlaybackReleasesRetainedEndingActivity() async throws {
        try await checkReplacement(isPlaying: true)
    }

    func testClearReleasesRetainedEndingActivity() async throws {
        let (coordinator, title, source) = try await pausedAlignmentResult()
        defer { coordinator.end() }
        // An unchanged terminal snapshot must keep the delayed result owned.
        coordinator.update(title: title, speaker: "Synthetic fixture", position: 42,
                           duration: 300, isPlaying: false, sourceKey: source, alignmentPhase: .failed)
        try await eventually { !coordinator.isReconcilingForTesting }
        XCTAssertNotNil(coordinator.endingActivityIDForTesting)
        coordinator.end()
        try await eventually { coordinator.endingActivityIDForTesting == nil }
    }

    private func checkReplacement(isPlaying: Bool) async throws {
        let (coordinator, title, source) = try await pausedAlignmentResult()
        defer { coordinator.end() }
        let previous = try XCTUnwrap(coordinator.endingActivityIDForTesting)
        coordinator.update(title: title, speaker: "Synthetic fixture", position: 42,
                           duration: 300, isPlaying: isPlaying, sourceKey: source,
                           alignmentPhase: isPlaying ? nil : .listening)
        try await eventually {
            ListeningActivity.activities.contains { $0.content.state.title == title && $0.id != previous }
        }
        XCTAssertNil(coordinator.endingActivityIDForTesting,
                     "Replacement must dismiss and release the previous ended card first")
    }

    private func pausedAlignmentResult() async throws -> (ListeningLiveActivityCoordinator, String, String) {
        try XCTSkipUnless(ProcessInfo.processInfo.environment["TONGXING_ACTIVITY_DISMISSAL_SMOKE"] == "1",
                          "Explicit opt-in required for real ActivityKit")
        if #available(iOS 18.0, *) { throw XCTSkip("Regression covers the ordinary iOS 17 alignment path") }
        let title = "Synthetic activity \(UUID().uuidString)"
        let source = UUID().uuidString
        let coordinator = ListeningLiveActivityCoordinator(allowSystemActivitiesInTests: true)
        coordinator.update(title: title, speaker: "Synthetic fixture", position: 42,
                           duration: 300, isPlaying: false, sourceKey: source, alignmentPhase: .listening)
        try await eventually { ListeningActivity.activities.contains { $0.content.state.title == title } }
        coordinator.update(title: title, speaker: "Synthetic fixture", position: 42,
                           duration: 300, isPlaying: false, sourceKey: source, alignmentPhase: .failed)
        try await eventually {
            coordinator.endingActivityIDForTesting != nil && !coordinator.isReconcilingForTesting
        }
        return (coordinator, title, source)
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
