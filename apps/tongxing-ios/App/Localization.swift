import Combine
import Foundation

enum AppLanguage: String, Codable, CaseIterable, Identifiable {
    case system
    case simplifiedChinese = "zh-CN"
    case english = "en"
    var id: String { rawValue }
}

enum AppReadingMode: String, Codable {
    case outline, transcript
}

/// Interface language is independent of the selected sermon and audio track.
/// The source-language catalog keys are also the Chinese fallback.
@MainActor
final class AppLocalization: ObservableObject {
    static let shared: AppLocalization = {
        #if DEBUG
        if ProcessInfo.processInfo.arguments.contains("--ui-testing"),
           let value = ProcessInfo.processInfo.environment["TONGXING_UI_TEST_RUN_ID"],
           let run = UUID(uuidString: value),
           let support = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask).first {
            return AppLocalization(preferenceURL: support.appendingPathComponent("Tongxing-UITests")
                .appendingPathComponent(run.uuidString).appendingPathComponent("ui-language-v1.json"))
        }
        #endif
        return AppLocalization()
    }()

    @Published private(set) var preference: AppLanguage
    @Published private(set) var language: AppLanguage
    @Published private(set) var storageWarning: String?
    @Published private(set) var readingMode: AppReadingMode
    @Published private(set) var readingStorageWarning: String?
    var locale: Locale { Locale(identifier: language.rawValue) }

    private struct SavedPreference: Codable {
        let version: Int
        let language: AppLanguage
    }

    private struct SavedReadingPreference: Codable {
        let version: Int
        let mode: AppReadingMode
    }

    private let preferenceURL: URL?
    private let readingPreferenceURL: URL?
    private var systemLanguageObserver: AnyCancellable?

    init(preferenceURL: URL? = nil) {
        let url = preferenceURL ?? FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)
            .first?.appendingPathComponent("Tongxing/ui-language-v1.json")
        self.preferenceURL = url
        let readingURL = url?.deletingLastPathComponent().appendingPathComponent("reading-mode-v1.json")
        self.readingPreferenceURL = readingURL
        let savedReading = readingURL.flatMap { try? Data(contentsOf: $0) }
            .flatMap { try? JSONDecoder().decode(SavedReadingPreference.self, from: $0) }
        if let savedReading, savedReading.version == 1 { self.readingMode = savedReading.mode }
        else { self.readingMode = .outline }
        let saved = url.flatMap { try? Data(contentsOf: $0) }
            .flatMap { try? JSONDecoder().decode(SavedPreference.self, from: $0) }
        let preference: AppLanguage
        if let saved, saved.version == 1 { preference = saved.language }
        else { preference = .system }
        self.preference = preference
        self.language = Self.resolve(preference, preferredLanguages: Locale.preferredLanguages)
        systemLanguageObserver = NotificationCenter.default.publisher(for: NSLocale.currentLocaleDidChangeNotification)
            .receive(on: RunLoop.main)
            .sink { [weak self] _ in self?.refreshSystemLanguage() }
    }

    func setPreference(_ preference: AppLanguage) {
        self.preference = preference
        language = Self.resolve(preference, preferredLanguages: Locale.preferredLanguages)
        do {
            guard let preferenceURL else { throw CocoaError(.fileWriteUnknown) }
            try FileManager.default.createDirectory(at: preferenceURL.deletingLastPathComponent(), withIntermediateDirectories: true)
            try JSONEncoder().encode(SavedPreference(version: 1, language: preference)).write(to: preferenceURL, options: .atomic)
            storageWarning = nil
        } catch {
            storageWarning = "语言已切换，本次偏好暂时无法保存。"
        }
    }

    func setReadingMode(_ mode: AppReadingMode) {
        readingMode = mode
        do {
            guard let readingPreferenceURL else { throw CocoaError(.fileWriteUnknown) }
            try FileManager.default.createDirectory(at: readingPreferenceURL.deletingLastPathComponent(), withIntermediateDirectories: true)
            try JSONEncoder().encode(SavedReadingPreference(version: 1, mode: mode)).write(to: readingPreferenceURL, options: .atomic)
            readingStorageWarning = nil
        } catch {
            readingStorageWarning = "阅读方式已切换，本次偏好暂时无法保存。"
        }
    }

    func refreshSystemLanguage() {
        language = Self.resolve(preference, preferredLanguages: Locale.preferredLanguages)
    }

    static func resolve(_ preference: AppLanguage, preferredLanguages: [String]) -> AppLanguage {
        guard preference == .system else { return preference }
        for identifier in preferredLanguages {
            let language = identifier.lowercased().split(separator: "-").first
            if language == "zh" { return .simplifiedChinese }
            if language == "en" { return .english }
        }
        return .english
    }

    func text(_ key: String, _ values: [String: String] = [:]) -> String {
        var result = language == .english ? Self.englishText(key) : key
        for (name, value) in values { result = result.replacingOccurrences(of: "{\(name)}", with: value) }
        return result
    }

    private static func englishText(_ key: String) -> String {
        if let translated = englishTranslation(key) { return translated }
        // Model messages remain language-neutral keys, including the few legacy
        // messages that interpolate a time or concatenate a catalog warning.
        for (prefix, template) in [("已定位 ", "已定位 {time}"), ("已返回 ", "已返回 {time}")] where key.hasPrefix(prefix) {
            guard let translated = englishTranslation(template) else { return key }
            return translated.replacingOccurrences(of: "{time}", with: String(key.dropFirst(prefix.count)))
        }
        let catalogPrefix = "当前使用上次保存的证道目录。"
        if key.hasPrefix(catalogPrefix), key != catalogPrefix, let translated = englishTranslation(catalogPrefix) {
            return translated + " " + englishText(String(key.dropFirst(catalogPrefix.count)))
        }
        let statusPrefix = "内容服务器返回错误（"
        if key.hasPrefix(statusPrefix), key.hasSuffix("）。"),
           let translated = englishTranslation("内容服务器返回错误（{status}）。") {
            let status = key.dropFirst(statusPrefix.count).dropLast(2)
            return translated.replacingOccurrences(of: "{status}", with: String(status))
        }
        return key
    }

    private static func englishTranslation(_ key: String) -> String? {
        let localized = englishBundle?.localizedString(forKey: key, value: key, table: "Localizable") ?? key
        return localized != key ? localized : previewEnglish[key] ?? readingEnglish[key]
    }

    private static let readingEnglish = [
        "阅读": "Read",
        "阅读内容": "Reading content",
        "本篇暂无大纲": "No outline is available for this sermon.",
        "阅读方式已切换，本次偏好暂时无法保存。": "Reading mode changed, but this preference could not be saved."
    ]

    private static var resourceBundle: Bundle {
        #if SWIFT_PACKAGE
        return .module
        #else
        return .main
        #endif
    }

    private static let englishBundle: Bundle? = resourceBundle.path(forResource: "en", ofType: "lproj").flatMap(Bundle.init(path:))

    /// SwiftPM copies the same String Catalog for the macOS preview. The iOS
    /// app uses Xcode's compiled localization resources from that catalog.
    private static let previewEnglish: [String: String] = {
        guard let url = resourceBundle.url(forResource: "Localizable", withExtension: "xcstrings"),
              let data = try? Data(contentsOf: url),
              let root = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any],
              let strings = root["strings"] as? [String: [String: Any]] else { return [:] }
        return strings.reduce(into: [:]) { result, item in
            guard let localizations = item.value["localizations"] as? [String: [String: Any]],
                  let unit = localizations["en"]?["stringUnit"] as? [String: String],
                  let value = unit["value"] else { return }
            result[item.key] = value
        }
    }()
}
