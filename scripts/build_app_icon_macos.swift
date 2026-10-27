#!/usr/bin/env swift
// Package the existing artwork at the same visual scale as native Dock icons.
// Keep the unpadded artwork for in-app branding; only app icon outputs get margins.
import AppKit
import Foundation

let root = URL(fileURLWithPath: #filePath).deletingLastPathComponent().deletingLastPathComponent()
let artworkURL = root.appendingPathComponent("docs/assets/veronica-icon.png")
guard let artwork = NSImage(contentsOf: artworkURL) else {
    fatalError("The Veronica icon artwork is missing")
}
let fm = FileManager.default
let work = root.appendingPathComponent(".build/app-icon-\(UUID().uuidString)")
let iconset = work.appendingPathComponent("AppIcon.iconset")
try fm.createDirectory(at: iconset, withIntermediateDirectories: true)
defer { try? fm.removeItem(at: work) }
let assetDirectory = root.appendingPathComponent("macos/Assets.xcassets/AppIcon.appiconset")
let sizes = [(16, 1), (16, 2), (32, 1), (32, 2), (128, 1), (128, 2), (256, 1), (256, 2), (512, 1), (512, 2)]
for (points, scale) in sizes {
    let pixels = points * scale
    guard let bitmap = NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: pixels, pixelsHigh: pixels,
        bitsPerSample: 8, samplesPerPixel: 4, hasAlpha: true, isPlanar: false,
        colorSpaceName: .deviceRGB, bytesPerRow: pixels * 4, bitsPerPixel: 32),
          let context = NSGraphicsContext(bitmapImageRep: bitmap) else {
        fatalError("Could not prepare an app icon representation")
    }
    bitmap.size = NSSize(width: pixels, height: pixels)
    NSGraphicsContext.saveGraphicsState()
    NSGraphicsContext.current = context
    context.imageInterpolation = .high
    NSColor.clear.setFill()
    NSRect(x: 0, y: 0, width: pixels, height: pixels).fill(using: .copy)
    let canvas = CGFloat(pixels)
    let inset = canvas * 0.10
    artwork.draw(in: NSRect(x: inset, y: inset, width: canvas - 2 * inset, height: canvas - 2 * inset),
                 from: .zero, operation: .sourceOver, fraction: 1)
    NSGraphicsContext.restoreGraphicsState()
    guard let data = bitmap.representation(using: .png, properties: [:]) else {
        fatalError("Could not encode an app icon representation")
    }
    let suffix = scale == 2 ? "@2x" : ""
    let filename = "icon_\(points)x\(points)\(suffix).png"
    try data.write(to: iconset.appendingPathComponent(filename), options: .atomic)
    try data.write(to: assetDirectory.appendingPathComponent(filename), options: .atomic)
}
let output = root.appendingPathComponent("macos/Veronica/Resources/AppIcon.icns")
let process = Process()
process.executableURL = URL(fileURLWithPath: "/usr/bin/iconutil")
process.arguments = ["-c", "icns", iconset.path, "-o", output.path]
try process.run()
process.waitUntilExit()
guard process.terminationStatus == 0 else { fatalError("Could not package the app icon") }
print("App icon packaged with 10% transparent margins on each side.")
