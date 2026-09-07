#!/usr/bin/env swift
import Foundation
import CoreGraphics
import ImageIO
import UniformTypeIdentifiers

// Run on macOS: swift apps/tongxing-ios/scripts/generate-app-icon.swift
// Scale the approved square light/dark logos as a whole, preserving composition.
// The images in Branding remain unchanged; iOS applies its own AppIcon mask.
let appDirectory = URL(fileURLWithPath: #filePath).deletingLastPathComponent().deletingLastPathComponent()
let assets = appDirectory.appendingPathComponent("App/Assets.xcassets")
let opaqueAlphaModes: [CGImageAlphaInfo] = [.none, .noneSkipFirst, .noneSkipLast]
let colorSpace = CGColorSpace(name: CGColorSpace.sRGB)!

func loadLogo(_ filename: String) -> CGImage {
    let sourceURL = appDirectory.appendingPathComponent("Branding/\(filename)")
    guard let source = CGImageSourceCreateWithURL(sourceURL as CFURL, nil),
          let original = CGImageSourceCreateImageAtIndex(source, 0, nil) else {
        fatalError("Unable to read Branding/\(filename)")
    }
    precondition(original.width == original.height, "The approved logo must remain square")
    precondition(opaqueAlphaModes.contains(original.alphaInfo), "The approved logo must be opaque")
    return original
}

// Validate both sources before writing any generated asset. A missing light
// source must leave the previously generated catalog intact.
let variants = [
    (suffix: "", image: loadLogo("Logo-light-source.png")),
    (suffix: "-dark", image: loadLogo("Logo-source.png"))
]

func generate(size: Int, assetName: String, extension assetExtension: String, imageRecord: [String: String]) throws {
    let directory = assets.appendingPathComponent("\(assetName).\(assetExtension)")
    try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
    var images: [[String: Any]] = []
    for variant in variants {
        let output = directory.appendingPathComponent("\(assetName)\(variant.suffix).png")
        guard let context = CGContext(data: nil, width: size, height: size,
                bitsPerComponent: 8, bytesPerRow: size * 4, space: colorSpace,
                bitmapInfo: CGImageAlphaInfo.noneSkipLast.rawValue) else {
            fatalError("Unable to create the native image scaler")
        }
        context.interpolationQuality = .high
        context.draw(variant.image, in: CGRect(x: 0, y: 0, width: size, height: size))

        guard let rendered = context.makeImage(),
              let destination = CGImageDestinationCreateWithURL(output as CFURL, UTType.png.identifier as CFString, 1, nil) else {
            fatalError("Unable to encode \(output.lastPathComponent)")
        }
        CGImageDestinationAddImage(destination, rendered, nil)
        precondition(CGImageDestinationFinalize(destination), "PNG encoding failed")

        guard let encoded = CGImageSourceCreateWithURL(output as CFURL, nil),
              let decoded = CGImageSourceCreateImageAtIndex(encoded, 0, nil) else {
            fatalError("The encoded PNG could not be decoded")
        }
        precondition(decoded.width == size && decoded.height == size, "Incorrect asset dimensions")
        precondition(opaqueAlphaModes.contains(decoded.alphaInfo), "The generated image must be opaque")

        var record: [String: Any] = imageRecord
        record["filename"] = output.lastPathComponent
        if variant.suffix == "-dark" {
            record["appearances"] = [["appearance": "luminosity", "value": "dark"]]
        }
        images.append(record)
        print("Generated \(output.path): \(size) × \(size), opaque sRGB")
    }

    let manifest: [String: Any] = [
        "images": images,
        "info": ["author": "xcode", "version": 1]
    ]
    var json = try JSONSerialization.data(withJSONObject: manifest, options: [.prettyPrinted, .sortedKeys])
    json.append(0x0a)
    try json.write(to: directory.appendingPathComponent("Contents.json"), options: .atomic)
}

try generate(size: 1024, assetName: "AppIcon", extension: "appiconset",
             imageRecord: ["idiom": "universal", "platform": "ios", "size": "1024x1024"])
try generate(size: 128, assetName: "BrandMark", extension: "imageset", imageRecord: ["idiom": "universal"])
