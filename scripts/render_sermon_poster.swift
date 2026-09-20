#!/usr/bin/env swift
// swiftc render_sermon_poster.swift -o render_sermon_poster
// render_sermon_poster brief.json art.png outDir
import AppKit
import CoreImage
import Vision

struct Failure: Error, CustomStringConvertible { let description: String }
func need(_ condition: Bool, _ message: String) throws { if !condition { throw Failure(description: message) } }
struct Brief: Decodable {
    let title, series, date, speaker, scripture, tagline, qrURL, origin, reviewLabel: String
    let labels: [String:String]
}
let W = 1800, H = 2400
let ink = NSColor(calibratedRed: 0.055, green: 0.23, blue: 0.24, alpha: 1)
let muted = NSColor(calibratedRed: 0.29, green: 0.39, blue: 0.39, alpha: 1)
let paper = NSColor(calibratedRed: 0.953, green: 0.941, blue: 0.897, alpha: 1)
func font(_ size: CGFloat, serif: Bool = false) -> NSFont {
    NSFont(name: serif ? "Songti SC" : "PingFang SC", size: size) ?? NSFont(name: "PingFang SC", size: size) ?? NSFont.systemFont(ofSize:size)
}
func text(_ value: String, _ rect: NSRect, maxSize: CGFloat, minSize: CGFloat = 16, serif: Bool = false, color: NSColor = ink, alignment: NSTextAlignment = .left) throws {
    guard !value.isEmpty else { return }
    let style = NSMutableParagraphStyle(); style.alignment = alignment; style.lineBreakMode = .byWordWrapping; style.lineSpacing = 2
    var size = maxSize
    while size >= minSize {
        let attrs: [NSAttributedString.Key:Any] = [.font:font(size,serif:serif),.foregroundColor:color,.paragraphStyle:style]
        let str = NSAttributedString(string:value,attributes:attrs)
        let measured = str.boundingRect(with:NSSize(width:rect.width,height:100000), options:[.usesLineFragmentOrigin,.usesFontLeading])
        if ceil(measured.height) <= rect.height && ceil(measured.width) <= rect.width + 1 {
            str.draw(with:rect,options:[.usesLineFragmentOrigin,.usesFontLeading]); return
        }
        size -= 1
    }
    throw Failure(description:"Text cannot fit assigned region without clipping: \(value.prefix(60))")
}
func bitmap(_ width: Int, _ height: Int) throws -> NSBitmapImageRep {
    guard let rep = NSBitmapImageRep(bitmapDataPlanes:nil,pixelsWide:width,pixelsHigh:height,bitsPerSample:8,samplesPerPixel:4,hasAlpha:true,isPlanar:false,colorSpaceName:.deviceRGB,bytesPerRow:width*4,bitsPerPixel:32) else { throw Failure(description:"Cannot allocate canvas") }; return rep
}
func drawOn(_ rep: NSBitmapImageRep, body:() throws -> Void) throws {
    guard let base = NSGraphicsContext(bitmapImageRep:rep) else { throw Failure(description:"Cannot create canvas context") }
    let cg = base.cgContext
    NSGraphicsContext.saveGraphicsState(); defer { NSGraphicsContext.restoreGraphicsState() }
    cg.translateBy(x:0,y:CGFloat(rep.pixelsHigh)); cg.scaleBy(x:1,y:-1)
    NSGraphicsContext.current = NSGraphicsContext(cgContext:cg,flipped:true)
    try body(); cg.flush()
}
func writePNG(_ rep:NSBitmapImageRep, _ url:URL) throws {
    guard let data=rep.representation(using:.png,properties:[:]) else { throw Failure(description:"PNG encoding failed") }; try data.write(to:url,options:.atomic)
}
func qrImage(_ payload:String) throws -> CGImage {
    guard let f=CIFilter(name:"CIQRCodeGenerator") else { throw Failure(description:"CoreImage QR unavailable") }
    f.setValue(Data(payload.utf8),forKey:"inputMessage"); f.setValue("M",forKey:"inputCorrectionLevel")
    guard let image=f.outputImage, let cg=CIContext().createCGImage(image,from:image.extent) else { throw Failure(description:"QR generation failed") };return cg
}
func decode(_ image:CGImage, expected:String) throws -> [String] {
    let req=VNDetectBarcodesRequest();req.symbologies=[.qr]
    try VNImageRequestHandler(cgImage:image,options:[:]).perform([req])
    let values=(req.results ?? []).compactMap{$0.payloadStringValue}
    try need(values == [expected],"Final PNG QR decode mismatch: found \(values.count) QR payload(s)")
    return values
}
func main() throws {
    try need(CommandLine.arguments.count == 4,"Usage: render_sermon_poster brief.json art.png outDir")
    let args=CommandLine.arguments
    let brief=try JSONDecoder().decode(Brief.self,from:Data(contentsOf:URL(fileURLWithPath:args[1])))
    for (key,value) in [("title",brief.title),("date",brief.date),("speaker",brief.speaker),("scripture",brief.scripture),("tagline",brief.tagline),("reviewLabel",brief.reviewLabel)] { try need(!value.trimmingCharacters(in:.whitespacesAndNewlines).isEmpty,"Missing \(key)") }
    guard let url=URL(string:brief.qrURL),url.scheme == "https",url.host != nil else { throw Failure(description:"qrURL must be an absolute HTTPS URL") }
    let disclaimer=brief.labels["disclaimer"] ?? ""
    try need(disclaimer.contains("独立") && disclaimer.contains("AI") && disclaimer.contains("非教会官方"),"labels.disclaimer must explicitly state 独立, AI and 非教会官方")
    guard let art=NSImage(contentsOfFile:args[2]),art.size.width > 0,art.size.height > 0 else { throw Failure(description:"Cannot load art") }
    let out=URL(fileURLWithPath:args[3],isDirectory:true)
    try FileManager.default.createDirectory(at:out,withIntermediateDirectories:true)
    for name in ["poster.png","poster-preview.png","qr-validation.json"] { try need(!FileManager.default.fileExists(atPath:out.appendingPathComponent(name).path),"Output already exists; use a fresh outDir") }
    let qr=try qrImage(brief.qrURL), modules=qr.width
    let scale=(404/(modules+8)/2)*2
    try need(scale >= 2,"qrURL is too long for a reliably decodable 404px QR box")
    let qrSize=modules*scale, quiet=(404-qrSize)/2
    try need(quiet >= 4*scale,"Insufficient QR quiet zone")
    let poster=try bitmap(W,H)
    try drawOn(poster) {
        paper.setFill();NSRect(x:0,y:0,width:W,height:H).fill()
        try text(brief.labels["brand"] ?? "",NSRect(x:96,y:64,width:220,height:54),maxSize:36)
        try text(brief.labels["eyebrow"] ?? "",NSRect(x:330,y:70,width:900,height:45),maxSize:23)
        try text(brief.date,NSRect(x:1260,y:72,width:444,height:45),maxSize:28,alignment:.right)
        muted.withAlphaComponent(0.22).setFill();NSRect(x:96,y:146,width:1608,height:1).fill()
        try text(brief.title,NSRect(x:90,y:168,width:1614,height:205),maxSize:144,minSize:30,serif:true)
        try text(brief.series,NSRect(x:100,y:374,width:1600,height:62),maxSize:30,minSize:16)
        // Aspect-fit preserves all original art; no crop, filter, retouch or overlay.
        let area=NSRect(x:0,y:450,width:1800,height:1200)
        let ratio=min(area.width/art.size.width,area.height/art.size.height)
        let size=NSSize(width:art.size.width*ratio,height:art.size.height*ratio)
        art.draw(in:NSRect(x:area.midX-size.width/2,y:area.midY-size.height/2,width:size.width,height:size.height),from:.zero,operation:.sourceOver,fraction:1,respectFlipped:true,hints:[.interpolation:NSImageInterpolation.high])
        NSColor(calibratedRed:0.65,green:0.47,blue:0.22,alpha:1).setFill();NSRect(x:96,y:1720,width:60,height:5).fill()
        try text(brief.tagline,NSRect(x:96,y:1770,width:1110,height:120),maxSize:60,minSize:22,serif:true)
        try text(brief.speaker+"  |  "+brief.scripture,NSRect(x:100,y:1898,width:1100,height:68),maxSize:30,minSize:16)
        try text(brief.labels["cta"] ?? "",NSRect(x:96,y:2020,width:1110,height:68),maxSize:46,minSize:20)
        try text(brief.labels["serviceLine"] ?? "",NSRect(x:100,y:2106,width:1100,height:54),maxSize:28,minSize:16,color:muted)
        try text(brief.origin,NSRect(x:100,y:2182,width:1100,height:52),maxSize:24,minSize:14,color:muted)
        try text(brief.reviewLabel,NSRect(x:100,y:2238,width:1100,height:56),maxSize:22,minSize:14,color:muted)
        NSColor.white.setFill();NSRect(x:1300,y:1810,width:404,height:404).fill()
        let ctx=NSGraphicsContext.current!;ctx.imageInterpolation = .none
        NSImage(cgImage:qr,size:NSSize(width:modules,height:modules)).draw(in:NSRect(x:1300+quiet,y:1810+quiet,width:qrSize,height:qrSize),from:.zero,operation:.copy,fraction:1,respectFlipped:true,hints:[.interpolation:NSImageInterpolation.none])
        try text(brief.labels["qrCaption"] ?? "",NSRect(x:1260,y:2240,width:480,height:60),maxSize:24,minSize:14,alignment:.center)
        muted.withAlphaComponent(0.22).setFill();NSRect(x:96,y:2310,width:1608,height:1).fill()
        try text(disclaimer,NSRect(x:96,y:2340,width:1608,height:48),maxSize:20,minSize:12,color:muted)
    }
    guard let full=poster.cgImage else { throw Failure(description:"Missing full canvas") }
    let preview=try bitmap(900,1200)
    try drawOn(preview) {
        // Even integer module scaling keeps QR modules crisp at both resolutions.
        NSImage(cgImage:full,size:NSSize(width:W,height:H)).draw(in:NSRect(x:0,y:0,width:900,height:1200),from:.zero,operation:.copy,fraction:1,respectFlipped:true,hints:[.interpolation:NSImageInterpolation.none])
    }
    let posterURL=out.appendingPathComponent("poster.png"), previewURL=out.appendingPathComponent("poster-preview.png")
    try writePNG(poster,posterURL);try writePNG(preview,previewURL)
    var checks:[[String:Any]]=[]
    for (file,width,height) in [(posterURL,W,H),(previewURL,900,1200)] {
        guard let image=NSBitmapImageRep(data:try Data(contentsOf:file)),let cg=image.cgImage else {throw Failure(description:"Cannot reopen final PNG")}
        try need(image.pixelsWide == width && image.pixelsHigh == height,"Unexpected final image dimensions")
        checks.append(["file":file.lastPathComponent,"width":width,"height":height,"decodedPayloads":try decode(cg,expected:brief.qrURL),"status":"pass","passed":true,"payload":brief.qrURL])
    }
    let report:[String:Any] = ["schemaVersion":"sermon-poster-qr-validation-v1","status":"pass","qrURL":brief.qrURL,"encoder":"CoreImage CIQRCodeGenerator","decoder":"Vision VNDetectBarcodesRequest","qrBoxPixels":404,"qrModuleCount":modules,"pixelsPerModule":scale,"quietZonePixels":quiet,"humanApproval":false,"checks":checks]
    try JSONSerialization.data(withJSONObject:report,options:[.prettyPrinted,.sortedKeys]).write(to:out.appendingPathComponent("qr-validation.json"),options:.atomic)
    print("PASS: poster.png 1800x2400 and poster-preview.png 900x1200; both final PNG QR payloads verified")
}
do { try main() } catch { fputs("Error: \(error)\n",stderr);exit(1) }
