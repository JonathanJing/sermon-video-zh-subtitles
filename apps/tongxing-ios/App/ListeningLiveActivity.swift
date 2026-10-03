import Foundation
import TongxingCore

#if os(iOS) && canImport(ActivityKit)
import ActivityKit
import CryptoKit
import UIKit
import OSLog
#endif

/// PlaybackController supplies every state transition and periodic observation.
/// This coordinator never starts, pauses, seeks, or otherwise controls audio.
@MainActor
final class ListeningLiveActivityCoordinator {
    #if os(iOS) && canImport(ActivityKit)
    private typealias ListeningActivity = Activity<ListeningActivityAttributes>
    private struct Snapshot {
        let sourceKey: String
        let state: ListeningActivityAttributes.ContentState
        let alignmentSessionID: UUID?
    }

    private let enabled: Bool
    private var activity: ListeningActivity?
    private var pending: Snapshot?
    private var lastPublished: Snapshot?
    private var revision: UInt64 = 0
    private var worker: Task<Void, Never>?
    private var stateObserver: Task<Void, Never>?
    private var cleanedPreviousLaunch = false
    private var suppressedSourceKey: String?
    private var lastRequestAttempt = Date.distantPast
    private var lastRequestSourceKey: String?
    private var startedForAlignment = false
    private var alignmentActivity: ListeningActivity?
    private var alignmentSourceKey: String?
    private var alignmentSessionID: UUID?
    private var alignmentDismissed = false
    private let logger = Logger(subsystem: "Tongxing", category: "LiveActivity")
    #endif

    init(enabled: Bool = true) {
        #if os(iOS) && canImport(ActivityKit)
        // Automated player tests must not create system activities as a side effect.
        var isTest = ProcessInfo.processInfo.environment["TONGXING_TEST_HOST"] == "1"
            || ProcessInfo.processInfo.arguments.contains("--ui-testing")
        #if DEBUG
        if ProcessInfo.processInfo.arguments.contains("--ui-testing-live-activity") { isTest = false }
        #endif
        self.enabled = enabled && !isTest
        if self.enabled { enqueue(nil) }
        #endif
    }

    /// Starts only for actual foreground playback. Pausing keeps a static paused
    /// activity; source change, end-of-track or end() removes the previous activity.
    /// User-dismissed activities are not recreated for the same loaded source.
    func update(title: String, speaker: String, position: Double, duration: Double,
                isPlaying: Bool, sourceKey: String, languageCode: String = "zh",
                isWaiting: Bool = false, alignmentPhase: ListeningAlignmentPhase? = nil,
                alignmentSessionID: UUID? = nil) {
        #if os(iOS) && canImport(ActivityKit)
        guard enabled else { return }
        guard position.isFinite, duration.isFinite, duration > 0, duration <= 24 * 3600,
              !sourceKey.isEmpty, position < duration - 0.05 else {
            end()
            return
        }
        let key = SHA256.hash(data: Data(sourceKey.utf8)).map { String(format: "%02x", $0) }.joined()
        let state = ListeningActivityAttributes.ContentState(
            title: boundedText(title, maximumBytes: 800), speaker: boundedText(speaker, maximumBytes: 400),
            position: max(0, position), duration: duration, isPlaying: isPlaying,
            isWaiting: isWaiting, sampledAt: Date(), languageCode: languageCode.hasPrefix("en") ? "en" : "zh", alignmentPhase: alignmentPhase
        )
        enqueue(Snapshot(sourceKey: key, state: state, alignmentSessionID: alignmentSessionID))
        #endif
    }

    /// Call on clear, failure, or teardown. A later explicit playback may start anew.
    func end() {
        #if os(iOS) && canImport(ActivityKit)
        guard enabled else { return }
        suppressedSourceKey = nil
        lastRequestSourceKey = nil
        lastRequestAttempt = .distantPast
        guard pending != nil || activity != nil || !cleanedPreviousLaunch else { return }
        enqueue(nil)
        #endif
    }

    #if os(iOS) && canImport(ActivityKit)
    deinit {
        worker?.cancel()
        stateObserver?.cancel()
        if let alignmentActivity {
            Task { await alignmentActivity.end(nil, dismissalPolicy: .immediate) }
        }
        if let activity {
            var stopped = activity.content.state
            stopped.isPlaying = false
            stopped.isWaiting = false
            stopped.alignmentPhase = nil
            let finalContent = ActivityContent(state: stopped, staleDate: nil)
            Task { await activity.end(finalContent, dismissalPolicy: .immediate) }
        }
    }

