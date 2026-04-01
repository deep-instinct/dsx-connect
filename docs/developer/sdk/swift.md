# Swift SDK Calls

This page documents the callable surface of the Swift DSXA SDK.

Source: `dsxa_swift/Sources/DSXASDK/DSXASDK.swift`

## Client

## `DSXAClient`

Initializer:

```swift
DSXAClient(
    baseURL: String,
    authToken: String? = nil,
    protectedEntity: Int = 1,
    verifyTLS: Bool = true,
    timeoutSeconds: TimeInterval = 120.0
)
```

`DSXAClient.ScanMode` values:
- `.binary`
- `.base64`

---

## Core scan calls

All calls are async and throw.

## `scanFile(at:mode:metadata:password:)`

Reads file from disk and scans it.

## `scanBinary(data:metadata:password:)`

Scans raw bytes via `POST /scan/binary/v2`.

## `scanBase64(data:metadata:password:)`

Scans base64 bytes via `POST /scan/base64/v2`.

## `scanHash(_:metadata:)`

Scans hash via `POST /scan/by_hash`.

## `scanByPath(_:metadata:password:)`

Starts scan-by-path workflow via `GET /scan/by_path` with `Stream-Path` header.

---

## Typical usage

## Disk file scan

```swift
import Foundation
import DSXASDK

let client = try DSXAClient(
    baseURL: "http://127.0.0.1:5000",
    authToken: nil,
    verifyTLS: false
)

let fileURL = URL(fileURLWithPath: "/path/to/file.pdf")
let response = try await client.scanFile(
    at: fileURL,
    mode: .binary,
    metadata: "upload-id=1234",
    password: nil
)
print(response.verdict.rawValue, response.scanGuid)
```

## Upload bytes (backend flow)

```swift
import Foundation
import DSXASDK

func scanUploadedData(_ data: Data) async throws -> DSXAScanResponse {
    let client = try DSXAClient(baseURL: "http://127.0.0.1:5000", verifyTLS: false)
    return try await client.scanBinary(data: data, metadata: "source=web-upload", password: nil)
}
```

## Bounded concurrency pattern

Use a `TaskGroup` with a max in-flight limit in your app/service layer.

```swift
import Foundation
import DSXASDK

func scanMany(fileURLs: [URL], maxConcurrent: Int = 8) async -> [Result<DSXAScanResponse, Error>] {
    var results: [Result<DSXAScanResponse, Error>] = []
    var nextIndex = 0

    await withTaskGroup(of: Result<DSXAScanResponse, Error>.self) { group in
        let initial = min(maxConcurrent, fileURLs.count)
        for _ in 0..<initial {
            let file = fileURLs[nextIndex]
            nextIndex += 1
            group.addTask {
                do {
                    let client = try DSXAClient(baseURL: "http://127.0.0.1:5000", verifyTLS: false)
                    return .success(try await client.scanFile(at: file))
                } catch {
                    return .failure(error)
                }
            }
        }

        for await r in group {
            results.append(r)
            if nextIndex < fileURLs.count {
                let file = fileURLs[nextIndex]
                nextIndex += 1
                group.addTask {
                    do {
                        let client = try DSXAClient(baseURL: "http://127.0.0.1:5000", verifyTLS: false)
                        return .success(try await client.scanFile(at: file))
                    } catch {
                        return .failure(error)
                    }
                }
            }
        }
    }
    return results
}
```

---

## Notes

- There is no single SDK \"batch endpoint\" call; batching is done by app-level concurrency.
- SDK uses shared `URLSession` pools for connection reuse.
