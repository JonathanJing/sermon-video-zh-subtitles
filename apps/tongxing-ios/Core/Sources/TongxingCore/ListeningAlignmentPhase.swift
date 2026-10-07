import Foundation

/// Observed transaction state, independent of microphone permission or playback.
public enum ListeningAlignmentPhase: String, Codable, Hashable, Sendable {
    case preparing, listening, matching, aligned, unmatched, cancelled, failed

    public var isActive: Bool {
        self == .preparing || self == .listening || self == .matching
    }

    public var symbolName: String {
        switch self {
        case .preparing: "hourglass"
        case .listening: "mic.fill"
        case .matching: "waveform.badge.magnifyingglass"
        case .aligned: "checkmark.circle.fill"
        case .unmatched: "questionmark.circle"
        case .cancelled: "stop.circle"
        case .failed: "exclamationmark.triangle"
        }
    }

    public func statusText(english: Bool) -> String {
        switch self {
        case .preparing: english ? "Preparing alignment" : "正在准备对齐"
        case .listening: english ? "Listening · keep app open" : "正在听现场 · 保持前台"
        case .matching: english ? "Matching on device" : "正在本机匹配"
        case .aligned: english ? "Aligned" : "已对齐"
        case .unmatched: english ? "No reliable match · try again" : "未找到匹配 · 请重试"
        case .cancelled: english ? "Alignment stopped" : "对齐已停止"
        case .failed: english ? "Alignment failed · open app" : "对齐未完成 · 打开 App"
        }
    }

    public func compactText(english: Bool) -> String {
        switch self {
        case .preparing: english ? "Wait" : "准备"
        case .listening: english ? "Listen" : "监听"
        case .matching: english ? "Match" : "匹配"
        case .aligned: english ? "Aligned" : "已对齐"
        case .unmatched: english ? "No match" : "未找到"
        case .cancelled: english ? "Stopped" : "已停止"
        case .failed: english ? "Failed" : "未完成"
        }
    }
}