    private func enqueue(_ snapshot: Snapshot?) {
        pending = snapshot
        revision &+= 1
        guard worker == nil else { return }
        worker = Task { [weak self] in await self?.drain() }
    }

    /// Serialize ActivityKit calls and coalesce ticks. After every suspension,
    /// recheck the revision before requesting a new source's activity.
    private func drain() async {
        while !Task.isCancelled {
            let token = revision
            await reconcile(pending, token: token)
            if token == revision { break }
        }
        worker = nil
    }

    private func reconcile(_ requested: Snapshot?, token: UInt64) async {
        if !cleanedPreviousLaunch {
            cleanedPreviousLaunch = true
            // A cold launch has no verified ongoing AVPlayer session to adopt.
            for previous in ListeningActivity.activities { await finish(previous) }
        }
        guard token == revision, !Task.isCancelled else { return }
        var snapshot = requested
        if #available(iOS 18.0, *) {
            await reconcileForegroundAlignment(requested, token: token)
            guard token == revision, !Task.isCancelled else { return }
            // A separate transient presentation owns foreground alignment.
            // Keep the ordinary playback activity independent of its dismissal.
            if let requested {
                var state = requested.state
                state.alignmentPhase = nil
                snapshot = Snapshot(sourceKey: requested.sourceKey, state: state, alignmentSessionID: nil)
            }
        }
        guard let snapshot else {
            await endCurrent()
            lastPublished = nil
            suppressedSourceKey = nil
            return
        }

        if let activity, activity.attributes.sourceKey != snapshot.sourceKey {
            await endCurrent()
            lastPublished = nil
            suppressedSourceKey = nil
            lastRequestAttempt = .distantPast
        }
        guard token == revision, !Task.isCancelled else { return }

        if let activity, activity.activityState == .dismissed || activity.activityState == .ended {
            suppressedSourceKey = activity.attributes.sourceKey
            self.activity = nil
            stateObserver?.cancel()
            stateObserver = nil
        }

