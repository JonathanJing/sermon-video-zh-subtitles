import Foundation
import Vision
import AppKit

// Objectness-based saliency boxes for one poster artwork.
// Output: JSON array of {"x","y","w","h","confidence"} in Vision's normalized
// coordinate space (origin bottom-left). The Python lint converts them to
// top-origin ratios and classifies the subject band against the poster safe area.
guard CommandLine.arguments.count == 2 else {
    FileHandle.standardError.write(Data("usage: saliency_lint.swift <png>\n".utf8))
    exit(2)
}
let path = CommandLine.arguments[1]
guard let image = NSImage(contentsOfFile: path),
      let cgImage = image.cgImage(forProposedRect: nil, context: nil, hints: nil) else {
    FileHandle.standardError.write(Data("cannot load image\n".utf8))
    exit(3)
}
let request = VNGenerateObjectnessBasedSaliencyImageRequest()
do {
    try VNImageRequestHandler(cgImage: cgImage, options: [:]).perform([request])
} catch {
    FileHandle.standardError.write(Data("vision failed: \(error)\n".utf8))
    exit(4)
}
guard let observation = request.results?.first as? VNSaliencyImageObservation,
      let objects = observation.salientObjects, !objects.isEmpty else {
    print("[]")
    exit(0)
}
let rows: [[String: Any]] = objects.map { object in
    let box = object.boundingBox
    return ["x": Double(box.origin.x), "y": Double(box.origin.y),
            "w": Double(box.size.width), "h": Double(box.size.height),
            "confidence": Double(object.confidence)]
}
let data = try JSONSerialization.data(withJSONObject: rows, options: [.sortedKeys])
print(String(data: data, encoding: .utf8)!)
