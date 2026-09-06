import Foundation

public enum PlaybackTime {
    /// Stable positional notation, independent of the device's language settings.
    public static func format(_ seconds: Double) -> String {
        guard seconds.isFinite, seconds >= 0, seconds < Double(Int.max) else { return "00:00" }
        let total = Int(seconds.rounded(.down))
        if total >= 3_600 {
            return "\(total / 3_600):" + String(format: "%02d:%02d", (total / 60) % 60, total % 60)
        }
        return String(format: "%02d:%02d", total / 60, total % 60)
    }

    /// Accepts seconds, MM:SS or HH:MM:SS; rejects signs, overflow and ambiguous components.
    public static func parse(_ text: String) -> Double? {
        let value = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !value.isEmpty, value.utf8.count <= 32 else { return nil }
        let components = value.split(separator: ":", omittingEmptySubsequences: false)
        guard (1...3).contains(components.count) else { return nil }
        var total: Double = 0
        for (index, component) in components.enumerated() {
            let pattern = index == components.count - 1 ? "^[0-9]+(?:\\.[0-9]+)?$" : "^[0-9]+$"
            guard component.range(of: pattern, options: .regularExpression) != nil,
                  let number = Double(component), number.isFinite,
                  (index == 0 || number < 60) else { return nil }
            total = total * 60 + number
        }
        return total.isFinite && total < Double(Int.max) ? total : nil
    }
}

/// Single-step undo belongs to the current track; reset when changing media identity.
public struct SeekHistory: Sendable, Equatable {
    private var previousPosition: Double?
    public var canUndo: Bool { previousPosition != nil }
    public init() {}

    public mutating func seek(from: Double, to: Double, duration: Double) -> Double? {
        guard from.isFinite, from >= 0, from <= duration, to.isFinite,
              duration.isFinite, duration > 0 else { return nil }
        let target = min(max(to, 0), duration)
        guard target != from else { return target }
        previousPosition = from
        return target
    }

    public mutating func undo(duration: Double) -> Double? {
        guard duration.isFinite, duration > 0, let previousPosition else { return nil }
        self.previousPosition = nil
        return min(max(previousPosition, 0), duration)
    }

    public mutating func reset() { previousPosition = nil }
}
