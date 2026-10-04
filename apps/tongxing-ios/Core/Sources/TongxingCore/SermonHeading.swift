import Foundation

/// Display metadata only. Source titles and release identities remain unchanged.
public struct SermonHeading: Sendable, Equatable {
    public let title: String
    public let series: String?
    public let speaker: String?
    public let edition: String?

    public init(title: String, series: String? = nil, speaker: String? = nil, displayEdition: String? = nil) {
        func nonempty(_ value: String?) -> String? {
            guard let text = value?.trimmingCharacters(in: .whitespacesAndNewlines), !text.isEmpty else { return nil }
            return text
        }
        let series = nonempty(series)
        var displayed = nonempty(title) ?? title
        var edition: String?
        // Only recognized delivery suffixes; a dot inside a sermon title is meaningful.
        for suffix in ["正式播放版", "YouTube 版"] {
            if displayed.hasSuffix("｜" + suffix) {
                displayed = String(displayed.dropLast(suffix.count + 1)).trimmingCharacters(in: .whitespacesAndNewlines)
                edition = suffix
                break
            }
        }
        if let series {
            if displayed.hasSuffix(" · " + series) {
                displayed = String(displayed.dropLast(series.count + 3))
            }
        }
        self.title = nonempty(displayed) ?? title
        self.series = series
        self.speaker = nonempty(speaker)
        self.edition = nonempty(displayEdition) ?? edition
    }

    public func details(date: String) -> String {
        [date, speaker].compactMap { $0 }.joined(separator: " · ")
    }
}
