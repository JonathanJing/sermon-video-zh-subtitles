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
    let locale: String?
    let storeURL: String
    let displayTitle: String?
}
let W = 1200, H = 1800
let ink = NSColor(calibratedRed: 0.055, green: 0.23, blue: 0.24, alpha: 1)
let muted = NSColor(calibratedRed: 0.29, green: 0.39, blue: 0.39, alpha: 1)
let paper = NSColor(calibratedRed: 0.953, green: 0.941, blue: 0.897, alpha: 1)
var posterLocale = "zh-Hans"
func font(_ size: CGFloat, headline: Bool = false) throws -> NSFont {
    guard headline else { return NSFont.systemFont(ofSize: size, weight: .regular) }
    let titleFonts = ["zh-Hans": "STSongti-SC-Bold", "ko": "AppleMyungjo",
                      "es": "Georgia-Bold", "en": "Georgia-Bold"]
    guard let name = titleFonts[posterLocale], let face = NSFont(name: name, size: size) else {
        throw Failure(description: "Editorial title font unavailable for \(posterLocale)")
    }
    return face
}
func text(_ value: String, _ rect: NSRect, maxSize: CGFloat, minSize: CGFloat = 16, headline: Bool = false, color: NSColor = ink, alignment: NSTextAlignment = .left) throws {
    guard !value.isEmpty else { return }
    let style = NSMutableParagraphStyle(); style.alignment = alignment; style.lineBreakMode = .byWordWrapping; style.lineSpacing = 2
    var size = maxSize
    while size >= minSize {
        let attrs: [NSAttributedString.Key:Any] = [.font:try font(size,headline:headline),.foregroundColor:color,.paragraphStyle:style]
        let str = NSAttributedString(string:value,attributes:attrs)
        let measured = str.boundingRect(with:NSSize(width:rect.width,height:100000), options:[.usesLineFragmentOrigin,.usesFontLeading])
        if ceil(measured.height) <= rect.height && ceil(measured.width) <= rect.width + 1 {
            str.draw(with:rect,options:[.usesLineFragmentOrigin,.usesFontLeading]); return
        }
        size -= 1
    }
    throw Failure(description:"Text cannot fit assigned region without clipping: \(value.prefix(60))")
}
func oneLineHeadline(_ value: String, _ rect: NSRect, maxSize: CGFloat, minSize: CGFloat) throws {
    let line = value.split(whereSeparator: { $0.isWhitespace }).joined(separator: " ")
    try need(!line.isEmpty, "Empty poster title")
    var size = maxSize
    while size >= minSize {
        let face = try font(size, headline: true)
        let attributes: [NSAttributedString.Key: Any] = [.font: face, .foregroundColor: ink]
        let measured = (line as NSString).size(withAttributes: attributes)
        if ceil(measured.width) <= rect.width && ceil(measured.height) <= rect.height {
            let origin = NSPoint(x: rect.midX - measured.width / 2, y: rect.midY - measured.height / 2)
            (line as NSString).draw(at: origin, withAttributes: attributes)
            return
        }
        size -= 1
    }
    throw Failure(description: "Title cannot fit on one line without clipping: \(line.prefix(60))")
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
func softenHeadlineBackground() {
    // Dark artwork can swallow the dark-green title. Fade a light scrim out
    // before the separate source-metadata panel begins at y=505.
    let colorSpace = CGColorSpaceCreateDeviceRGB()
    let colors = [CGColor(red:0.953,green:0.941,blue:0.897,alpha:0.88),
                  CGColor(red:0.953,green:0.941,blue:0.897,alpha:0.62),
                  CGColor(red:0.953,green:0.941,blue:0.897,alpha:0)] as CFArray
    guard let gradient = CGGradient(colorsSpace:colorSpace,colors:colors,locations:[0,0.78,1]) else { return }
    let context = NSGraphicsContext.current!.cgContext
    context.saveGState(); defer { context.restoreGState() }
    context.clip(to:CGRect(x:0,y:0,width:1200,height:505))
    context.drawLinearGradient(gradient,start:CGPoint(x:0,y:0),end:CGPoint(x:0,y:505),options:[])
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

func placeQR(_ value:String, x:CGFloat, y:CGFloat, box:Int) throws {
 let qr=try qrImage(value), s=box/(qr.width+8), size=qr.width*s, quiet=(box-size)/2
 try need(s>=2 && quiet>=s*4,"QR size insufficient")
 NSColor.white.setFill();NSRect(x:x,y:y,width:CGFloat(box),height:CGFloat(box)).fill()
 NSImage(cgImage:qr,size:NSSize(width:qr.width,height:qr.height)).draw(in:NSRect(x:x+CGFloat(quiet),y:y+CGFloat(quiet),width:CGFloat(size),height:CGFloat(size)),from:.zero,operation:.copy,fraction:1,respectFlipped:true,hints:[.interpolation:NSImageInterpolation.none])
}
do {
 try need(CommandLine.arguments.count == 5,"Usage: render_weekly_poster brief.json art.png badge.svg outDir")
 let brief=try JSONDecoder().decode(Brief.self,from:Data(contentsOf:URL(fileURLWithPath:CommandLine.arguments[1])))
 try need(["zh-Hans","en","ko","es"].contains(brief.locale ?? ""),"Unsupported poster locale")
 posterLocale = brief.locale ?? "zh-Hans"
 let storeURL=brief.storeURL,webURL=brief.qrURL
 try need(storeURL == "https://apps.apple.com/app/id6809255441","Unexpected App Store identity")
 let out=URL(fileURLWithPath:CommandLine.arguments[4],isDirectory:true)
 try FileManager.default.createDirectory(at:out,withIntermediateDirectories:true)
 for name in ["poster.png","poster-preview.png","qr-validation.json"] {try need(!FileManager.default.fileExists(atPath:out.appendingPathComponent(name).path),"Output exists; use fresh directory")}
 guard let art=NSImage(contentsOfFile:CommandLine.arguments[2]),let badge=NSImage(contentsOfFile:CommandLine.arguments[3]) else {throw Failure(description:"Cannot load art or official badge")}
 let poster=try bitmap(W,H)
 try drawOn(poster) {
 let ratio=max(CGFloat(W)/art.size.width,CGFloat(H)/art.size.height)
 let area=NSRect(x:(CGFloat(W)-art.size.width*ratio)/2,y:(CGFloat(H)-art.size.height*ratio)/2,width:art.size.width*ratio,height:art.size.height*ratio)
 art.draw(in:area,from:.zero,operation:.copy,fraction:1,respectFlipped:true,hints:[.interpolation:NSImageInterpolation.high])
 softenHeadlineBackground()
 try text(brief.labels["header"] ?? "",NSRect(x:120,y:75,width:960,height:68),maxSize:33,alignment:.center)
 try oneLineHeadline(brief.displayTitle ?? brief.title,NSRect(x:80,y:225,width:1040,height:210),maxSize:brief.locale == "zh-Hans" ? 138 : 100,minSize:46)
 // Group source metadata over a stable light surface across weekly artwork.
 paper.withAlphaComponent(0.70).setFill()
 NSBezierPath(roundedRect:NSRect(x:80,y:505,width:1040,height:255),xRadius:20,yRadius:20).fill()
 try text(brief.series,NSRect(x:120,y:525,width:960,height:54),maxSize:34,minSize:27,alignment:.center)
 try text(brief.date.replacingOccurrences(of:"-",with:".")+" · "+brief.speaker,NSRect(x:120,y:605,width:960,height:55),maxSize:33,minSize:28,alignment:.center)
 try text(brief.scripture,NSRect(x:120,y:678,width:960,height:55),maxSize:31,minSize:27,alignment:.center)
 paper.setFill();NSRect(x:0,y:1200,width:1200,height:600).fill()
 try text(brief.labels["cta"] ?? "",NSRect(x:80,y:1224,width:1040,height:58),maxSize:34,minSize:29,alignment:.center)
 try text(brief.labels["storeHeading"] ?? "",NSRect(x:125,y:1290,width:350,height:43),maxSize:29,minSize:27,alignment:.center)
 try text(brief.labels["webHeading"] ?? "",NSRect(x:725,y:1290,width:350,height:43),maxSize:29,minSize:27,alignment:.center)
 try placeQR(storeURL,x:156,y:1340,box:288)
 try placeQR(webURL,x:756,y:1340,box:288)
 muted.withAlphaComponent(0.18).setFill();NSRect(x:600,y:1345,width:1,height:338).fill()
 badge.draw(in:NSRect(x:165,y:1635,width:270,height:90),from:.zero,operation:.sourceOver,fraction:1,respectFlipped:true,hints:[.interpolation:NSImageInterpolation.high])
 try text(brief.labels["caption"] ?? "",NSRect(x:660,y:1648,width:480,height:65),maxSize:29,minSize:25,color:muted,alignment:.center)
 try text(brief.labels["disclaimer"] ?? "",NSRect(x:58,y:1724,width:1084,height:73),maxSize:28,minSize:24,color:muted,alignment:.center)
 }
 try writePNG(poster,out.appendingPathComponent("poster.png"))
 let preview=try bitmap(600,900)
 try drawOn(preview) { NSImage(cgImage:poster.cgImage!,size:NSSize(width:1200,height:1800)).draw(in:NSRect(x:0,y:0,width:600,height:900),from:.zero,operation:.copy,fraction:1,respectFlipped:true,hints:[.interpolation:NSImageInterpolation.none]) }
 try writePNG(preview,out.appendingPathComponent("poster-preview.png"))
 var checks:[[String:Any]]=[]
 for name in ["poster.png","poster-preview.png"] {
 let image=NSImage(contentsOf:out.appendingPathComponent(name))!; var rect=NSRect(origin:.zero,size:image.size)
 let cg=image.cgImage(forProposedRect:&rect,context:nil,hints:nil)!
 let req=VNDetectBarcodesRequest();req.symbologies=[.qr];try VNImageRequestHandler(cgImage:cg,options:[:]).perform([req])
 let values=(req.results ?? []).compactMap{$0.payloadStringValue}
 try need(values.count==2 && Set(values)==Set([storeURL,webURL]),"Two final QR codes must decode exactly: \(name), found \(values.count)")
 checks.append(["file":name,"passed":true,"decodedPayloads":values,"width":Int(image.size.width),"height":Int(image.size.height)])
 }
 let data=try JSONSerialization.data(withJSONObject:["schemaVersion":"tongxing-dual-qr-validation-v1","checks":checks],options:[.prettyPrinted,.sortedKeys]);try data.write(to:out.appendingPathComponent("qr-validation.json"))
 print("Rendered 1200x1800 and 600x900. Both QR codes decoded correctly in both final files.")
} catch {fputs("\(error)\n",stderr);exit(1)}
