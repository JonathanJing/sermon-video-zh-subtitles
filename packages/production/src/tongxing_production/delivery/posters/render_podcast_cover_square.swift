#!/usr/bin/env swift
// 1080x1080 Chinese podcast poster: the whole YouTube cover on top, a paper information band below.
// Usage: swift render_cover_square.swift brief.json cover.jpg badge.svg outDir
import AppKit
import CoreImage
import Vision

struct Failure: Error, CustomStringConvertible { let description: String }
func need(_ condition: Bool, _ message: String) throws { if !condition { throw Failure(description: message) } }

struct Brief: Decodable {
    let title, series, date, speaker, scripture, qrURL, storeURL: String
    let titleLines: [String]
    let reviewLabel: String
    let labels: [String: String]
    let locale: String?
}

let W = 1080, H = 1080
let ink = NSColor(calibratedRed: 0.055, green: 0.23, blue: 0.24, alpha: 1)
let muted = NSColor(calibratedRed: 0.25, green: 0.35, blue: 0.35, alpha: 1)
let paper = NSColor(calibratedRed: 0.953, green: 0.941, blue: 0.897, alpha: 1)
var posterLocale = "zh-Hans"

func font(_ size: CGFloat, headline: Bool = false) throws -> NSFont {
    if !headline { return NSFont.systemFont(ofSize: size, weight: .regular) }
    let titleFonts = ["zh-Hans": "STSongti-SC-Bold", "ko": "AppleMyungjo",
                      "es": "Georgia-Bold", "en": "Georgia-Bold"]
    guard let name = titleFonts[posterLocale], let face = NSFont(name: name, size: size) else {
        throw Failure(description: "Editorial title font unavailable for \(posterLocale)")
    }
    return face
}

func text(_ value: String, _ rect: NSRect, maxSize: CGFloat, minSize: CGFloat = 12,
          headline: Bool = false, color: NSColor = ink, alignment: NSTextAlignment = .left) throws {
    guard !value.isEmpty else { return }
    let style = NSMutableParagraphStyle(); style.alignment = alignment
    style.lineBreakMode = .byWordWrapping; style.lineSpacing = 2
    var size = maxSize
    while size >= minSize {
        let attrs: [NSAttributedString.Key: Any] = [.font: try font(size, headline: headline),
                                                    .foregroundColor: color, .paragraphStyle: style]
        let str = NSAttributedString(string: value, attributes: attrs)
        let measured = str.boundingRect(with: NSSize(width: rect.width, height: 100000),
                                        options: [.usesLineFragmentOrigin, .usesFontLeading])
        if ceil(measured.height) <= rect.height && ceil(measured.width) <= rect.width + 1 {
            str.draw(with: rect, options: [.usesLineFragmentOrigin, .usesFontLeading]); return
        }
        size -= 1
    }
    throw Failure(description: "Text cannot fit assigned region without clipping: \(value.prefix(60))")
}

func headline(_ line: String, _ rect: NSRect, maxSize: CGFloat, minSize: CGFloat) throws {
    var size = maxSize
    while size >= minSize {
        let face = try font(size, headline: true)
        let attrs: [NSAttributedString.Key: Any] = [.font: face, .foregroundColor: ink]
        let width = ceil((line as NSString).size(withAttributes: attrs).width)
        let height = ceil(face.ascender - face.descender + face.leading)
        if width <= rect.width && height <= rect.height {
            (line as NSString).draw(at: NSPoint(x: rect.minX, y: rect.minY + (rect.height - height) / 2),
                                    withAttributes: attrs)
            return
        }
        size -= 1
    }
    throw Failure(description: "Headline cannot fit without clipping")
}

func bitmap(_ width: Int, _ height: Int) throws -> NSBitmapImageRep {
    guard let rep = NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: width, pixelsHigh: height,
                                     bitsPerSample: 8, samplesPerPixel: 4, hasAlpha: true,
                                     isPlanar: false, colorSpaceName: .deviceRGB,
                                     bytesPerRow: width * 4, bitsPerPixel: 32) else {
        throw Failure(description: "Cannot allocate canvas")
    }
    return rep
}

