import CryptoKit
import Foundation

public enum ContentStorageError: Error, LocalizedError, Equatable, Sendable {
    case invalidURL
    case httpStatus(Int)
    case invalidResponse
    case tooLarge(limit: Int64)
    case emptyFile
    case truncated(expected: Int64, actual: Int64)
    case checksumMismatch
    case invalidDownloadReference

    public var errorDescription: String? {
        switch self {
        case .invalidURL: return "内容地址不符合安全要求。"
        case .httpStatus(let status): return "内容服务器返回错误（\(status)）。"
        case .invalidResponse: return "内容服务器的响应无效。"
        case .tooLarge: return "内容文件超过允许的大小。"
        case .emptyFile: return "下载的文件为空。"
        case .truncated: return "文件未完整下载，请重试。"
        case .checksumMismatch: return "音频完整性校验失败，请重新下载。"
        case .invalidDownloadReference: return "离线音频记录无效，请重新下载。"
        }
    }
}

enum ContentOrigin {
    static func validateHTTPS(_ url: URL) throws {
        guard url.scheme?.lowercased() == "https", let host = url.host, !host.isEmpty,
              url.user == nil, url.password == nil, url.fragment == nil else {
            throw ContentStorageError.invalidURL
        }
    }

    static func isSame(_ lhs: URL, _ rhs: URL) -> Bool {
        lhs.scheme?.lowercased() == "https" && rhs.scheme?.lowercased() == "https"
            && lhs.host?.lowercased() == rhs.host?.lowercased()
            && (lhs.port ?? 443) == (rhs.port ?? 443)
            && rhs.user == nil && rhs.password == nil && rhs.fragment == nil
    }
}

struct HTTPFileReceipt: Sendable {
    let byteCount: Int64
    let sha256: String
}

/// Foreground transfer. Each response chunk goes to an app-owned temporary file;
/// size checks happen before writing. The injected session remains caller-owned.
final class HTTPFileTransfer: NSObject, URLSessionDataDelegate, @unchecked Sendable {
    private let session: URLSession
    private let requestURL: URL
    private let temporaryURL: URL
    private let maximumBytes: Int64
    private let lock = NSLock()
    private var task: URLSessionDataTask?
    private var handle: FileHandle?
    private var continuation: CheckedContinuation<HTTPFileReceipt, Error>?
    private var failure: Error?
    private var cancelled = false
    private var received: Int64 = 0
    private var expectedLength: Int64 = -1
    private var acceptedResponse = false
    private var digest = SHA256()

    init(session: URLSession, url: URL, temporaryURL: URL, maximumBytes: Int64) {
        self.session = session
        self.requestURL = url
        self.temporaryURL = temporaryURL
        self.maximumBytes = maximumBytes
    }

    func run() async throws -> HTTPFileReceipt {
        try ContentOrigin.validateHTTPS(requestURL)
        return try await withTaskCancellationHandler {
            try Task.checkCancellation()
            return try await withCheckedThrowingContinuation { continuation in
                start(continuation)
            }
        } onCancel: {
            self.cancel()
        }
    }

    private func start(_ continuation: CheckedContinuation<HTTPFileReceipt, Error>) {
        lock.lock()
        guard !cancelled else {
            lock.unlock()
            continuation.resume(throwing: CancellationError())
            return
        }
        do {
            guard maximumBytes > 0 else { throw ContentStorageError.tooLarge(limit: maximumBytes) }
            guard FileManager.default.createFile(atPath: temporaryURL.path, contents: nil) else {
                throw CocoaError(.fileWriteUnknown)
            }
            handle = try FileHandle(forWritingTo: temporaryURL)
            self.continuation = continuation
            var request = URLRequest(url: requestURL)
            request.cachePolicy = .reloadIgnoringLocalCacheData
            request.timeoutInterval = 60
            request.setValue("identity", forHTTPHeaderField: "Accept-Encoding")
            let task = session.dataTask(with: request)
            task.delegate = self
            self.task = task
            lock.unlock()
            task.resume()
        } catch {
            lock.unlock()
            continuation.resume(throwing: error)
        }
    }

    private func cancel() {
        lock.lock()
        cancelled = true
        failure = CancellationError()
        let task = task
        lock.unlock()
        task?.cancel()
    }

    func urlSession(_ session: URLSession, task: URLSessionTask,
                    willPerformHTTPRedirection response: HTTPURLResponse,
                    newRequest request: URLRequest,
                    completionHandler: @escaping (URLRequest?) -> Void) {
        guard let url = request.url, ContentOrigin.isSame(requestURL, url) else {
            lock.lock()
            failure = ContentStorageError.invalidURL
            lock.unlock()
            completionHandler(nil)
            task.cancel()
            return
        }
        completionHandler(request)
    }

    func urlSession(_ session: URLSession, dataTask: URLSessionDataTask,
                    didReceive response: URLResponse,
                    completionHandler: @escaping (URLSession.ResponseDisposition) -> Void) {
        lock.lock()
        do {
            guard let response = response as? HTTPURLResponse, let url = response.url,
                  ContentOrigin.isSame(requestURL, url) else {
                throw ContentStorageError.invalidResponse
            }
            guard response.statusCode == 200 else {
                throw ContentStorageError.httpStatus(response.statusCode)
            }
            guard response.expectedContentLength <= maximumBytes else {
                throw ContentStorageError.tooLarge(limit: maximumBytes)
            }
            // Content-Length describes transferred bytes; compressed HTTP bodies
            // could otherwise cause a misleading comparison with decoded chunks.
            let encoding = response.value(forHTTPHeaderField: "Content-Encoding")?.lowercased()
            expectedLength = (encoding == nil || encoding == "identity")
                ? response.expectedContentLength : -1
            acceptedResponse = true
            lock.unlock()
            completionHandler(.allow)
        } catch {
            failure = error
            lock.unlock()
            completionHandler(.cancel)
        }
    }

    func urlSession(_ session: URLSession, dataTask: URLSessionDataTask, didReceive data: Data) {
        lock.lock()
        guard failure == nil else { lock.unlock(); return }
        do {
            guard acceptedResponse else { throw ContentStorageError.invalidResponse }
            guard Int64(data.count) <= maximumBytes - received else {
                throw ContentStorageError.tooLarge(limit: maximumBytes)
            }
            try handle?.write(contentsOf: data)
            digest.update(data: data)
            received += Int64(data.count)
            lock.unlock()
        } catch {
            failure = error
            lock.unlock()
            dataTask.cancel()
        }
    }

    func urlSession(_ session: URLSession, task: URLSessionTask, didCompleteWithError error: Error?) {
        lock.lock()
        do { try handle?.close() } catch { if failure == nil { failure = error } }
        handle = nil
        let continuation = continuation
        self.continuation = nil
        self.task = nil
        let result: Result<HTTPFileReceipt, Error>
        if let error = failure ?? error {
            result = .failure(error)
        } else if !acceptedResponse {
            result = .failure(ContentStorageError.invalidResponse)
        } else if received == 0 {
            result = .failure(ContentStorageError.emptyFile)
        } else if expectedLength >= 0 && received != expectedLength {
            result = .failure(ContentStorageError.truncated(expected: expectedLength, actual: received))
        } else {
            result = .success(HTTPFileReceipt(byteCount: received,
                sha256: digest.finalize().map { String(format: "%02x", $0) }.joined()))
        }
        lock.unlock()
        continuation?.resume(with: result)
    }
}
