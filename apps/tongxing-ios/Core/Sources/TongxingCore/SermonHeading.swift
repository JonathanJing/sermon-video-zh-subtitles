import Foundation

/// Display metadata only. Source titles and release identities remain unchanged.
public struct SermonHeading: Sendable, Equatable {
    /// Display fallback only; stable identifiers remain available for addressing.
    public static func displayTitle(_ title: String?, pageID: String, date: String, fallback: String) -> String {
        let value = title?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        guard !value.isEmpty, value != pageID, UUID(uuidString: value) == nil,
              !value.hasPrefix("resi-"), !value.hasPrefix("https://"),
              ![".mp3", ".m4a", ".wav"].contains(where: { value.lowercased().hasSuffix($0) }) else {
            return date.isEmpty ? fallback : "\(date) · \(fallback)"
        }
        return value
    }
    public let title: String
    public let series: String?
    public let speaker: String?
    public let scripture: String?
    public let edition: String?

    public init(title: String, series: String? = nil, speaker: String? = nil, scripture: String? = nil,
                displayEdition: String? = nil) {
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
        self.scripture = nonempty(scripture)
        self.edition = nonempty(displayEdition) ?? edition
    }

    /// The series line, shown once. A title published as "series · title" (the approved
    /// podcast format) keeps its wording, so the separate series line is left out. Web and
    /// the static page follow the same rule (`headingLines` in listening-web/catalog.mjs).
    public var displayedSeries: String? {
        guard let series, title.hasPrefix(series + " · ") else { return series }
        return nil
    }

    public func details(date: String) -> String {
        [date, speaker].compactMap { $0 }.joined(separator: " · ")
    }
}