func drawOn(_ rep: NSBitmapImageRep, body: () throws -> Void) throws {
    guard let base = NSGraphicsContext(bitmapImageRep: rep) else { throw Failure(description: "Cannot create context") }
    let cg = base.cgContext
    NSGraphicsContext.saveGraphicsState(); defer { NSGraphicsContext.restoreGraphicsState() }
    cg.translateBy(x: 0, y: CGFloat(rep.pixelsHigh)); cg.scaleBy(x: 1, y: -1)
    NSGraphicsContext.current = NSGraphicsContext(cgContext: cg, flipped: true)
    try body(); cg.flush()
}

func writePNG(_ rep: NSBitmapImageRep, _ url: URL) throws {
    guard let data = rep.representation(using: .png, properties: [:]) else { throw Failure(description: "PNG encoding failed") }
    try data.write(to: url, options: .atomic)
}

func qrImage(_ payload: String) throws -> CGImage {
    guard let f = CIFilter(name: "CIQRCodeGenerator") else { throw Failure(description: "CoreImage QR unavailable") }
    f.setValue(Data(payload.utf8), forKey: "inputMessage")
    f.setValue("M", forKey: "inputCorrectionLevel")
    guard let image = f.outputImage, let cg = CIContext().createCGImage(image, from: image.extent) else {
        throw Failure(description: "QR generation failed")
    }
    return cg
}

func placeQR(_ value: String, x: CGFloat, y: CGFloat, box: Int) throws {
    let qr = try qrImage(value), s = box / (qr.width + 8), size = qr.width * s, quiet = (box - size) / 2
    try need(s >= 2 && quiet >= s * 4, "QR size insufficient")
    NSColor.white.setFill(); NSRect(x: x, y: y, width: CGFloat(box), height: CGFloat(box)).fill()
    NSImage(cgImage: qr, size: NSSize(width: qr.width, height: qr.height)).draw(
        in: NSRect(x: x + CGFloat(quiet), y: y + CGFloat(quiet), width: CGFloat(size), height: CGFloat(size)),
        from: .zero, operation: .copy, fraction: 1, respectFlipped: true,
        hints: [.interpolation: NSImageInterpolation.none])
}