        guard let activity else {
            guard snapshot.state.isPlaying || snapshot.state.alignmentPhase?.isActive == true, suppressedSourceKey != snapshot.sourceKey,
                  ActivityAuthorizationInfo().areActivitiesEnabled,
                  UIApplication.shared.applicationState == .active,
                  lastRequestSourceKey != snapshot.sourceKey || Date().timeIntervalSince(lastRequestAttempt) >= 30 else { return }
            lastRequestAttempt = Date()
            lastRequestSourceKey = snapshot.sourceKey
            do {
                let created = try ListeningActivity.request(
                    attributes: ListeningActivityAttributes(sourceKey: snapshot.sourceKey),
                    content: content(for: snapshot.state), pushType: nil
                )
                self.activity = created
                startedForAlignment = !snapshot.state.isPlaying
                lastPublished = snapshot
                observeState(of: created)
            } catch {
                // Live Activities are optional; denial or system limits must not
                // replace the player's real error/status or interrupt playback.
                logger.error("Playback Live Activity request failed: \(String(describing: error), privacy: .public)")
            }
            return
        }
        if snapshot.state.isPlaying { startedForAlignment = false }
        if startedForAlignment && snapshot.state.alignmentPhase?.isActive != true && !snapshot.state.isPlaying {
            // A paused alignment-only session has ended; retain its final result
            // briefly on the Lock Screen, with no active microphone/timer symbol.
            self.activity = nil
            stateObserver?.cancel()
            stateObserver = nil
            await activity.end(content(for: snapshot.state), dismissalPolicy: .after(Date().addingTimeInterval(8)))
            lastPublished = nil
            lastRequestSourceKey = nil
            lastRequestAttempt = .distantPast
            return
        }
        guard shouldPublish(snapshot) else { return }
        await activity.update(content(for: snapshot.state))
        lastPublished = snapshot
    }

    @available(iOS 18.0, *)
    private func reconcileForegroundAlignment(_ snapshot: Snapshot?, token: UInt64) async {
        let phase = snapshot?.state.alignmentPhase
        let newTransaction = alignmentSessionID != snapshot?.alignmentSessionID
        let sourceChanged = alignmentSourceKey != snapshot?.sourceKey
        defer { alignmentSessionID = snapshot?.alignmentSessionID; alignmentSourceKey = snapshot?.sourceKey }
        if phase == nil || sourceChanged || newTransaction {
            if let previous = alignmentActivity {
                alignmentActivity = nil
                await previous.end(nil, dismissalPolicy: .immediate)
            }
            alignmentDismissed = false
        }
        guard token == revision, !Task.isCancelled else { return }
        guard let snapshot, let phase else { return }
        if let current = alignmentActivity,
           current.activityState == .dismissed || current.activityState == .ended {
            alignmentActivity = nil
            alignmentDismissed = true
        }
        if let current = alignmentActivity {
            // Terminal feedback stays active until PlaybackController clears it
            // after eight seconds; end(.after) would remove the island at once.
            await current.update(content(for: snapshot.state))
            return
        }
        // Wait for real capture-start, after the permission dialog has closed.
        // Tapping that dialog can dismiss a transient created during preparing.
        guard phase == .listening || phase == .matching, !alignmentDismissed else { return }
        guard ActivityAuthorizationInfo().areActivitiesEnabled else {
            alignmentDismissed = true
            logger.notice("Foreground alignment activity unavailable: activities disabled")
            return
        }
        guard UIApplication.shared.applicationState == .active else { return }
        do {
            alignmentActivity = try ListeningActivity.request(
                attributes: ListeningActivityAttributes(sourceKey: snapshot.sourceKey),
                content: content(for: snapshot.state), pushType: nil, style: .transient)
        } catch {
            alignmentDismissed = true
            logger.error("Foreground alignment activity request failed: \(String(describing: error), privacy: .public)")
        }
    }

    private func observeState(of activity: ListeningActivity) {
        stateObserver?.cancel()
        stateObserver = Task { [weak self] in
            for await state in activity.activityStateUpdates {
                guard !Task.isCancelled, let self, self.activity?.id == activity.id else { return }
                if state == .dismissed || state == .ended {
                    self.suppressedSourceKey = activity.attributes.sourceKey
                    self.activity = nil
                    return
                }
            }
        }
    }

    private func shouldPublish(_ snapshot: Snapshot) -> Bool {
        guard let previous = lastPublished, previous.sourceKey == snapshot.sourceKey else { return true }
        let old = previous.state, new = snapshot.state
        let elapsed = new.sampledAt.timeIntervalSince(old.sampledAt)
        let expectedPosition = old.position + (old.isPlaying ? max(0, elapsed) : 0)
        return old.title != new.title || old.speaker != new.speaker || old.languageCode != new.languageCode
            || old.alignmentPhase != new.alignmentPhase
            || old.isPlaying != new.isPlaying || old.isWaiting != new.isWaiting
            || abs(old.duration - new.duration) > 0.2 || abs(expectedPosition - new.position) > 0.2
            || (new.isPlaying && elapsed >= 15)
    }

    private func content(for state: ListeningActivityAttributes.ContentState) -> ActivityContent<ListeningActivityAttributes.ContentState> {
        // If the app stops reporting while playing, show a stale message instead
        // of indefinitely projecting progress from the last reported position.
        ActivityContent(state: state, staleDate: state.alignmentPhase?.isActive == true ? state.sampledAt.addingTimeInterval(15)
                        : state.isPlaying ? state.sampledAt.addingTimeInterval(45) : nil,
                        relevanceScore: state.alignmentPhase == nil ? 50 : 100)
    }

    private func endCurrent() async {
        stateObserver?.cancel()
        stateObserver = nil
        guard let previous = activity else { return }
        activity = nil
        await finish(previous)
    }

    private func finish(_ previous: ListeningActivity) async {
        var stopped = previous.content.state
        stopped.isPlaying = false
        stopped.isWaiting = false
        stopped.alignmentPhase = nil
        await previous.end(ActivityContent(state: stopped, staleDate: nil), dismissalPolicy: .immediate)
    }

    private func boundedText(_ value: String, maximumBytes: Int) -> String {
        var result = "", count = 0
        for character in value {
            let bytes = String(character).utf8.count
            guard count + bytes <= maximumBytes else { break }
            result.append(character)
            count += bytes
        }
        return result
    }
    #endif
}
