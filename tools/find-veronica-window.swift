import Foundation
import CoreGraphics

guard CommandLine.arguments.count == 2,
      let targetPID = Int32(CommandLine.arguments[1]) else {
    fputs("Usage: find-veronica-window.swift PID\n", stderr)
    exit(2)
}

let options: CGWindowListOption = [
    .optionOnScreenOnly,
    .excludeDesktopElements
]

guard let windows = CGWindowListCopyWindowInfo(
    options,
    kCGNullWindowID
) as? [[String: Any]] else {
    fputs("Unable to inspect windows.\n", stderr)
    exit(1)
}

var selectedID: Int?
var selectedArea: Double = 0

for window in windows {
    guard let ownerPID = window[kCGWindowOwnerPID as String] as? Int,
          ownerPID == Int(targetPID),
          let layer = window[kCGWindowLayer as String] as? Int,
          layer == 0,
          let windowID = window[kCGWindowNumber as String] as? Int,
          windowID > 0,
          let bounds = window[kCGWindowBounds as String] as? [String: Any],
          let width = bounds["Width"] as? Double,
          let height = bounds["Height"] as? Double else {
        continue
    }

    let area = width * height

    if area > selectedArea {
        selectedArea = area
        selectedID = windowID
    }
}

guard let selectedID else {
    fputs("No visible normal-layer window for PID \(targetPID).\n", stderr)
    exit(1)
}

print(selectedID)
