import SwiftUI
import TongxingCore
import TongxingInfrastructure
#if os(iOS)
import UIKit
#else
import AppKit
#endif

/// Announcement discovery never selects a page or changes the shared player.
@MainActor
final class WeeklyUpdates: ObservableObject {
    @Published private(set) var announcement: WeeklyAnnouncement?
    @Published private(set) var posterData: Data?
    @Published private(set) var posterUnavailable = false
    @Published private(set) var isNew = false
    private(set) var verifiedCatalog: MultilingualCatalog?
    private let repository: WeeklyAnnouncementRepository
    private let receiptURL: URL
    private var seen: Set<String>
    private var revision = UUID()

    init(origin: URL, support: URL, session: URLSession) {
        repository = WeeklyAnnouncementRepository(origin: origin,
            cacheDirectory: support.appendingPathComponent("WeeklyUpdates"), session: session)
        receiptURL = support.appendingPathComponent("weekly-update-seen-v1.json")
        seen = (try? JSONDecoder().decode(Set<String>.self, from: Data(contentsOf: receiptURL))) ?? []
    }

    func load(catalog: MultilingualCatalog, locale: String, pageID: String? = nil) async {
        let request = UUID()
        revision = request
        do {
            let result = try await repository.load(catalog: catalog)
            let item = result.catalog.matchedAnnouncement(pageID: pageID ?? catalog.defaultPageId,
                                                         locale: locale, catalog: catalog)
            guard revision == request, !Task.isCancelled else { return }
            if announcement != item { posterData = nil; posterUnavailable = false }
            verifiedCatalog = catalog
            announcement = item
            isNew = item.map { !seen.contains($0.deduplicationKey) } ?? false
            guard let item else { return }
            do {
                let image = try await repository.poster(for: item)
                guard revision == request, !Task.isCancelled else { return }
                // Verified bytes must also decode as an actual image.
                #if os(iOS)
                guard UIImage(data: image.data) != nil else { throw WeeklyAnnouncementError.invalidBinding }
                #else
                guard NSImage(data: image.data) != nil else { throw WeeklyAnnouncementError.invalidBinding }
                #endif
                posterData = image.data
                posterUnavailable = false
            } catch {
                guard revision == request, !Task.isCancelled else { return }
                posterData = nil
                posterUnavailable = true
            }
        } catch {
            guard revision == request, !Task.isCancelled else { return }
            announcement = nil
            posterData = nil
            isNew = false
        }
    }

    func markSeen(_ key: String? = nil) {
        guard let key = key ?? announcement?.deduplicationKey else { return }
        if let saved = try? JSONDecoder().decode(Set<String>.self, from: Data(contentsOf: receiptURL)) { seen.formUnion(saved) }
        seen.insert(key)
        isNew = announcement.map { !seen.contains($0.deduplicationKey) } ?? false
        do {
            try FileManager.default.createDirectory(at: receiptURL.deletingLastPathComponent(), withIntermediateDirectories: true)
            try JSONEncoder().encode(seen).write(to: receiptURL, options: .atomic)
        } catch { /* Leave it eligible next launch when a receipt cannot persist. */ }
    }
}

struct WeeklyUpdateCard: View {
    @ObservedObject var updates: WeeklyUpdates
    let open: () -> Void
    @ObservedObject private var localization = AppLocalization.shared
    var body: some View {
        if let item = updates.announcement, updates.isNew {
            HStack(alignment: .top, spacing: 12) {
                Button(action: open) {
                    HStack(spacing: 12) {
                        WeeklyPosterImage(data: updates.posterData)
                            .frame(width: 64, height: 88).clipped().accessibilityHidden(true)
                        VStack(alignment: .leading, spacing: 4) {
                            Text(localization.text("本周更新")).font(.caption.weight(.semibold))
                            Text(item.title).font(.headline).multilineTextAlignment(.leading)
                            Text(localization.text("查看本周海报")).font(.subheadline)
                        }
                        Spacer(minLength: 0)
                    }
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .contentShape(Rectangle())
                }.buttonStyle(.plain).accessibilityIdentifier("weekly-update-open")
                Button { updates.markSeen() } label: {
                    Image(systemName: "xmark").frame(width: 44, height: 44)
                }.buttonStyle(.plain).accessibilityLabel(localization.text("关闭本周提示"))
                    .accessibilityIdentifier("weekly-update-dismiss")
            }
            .padding(12).background(Brand.accent.opacity(0.10), in: RoundedRectangle(cornerRadius: 20))
        }
    }
}

struct WeeklyPosterImage: View {
    let data: Data?
    var body: some View {
        #if os(iOS)
        if let data, let image = UIImage(data: data) {
            Image(uiImage: image).resizable().scaledToFit().accessibilityValue(AppLocalization.shared.text("本周海报"))
        } else { placeholder }
        #else
        if let data, let image = NSImage(data: data) {
            Image(nsImage: image).resizable().scaledToFit().accessibilityValue(AppLocalization.shared.text("本周海报"))
        } else { placeholder }
        #endif
    }
    private var placeholder: some View {
        Image(systemName: "doc.richtext").font(.largeTitle).foregroundStyle(.secondary)
            .frame(maxWidth: .infinity, minHeight: 72)
    }
}

struct WeeklyUpdateSheet: View {
    @ObservedObject var updates: WeeklyUpdates
    @ObservedObject var model: AppModel
    @ObservedObject private var localization = AppLocalization.shared
    @Environment(\.dismiss) private var dismiss
    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 20) {
                    if let item = updates.announcement {
                        Text(item.title).font(.title.bold()).accessibilityIdentifier("weekly-update-title")
                        WeeklyPosterImage(data: updates.posterData)
                            .frame(maxWidth: .infinity).accessibilityIdentifier("weekly-update-poster")
                        if updates.posterUnavailable {
                            Text(localization.text("海报暂不可用，仍可打开本周内容。"))
                                .font(.footnote).foregroundStyle(.secondary)
                        }
                        Button(localization.text("打开本周内容")) {
                            guard let catalog = updates.verifiedCatalog,
                                  let page = try? item.matchedPage(in: catalog) else { return }
                            model.openWeeklyUpdate(page, catalog: catalog)
                            model.selectPublishedContentLanguage(item.locale)
                            dismiss()
                        }.buttonStyle(.borderedProminent).controlSize(.large)
                            .accessibilityIdentifier("weekly-update-read")
                    } else {
                        Text(localization.text("本周海报暂不可用。"))
                    }
                }.padding(24).frame(maxWidth: 600)
                    .frame(maxWidth: .infinity)
            }
            .navigationTitle(localization.text("本周海报"))
            .toolbar { ToolbarItem(placement: .confirmationAction) {
                Button(localization.text("完成")) { dismiss() }.accessibilityIdentifier("weekly-update-done")
            } }
        }.task { updates.markSeen() }
    }
}
