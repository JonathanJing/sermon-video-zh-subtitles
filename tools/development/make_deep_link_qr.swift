#!/usr/bin/env swift
// Generate a QR code for a Universal Link and verify it with Vision.
// Usage: swift make_deep_link_qr.swift <https-url> <output.png>
import AppKit
import CoreImage
import Foundation
import Vision

func fail(_ message: String) -> Never {
    FileHandle.standardError.write(("error: " + message + "\n").data(using: .utf8)!)
    exit(2)
}

let args = CommandLine.arguments
guard args.count == 3 else { fail("usage: make_deep_link_qr.swift <https-url> <output.png>") }
guard let url = URL(string: args[1]), url.scheme == "https", url.host != nil else {
    fail("URL must be an absolute https URL")
}
let output = URL(fileURLWithPath: args[2])
guard let message = args[1].data(using: .utf8) else { fail("cannot encode URL") }
guard let filter = CIFilter(name: "CIQRCodeGenerator") else { fail("CoreImage QR unavailable") }
filter.setValue(message, forKey: "inputMessage")
filter.setValue("H", forKey: "inputCorrectionLevel")
guard let qr = filter.outputImage else { fail("QR generation failed") }

let modules = Int(qr.extent.width)
let quiet = 4
let target = 1024
let scale = max(1, target / (modules + quiet * 2))
let pixels = (modules + quiet * 2) * scale
let colorSpace = CGColorSpaceCreateDeviceRGB()
guard let context = CGContext(data: nil, width: pixels, height: pixels, bitsPerComponent: 8,
                              bytesPerRow: 0, space: colorSpace,
                              bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue) else {
    fail("cannot create bitmap context")
}
context.setFillColor(CGColor(gray: 1, alpha: 1))
context.fill(CGRect(x: 0, y: 0, width: pixels, height: pixels))
context.interpolationQuality = .none
guard let cgQR = CIContext().createCGImage(qr, from: qr.extent) else { fail("cannot rasterize QR") }
context.draw(cgQR, in: CGRect(x: quiet * scale, y: quiet * scale,
                              width: modules * scale, height: modules * scale))
guard let image = context.makeImage() else { fail("cannot create image") }
let bitmap = NSBitmapImageRep(cgImage: image)
guard let png = bitmap.representation(using: .png, properties: [:]) else { fail("cannot encode PNG") }
try png.write(to: output)

let request = VNDetectBarcodesRequest()
request.symbologies = [.qr]
let handler = VNImageRequestHandler(cgImage: image, options: [:])
try handler.perform([request])
let payloads = (request.results ?? []).compactMap(\.payloadStringValue)
guard payloads == [args[1]] else { fail("decoded payload mismatch: \(payloads)") }
let receipt: [String: Any] = [
    "schemaVersion": "tongxing-deep-link-qr-v1",
    "url": args[1],
    "output": output.path,
    "pixels": pixels,
    "modules": modules,
    "quietZoneModules": quiet,
    "errorCorrection": "H",
    "decodedPayload": payloads[0],
    "encoder": "CoreImage CIQRCodeGenerator",
    "decoder": "Vision VNDetectBarcodesRequest",
]
let data = try JSONSerialization.data(withJSONObject: receipt, options: [.prettyPrinted, .sortedKeys])
print(String(data: data, encoding: .utf8)!)
