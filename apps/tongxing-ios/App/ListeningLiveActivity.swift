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
    // end(.after) ends the session but leaves its Lock Screen card visible.
    // Retain it separately so a replacement can dismiss that card first.
    private var endingActivity: ListeningActivity?
    private var pending: Snapshot?
    private var lastPublished: Snapshot?
    private var revision: UInt64 = 0
    private var worker: Task<Void, Never>?
    private var stateObserver: Task<Void, Never>?
    private var cleanedPreviousLaunch = false
    private var suppressedSourceKey: String?
    private var lastRequestAttempt = Date.distantPast
    private var lastRequestSourceKey: String?
    private var alignmentActivity: ListeningActivity?
    private var alignmentSourceKey: String?
    private var alignmentSessionID: UUID?
    private var alignmentDismissed = false
    private var capturedAlignment: (sessionID: UUID, sourceKey: String)?
    private var suppressedAlignment: (sessionID: UUID, sourceKey: String)?
    #if DEBUG
    private var applicationStateOverride: UIApplication.State?
    func setApplicationStateForTesting(_ state: UIApplication.State?) { applicationStateOverride = state }
    #endif
    private var applicationState: UIApplication.State {
        #if DEBUG
        if let applicationStateOverride { return applicationStateOverride }
        #endif
        return UIApplication.shared.applicationState
    }
    private let logger = Logger(subsystem: "Tongxing", category: "LiveActivity")
    #endif

    init(enabled: Bool = true, allowSystemActivitiesInTests: Bool = false) {
        #if os(iOS) && canImport(ActivityKit)
        // Automated player tests must not create system activities as a side effect.
        var isTest = ProcessInfo.processInfo.environment["TONGXING_TEST_HOST"] == "1"
            || ProcessInfo.processInfo.arguments.contains("--ui-testing")
        #if DEBUG
        if allowSystemActivitiesInTests { isTest = false }
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
                alignmentSessionID: UUID? = nil, subtitleID: String? = nil,
                chineseSubtitle: String? = nil, englishSubtitle: String? = nil) {
        #if os(iOS) && canImport(ActivityKit)
        guard enabled else { return }
        guard position.isFinite, duration.isFinite, duration > 0, duration <= 24 * 3600,
              !sourceKey.isEmpty, position < duration - 0.05 else {
            end()
            return
        }
        let key = SHA256.hash(data: Data(sourceKey.utf8)).map { String(format: "%02x", $0) }.joined()
        guard let state = Self.boundedState(ListeningActivityAttributes.ContentState(
            title: title, speaker: speaker, position: max(0, position), duration: duration,
            isPlaying: isPlaying, isWaiting: isWaiting, sampledAt: Date(),
            languageCode: languageCode.hasPrefix("en") ? "en" : "zh", alignmentPhase: alignmentPhase,
            subtitleID: subtitleID, chineseSubtitle: chineseSubtitle, englishSubtitle: englishSubtitle
        )) else { end(); return }
        if suppressedAlignment?.sessionID != alignmentSessionID || suppressedAlignment?.sourceKey != key {
            suppressedAlignment = nil
        }
        if let alignmentSessionID, let alignmentPhase, applicationState != .active,
           Self.suppressesAlignmentAfterLeaving(phase: alignmentPhase, isBackground: applicationState == .background) {
            // Retain a departure even when a background snapshot is coalesced.
            suppressedAlignment = (alignmentSessionID, key)
            capturedAlignment = nil
        }
        // Observe real capture synchronously before coalescing ActivityKit writes.
        // A fast matcher may replace listening/matching with its result before
        // the worker runs; that result must still be eligible for presentation.
        if alignmentPhase == nil || alignmentPhase == .preparing || capturedAlignment?.sourceKey != key {
            capturedAlignment = nil
        }
        if applicationState == .active, suppressedAlignment == nil,
           (alignmentPhase == .listening || alignmentPhase == .matching), let alignmentSessionID {
            capturedAlignment = (alignmentSessionID, key)
        }
        enqueue(Snapshot(sourceKey: key, state: state, alignmentSessionID: alignmentSessionID))
        #endif
    }

    /// Call on clear, failure, or teardown. A later explicit playback may start anew.
    func end() {
        #if os(iOS) && canImport(ActivityKit)
        guard enabled else { return }
        capturedAlignment = nil
        suppressedAlignment = nil
        suppressedSourceKey = nil
        lastRequestSourceKey = nil
        lastRequestAttempt = .distantPast
        guard pending != nil || activity != nil || endingActivity != nil || !cleanedPreviousLaunch else { return }
        enqueue(nil)
        #endif
    }

    #if os(iOS) && canImport(ActivityKit)
    #if DEBUG
    var endingActivityIDForTesting: String? { endingActivity?.id }
    var isReconcilingForTesting: Bool { worker != nil }
    #endif

    deinit {
        worker?.cancel()
        stateObserver?.cancel()
        if let alignmentActivity {
            Task { await alignmentActivity.end(nil, dismissalPolicy: .immediate) }
        }
        if let endingActivity {
            Task { await endingActivity.end(nil, dismissalPolicy: .immediate) }
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
        }
        // Alignment feedback belongs only to a foreground transient activity.
        // Older systems keep the in-app feedback instead of a Lock Screen fallback.
        do {
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

        if let endingActivity,
           endingActivity.attributes.sourceKey != snapshot.sourceKey
            || snapshot.state.isPlaying {
            await dismissEndingActivity()
        }
        guard token == revision, !Task.isCancelled else { return }

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
            guard snapshot.state.isPlaying, suppressedSourceKey != snapshot.sourceKey,
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
                lastPublished = snapshot
                observeState(of: created)
            } catch {
                // Live Activities are optional; denial or system limits must not
                // replace the player's real error/status or interrupt playback.
                logger.error("Playback Live Activity request failed: \(String(describing: error), privacy: .public)")
            }
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
        guard snapshot.alignmentSessionID != nil else { return }
        let applicationState = self.applicationState
        let departed = suppressedAlignment?.sessionID == snapshot.alignmentSessionID
            && suppressedAlignment?.sourceKey == snapshot.sourceKey
        guard applicationState == .active && !departed else {
            if let current = alignmentActivity {
                alignmentActivity = nil
                await current.end(nil, dismissalPolicy: .immediate)
            }
            // Do not reopen this task when the user returns to the app.
            if departed || Self.suppressesAlignmentAfterLeaving(phase: phase, isBackground: applicationState == .background) {
                alignmentDismissed = true
            }
            return
        }
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
        let observedCapture = capturedAlignment?.sessionID == snapshot.alignmentSessionID
            && capturedAlignment?.sourceKey == snapshot.sourceKey
        let resultAfterCapture = observedCapture && (phase == .aligned || phase == .unmatched || phase == .failed)
        guard phase == .listening || phase == .matching || resultAfterCapture,
              !alignmentDismissed else { return }
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
            || old.subtitleID != new.subtitleID || old.chineseSubtitle != new.chineseSubtitle || old.englishSubtitle != new.englishSubtitle
            || old.alignmentPhase != new.alignmentPhase
            || old.isPlaying != new.isPlaying || old.isWaiting != new.isWaiting
            || abs(old.duration - new.duration) > 0.2 || abs(expectedPosition - new.position) > 0.2
            || (new.isPlaying && elapsed >= 15)
    }

    private func content(for state: ListeningActivityAttributes.ContentState) -> ActivityContent<ListeningActivityAttributes.ContentState> {
        // If the app stops reporting while playing, show a stale message instead
        // of indefinitely projecting progress from the last reported position.
        ActivityContent(state: state, staleDate: state.alignmentPhase?.isActive == true || state.isWaiting ? state.sampledAt.addingTimeInterval(15)
                        : state.isPlaying ? state.sampledAt.addingTimeInterval(45) : nil,
                        relevanceScore: state.alignmentPhase == nil ? 50 : 100)
    }

    private func endCurrent() async {
        stateObserver?.cancel()
        stateObserver = nil
        await dismissEndingActivity()
        guard let previous = activity else { return }
        activity = nil
        await finish(previous)
    }

    private func dismissEndingActivity() async {
        guard let previous = endingActivity else { return }
        endingActivity = nil
        // Preserve the final content while removing the old card immediately.
        await previous.end(nil, dismissalPolicy: .immediate)
    }

    private func finish(_ previous: ListeningActivity) async {
        var stopped = previous.content.state
        stopped.isPlaying = false
        stopped.isWaiting = false
        stopped.alignmentPhase = nil
        await previous.end(ActivityContent(state: stopped, staleDate: nil), dismissalPolicy: .immediate)
    }

    // A permission alert during preparation is transient inactivity, not a
    // dismissal of a listening task that has already started.
    nonisolated static func suppressesAlignmentAfterLeaving(phase: ListeningAlignmentPhase,
                                                           isBackground: Bool) -> Bool {
        isBackground || phase != .preparing
    }

    /// Pure payload preparation shared with tests. Count the JSON representation,
    /// including escaping, rather than raw UTF-8 (control scalars can expand 6x).
    /// The final 3500-byte ceiling leaves room for the hashed source attributes.
    nonisolated static func boundedState(_ input: ListeningActivityAttributes.ContentState)
        -> ListeningActivityAttributes.ContentState? {
        let encoder = JSONEncoder()
        func text(_ value: String, budget: Int) -> String {
            if let data = try? encoder.encode(value), data.count <= budget { return value }
            let characters = Array(value)
            var lower = 0, upper = characters.count
            while lower < upper {
                let mid = lower + (upper - lower + 1) / 2
                let candidate = String(characters.prefix(mid))
                if let data = try? encoder.encode(candidate), data.count <= budget { lower = mid }
                else { upper = mid - 1 }
            }
            return String(characters.prefix(lower))
        }
        var state = input
        state.title = text(input.title, budget: 450)
        state.speaker = text(input.speaker, budget: 200)
        state.subtitleID = input.subtitleID.map { text($0, budget: 160) }
        state.chineseSubtitle = input.chineseSubtitle.map { text($0, budget: 950) }
        state.englishSubtitle = input.englishSubtitle.map { text($0, budget: 950) }
        state.languageCode = text(input.languageCode, budget: 40)
        guard let encoded = try? encoder.encode(state), encoded.count <= 3500 else { return nil }
        return state
    }
    #endif
}
