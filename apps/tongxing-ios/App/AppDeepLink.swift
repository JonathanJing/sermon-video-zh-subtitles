import Foundation

/// A validated page + content-locale deep link.
///
/// Supported forms:
///   https://<host>/?week=<pageId>&contentLang=<locale>
///   https://<host>/pages/<pageId>/<locale>/
///   tongxing://page/<pageId>?contentLang=<locale>
///
/// Only the configured content host is accepted for HTTPS links. Page IDs and
/// locales are allow-listed here so a malformed link cannot select an arbitrary
/// page or a locale that was never published.
struct AppDeepLink: Equatable {
    enum Source: String, Equatable {
        case universalLink
        case customScheme
    }

    let pageID: String
    let locale: String?
    let source: Source

    static let supportedLocales: Set<String> = ["zh-Hans", "ko", "es", "en"]
    private static let pageIDPattern = try! NSRegularExpression(pattern: "^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")

    static func parse(_ url: URL, allowedHost: String, allowedSchemes: Set<String>) -> AppDeepLink? {
        guard let scheme = url.scheme?.lowercased() else { return nil }
        if scheme == "https" {
            guard url.host?.lowercased() == allowedHost.lowercased(),
                  url.port == nil || url.port == 443,
                  url.user == nil, url.password == nil else { return nil }
            return parseHTTPS(url)
        }
        guard allowedSchemes.map({ $0.lowercased() }).contains(scheme) else { return nil }
        return parseCustomScheme(url)
    }

    private static func parseHTTPS(_ url: URL) -> AppDeepLink? {
        let components = url.path.split(separator: "/", omittingEmptySubsequences: true).map(String.init)
        var pageID: String?
        var locale: String?
        if components.count >= 2, components[0] == "pages" {
            pageID = components[1]
            if components.count >= 3 { locale = components[2] }
        } else if components.count >= 2, components[0] == "open" {
            pageID = components[1]
        }
        let query = URLComponents(url: url, resolvingAgainstBaseURL: false)?.queryItems ?? []
        let queryPage = query.first(where: { ["week", "page", "pageId"].contains($0.name) })?.value
        let queryLocale = query.first(where: { ["contentLang", "locale"].contains($0.name) })?.value
        pageID = pageID ?? queryPage
        locale = locale ?? queryLocale
        guard let pageID, isValidPageID(pageID) else { return nil }
        return AppDeepLink(pageID: pageID, locale: canonicalLocale(locale), source: .universalLink)
    }

    private static func parseCustomScheme(_ url: URL) -> AppDeepLink? {
        let components = url.path.split(separator: "/", omittingEmptySubsequences: true).map(String.init)
        let host = url.host
        let pageID: String?
        if host?.lowercased() == "page" {
            pageID = components.first
        } else if let host, !host.isEmpty, host.lowercased() != "open" {
            pageID = host
        } else {
            pageID = components.first
        }
        guard let pageID, isValidPageID(pageID) else { return nil }
        let query = URLComponents(url: url, resolvingAgainstBaseURL: false)?.queryItems ?? []
        let locale = query.first(where: { ["contentLang", "locale"].contains($0.name) })?.value
        return AppDeepLink(pageID: pageID, locale: canonicalLocale(locale), source: .customScheme)
    }

    private static func isValidPageID(_ value: String) -> Bool {
        let range = NSRange(value.startIndex..<value.endIndex, in: value)
        return pageIDPattern.firstMatch(in: value, options: [], range: range) != nil
    }

    private static func canonicalLocale(_ value: String?) -> String? {
        guard let value else { return nil }
        if supportedLocales.contains(value) { return value }
        let lower = value.lowercased()
        if lower == "zh-hans" || lower == "zh" { return "zh-Hans" }
        return supportedLocales.first(where: { $0.lowercased() == lower })
    }
}
