#if os(iOS) && canImport(ActivityKit)
import ActivityKit
import Foundation

/// Shared only by the iOS app and its widget extension. These are observations
/// from PlaybackController, never a second player or a venue synchronization clock.
struct ListeningActivityAttributes: ActivityAttributes {
    struct ContentState: Codable, Hashable {
        var title: String
        var speaker: String
        var position: Double
        var duration: Double
        var isPlaying: Bool
        var isWaiting: Bool
        var sampledAt: Date
        var languageCode: String

        var usesEnglish: Bool { languageCode.hasPrefix("en") }

        var timerInterval: ClosedRange<Date> {
            let start = sampledAt.addingTimeInterval(-position)
            return start...start.addingTimeInterval(duration)
        }

        func statusText(isStale: Bool) -> String {
            if isStale { return usesEnglish ? "Open Tongxing to update" : "打开同行更新状态" }
            if isWaiting { return usesEnglish ? "Buffering" : "正在缓冲" }
            if isPlaying { return usesEnglish ? "Playing" : "正在播放" }
            return usesEnglish ? "Paused" : "已暂停"
        }

        static func timeLabel(_ seconds: Double) -> String {
            let total = Int(max(0, seconds.isFinite ? seconds : 0).rounded(.down))
            if total >= 3600 {
                return String(format: "%d:%02d:%02d", total / 3600, (total % 3600) / 60, total % 60)
            }
            return String(format: "%02d:%02d", total / 60, total % 60)
        }
    }

    /// Hash of the source-bound playback identity; no media URL or local path.
    let sourceKey: String

    /// Opens the current app scene. It never selects a different source or plays.
    static let widgetURL = URL(string: "tongxing://listening")!
}
#endif