do {
    try need(CommandLine.arguments.count == 5, "Usage: render_cover_square.swift brief.json cover.jpg badge.svg outDir")
    let brief = try JSONDecoder().decode(Brief.self, from: Data(contentsOf: URL(fileURLWithPath: CommandLine.arguments[1])))
    try need(["zh-Hans", "en", "ko", "es"].contains(brief.locale ?? ""), "Unsupported locale")
    posterLocale = brief.locale ?? "zh-Hans"
    try need(brief.storeURL == "https://apps.apple.com/app/id6809255441", "Unexpected App Store identity")
    let out = URL(fileURLWithPath: CommandLine.arguments[4], isDirectory: true)
    try FileManager.default.createDirectory(at: out, withIntermediateDirectories: true)
    for name in ["poster.png", "poster-preview.png", "qr-validation.json"] {
        try need(!FileManager.default.fileExists(atPath: out.appendingPathComponent(name).path),
                 "Output exists; use a fresh directory")
    }
    guard let cover = NSImage(contentsOfFile: CommandLine.arguments[2]),
          let badge = NSImage(contentsOfFile: CommandLine.arguments[3]) else {
        throw Failure(description: "Cannot load cover or official badge")
    }

    let coverHeight = (CGFloat(W) * cover.size.height / cover.size.width).rounded()
    let bandTop = coverHeight
    let poster = try bitmap(W, H)
    try drawOn(poster) {
        paper.setFill(); NSRect(x: 0, y: 0, width: CGFloat(W), height: CGFloat(H)).fill()
        cover.draw(in: NSRect(x: 0, y: 0, width: CGFloat(W), height: coverHeight),
                   from: .zero, operation: .copy, fraction: 1, respectFlipped: true,
                   hints: [.interpolation: NSImageInterpolation.high])

        let left: CGFloat = 64, textWidth: CGFloat = 540
        try text(brief.labels["header"] ?? "", NSRect(x: left, y: bandTop + 24, width: 520, height: 24),
                 maxSize: 17, minSize: 12, color: muted)
        try headline(brief.titleLines[0], NSRect(x: left, y: bandTop + 54, width: textWidth, height: 62),
                     maxSize: 52, minSize: 30)
        try text(brief.series + " · " + brief.date.replacingOccurrences(of: "-", with: ".") + " · " + brief.speaker,
                 NSRect(x: left, y: bandTop + 122, width: textWidth, height: 30), maxSize: 20, minSize: 13)
        try text(brief.scripture + " · " + brief.reviewLabel,
                 NSRect(x: left, y: bandTop + 158, width: textWidth, height: 26), maxSize: 16, minSize: 11,
                 color: muted)
        try text(brief.labels["disclaimer"] ?? "", NSRect(x: left, y: bandTop + 196, width: textWidth, height: 52),
                 maxSize: 13, minSize: 10, color: muted)
        // A hairline divider closes the content block; the tagline sits under it instead of floating.
        NSColor(calibratedWhite: 0.25, alpha: 0.18).setFill()
        NSRect(x: left, y: bandTop + 318, width: CGFloat(W) - 2 * left, height: 1).fill()
        try text(brief.labels["tagline"] ?? "", NSRect(x: left, y: bandTop + 336, width: 520, height: 24),
                 maxSize: 13, minSize: 10, color: muted)

        let qx1: CGFloat = 636, qx2: CGFloat = 838, qy: CGFloat = bandTop + 62, box: CGFloat = 164
        try text(brief.labels["storeHeading"] ?? "", NSRect(x: qx1, y: bandTop + 24, width: 190, height: 24),
                 maxSize: 15, minSize: 11)
        try text(brief.labels["webHeading"] ?? "", NSRect(x: qx2, y: bandTop + 24, width: 200, height: 24),
                 maxSize: 15, minSize: 11)
        try placeQR(brief.storeURL, x: qx1, y: qy, box: Int(box))
        try placeQR(brief.qrURL, x: qx2, y: qy, box: Int(box))
        badge.draw(in: NSRect(x: qx1, y: qy + box + 22, width: 164, height: 54), from: .zero,
                   operation: .sourceOver, fraction: 1, respectFlipped: true,
                   hints: [.interpolation: NSImageInterpolation.high])
        try text(brief.labels["caption"] ?? "", NSRect(x: qx2, y: qy + box + 34, width: 200, height: 28),
                 maxSize: 14, minSize: 11, color: muted)
    }
    try writePNG(poster, out.appendingPathComponent("poster.png"))

    let preview = try bitmap(810, 810)
    try drawOn(preview) {
        NSImage(cgImage: poster.cgImage!, size: NSSize(width: W, height: H)).draw(
            in: NSRect(x: 0, y: 0, width: 810, height: 810), from: .zero, operation: .copy, fraction: 1,
            respectFlipped: true, hints: [.interpolation: NSImageInterpolation.high])
    }
    try writePNG(preview, out.appendingPathComponent("poster-preview.png"))

    var checks: [[String: Any]] = []
    for name in ["poster.png", "poster-preview.png"] {
        let image = NSImage(contentsOf: out.appendingPathComponent(name))!
        var rect = NSRect(origin: .zero, size: image.size)
        let cg = image.cgImage(forProposedRect: &rect, context: nil, hints: nil)!
        let req = VNDetectBarcodesRequest(); req.symbologies = [.qr]
        try VNImageRequestHandler(cgImage: cg, options: [:]).perform([req])
        let values = (req.results ?? []).compactMap { $0.payloadStringValue }
        try need(values.count == 2 && Set(values) == Set([brief.storeURL, brief.qrURL]),
                 "Two final QR codes must decode exactly: \(name), found \(values.count)")
        checks.append(["file": name, "passed": true, "decodedPayloads": values,
                       "width": Int(image.size.width), "height": Int(image.size.height)])
    }
    let data = try JSONSerialization.data(withJSONObject: ["schemaVersion": "tongxing-dual-qr-validation-v1",
                                                           "checks": checks],
                                          options: [.prettyPrinted, .sortedKeys])
    try data.write(to: out.appendingPathComponent("qr-validation.json"))
    print("Rendered 1080x1080 and 810x810. Both QR codes decoded correctly.")
} catch {
    fputs("\(error)\n", stderr)
    exit(1)
}
