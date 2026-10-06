import Foundation
#if os(iOS)
import UIKit
#endif

/// A finite system assertion; expiration releases it immediately rather than
/// waiting for a network operation to react to cancellation.
@MainActor
final class DownloadBackgroundAssertion {
    typealias Begin = (@escaping @MainActor () -> Void) -> Int
    private let begin: Begin
    private let end: (Int) -> Void
    private var identifier: Int?
    private var finished = false
    private(set) var didExpire = false

    init(begin: @escaping Begin, end: @escaping (Int) -> Void) {
        self.begin = begin
        self.end = end
    }

    static func system() -> DownloadBackgroundAssertion {
        #if os(iOS)
        DownloadBackgroundAssertion(begin: { expiration in
            let id = UIApplication.shared.beginBackgroundTask(withName: "tongxing-download", expirationHandler: expiration)
            return id == .invalid ? -1 : id.rawValue
        }, end: { UIApplication.shared.endBackgroundTask(UIBackgroundTaskIdentifier(rawValue: $0)) })
        #else
        DownloadBackgroundAssertion(begin: { _ in -1 }, end: { _ in })
        #endif
    }

    func start(onExpiration: @escaping @MainActor () -> Void) {
        let id = begin { [weak self] in
            guard let self, !self.finished else { return }
            self.didExpire = true
            self.finish()
            onExpiration()
        }
        // A provider may expire synchronously, including when an assertion
        // cannot be granted. Do not retain that newly returned identifier.
        if id >= 0 {
            if didExpire { end(id) } else { identifier = id }
        }
    }

    func finish() {
        finished = true
        guard let id = identifier else { return }
        identifier = nil
        end(id)
    }
}
