import Foundation

/// A guide is bound to the exact weekly page ID from the published catalog.
struct WeeklyGuide: Decodable, Equatable, Identifiable {
    let id: String
    let week: Int
    let title: String
    let scripture: String
    let sections: [WeeklyGuideSection]
}

struct WeeklyGuideSection: Decodable, Equatable, Identifiable {
    let id: String
    let title: String
    let subtitle: String
    let symbol: String
    let body: String
}

enum WeeklyGuideRepository {
    /// No fallback: missing content, another locale, or another page never shows
    /// the current week's guide as if it belonged to the selected sermon.
    static func load(pageID: String?, locale: String) -> WeeklyGuide? {
        guard let url = Bundle.main.url(forResource: "weekly-guides", withExtension: "json"),
              let data = try? Data(contentsOf: url) else { return nil }
        return load(pageID: pageID, locale: locale, data: data)
    }

    static func load(pageID: String?, locale: String, data: Data) -> WeeklyGuide? {
        guard locale == "zh-Hans", let pageID, !pageID.isEmpty,
              let collection = try? JSONDecoder().decode(Collection.self, from: data) else { return nil }
        let matches = collection.guides.filter { $0.id == pageID }
        guard matches.count == 1, let guide = matches.first,
              guide.week > 0, !guide.sections.isEmpty,
              Set(guide.sections.map(\.id)).count == guide.sections.count else { return nil }
        return guide
    }

    private struct Collection: Decodable {
        let guides: [WeeklyGuide]
    }
}
