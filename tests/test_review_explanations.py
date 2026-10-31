#!/usr/bin/env python3
"""Exercise the real Swift presentation contract against engine review reasons."""
import ast
import json
from pathlib import Path
import subprocess
import tempfile

import media_maintenance as mm

ROOT = Path(__file__).resolve().parents[1]


def literal_prefix(node):
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr) and isinstance(node.values[0], ast.Constant):
        return node.values[0].value + "2"


def main():
    reasons = {
        "embedded_date_missing", "date_unknown", "date_conflict", "date_low_confidence",
        "no_eligibility_date", "media_probe_failed", "video_source_probe_failed",
        "empty_file", "image_dimensions_unknown", "filename_collision",
        "unicode_or_case_name_collision", "category_mismatch:expected_image_detected_video",
        "invalid_date_scope", "legacy_v2_but_image_exceeds_current_target",
        "no_media_conversion_policy", "no_phase2_policy", "unclassified_content:image",
    }
    # New literal reasons emitted by the auditor/planner must gain a description.
    for name in ("media_audit.py", "media_maintenance.py"):
        tree = ast.parse((ROOT / name).read_text())
        for call in (node for node in ast.walk(tree) if isinstance(node, ast.Call)):
            if isinstance(call.func, ast.Name) and call.func.id == "Decision" and len(call.args) >= 3:
                if isinstance(call.args[1], ast.Constant) and call.args[1].value == "REVIEW":
                    prefix = literal_prefix(call.args[2])
                    if prefix:
                        reasons.add(prefix)
            keywords = {kw.arg: kw.value for kw in call.keywords}
            if isinstance(keywords.get("operation"), ast.Constant) and keywords["operation"].value == "REVIEW":
                prefix = literal_prefix(keywords.get("reason"))
                if prefix:
                    reasons.add(prefix)
    video_checks = [
        "hdr_transfer:smpte2084", "wide_gamut:bt2020", "dolby_vision",
        "dolby_vision_side_data", "hdr_mastering_metadata", "variable_frame_rate",
        "frame_count_mismatch", "non_monotonic_frame_timestamps", "duplicate_frame_timestamps",
        "multichannel_audio:6", "video_stream_count:2", "multiple_audio_streams:2",
        "extra_subtitle_streams:3", "apple_quicktime_metadata_streams:2",
        "extra_data_streams:1", "extra_attachment_streams:1", "chapters_present:12",
    ]
    reasons.update("video_source_review:" + value for value in video_checks)
    reasons.update({
        "video_source_review:apple_quicktime_metadata_streams:1,extra_subtitle_streams:2",
        "video_source_review:hdr_transfer:smpte2084,multiple_audio_streams:2,chapters_present:3",
    })
    with tempfile.TemporaryDirectory(prefix="veronica-review-explanations-") as td:
        base = Path(td)
        cases = []
        for reason in sorted(reasons):
            cases.append({"root": str(base), "state_dir": str(base / "State"),
                          "relpath": "sample.mov", "operation": "REVIEW", "source_size": 100,
                          "reason": reason, "category": "review", "detail": "A generic old engine message.",
                          "can_process": mm.review_reason_allows_process_normally(reason)})
        payload = base / "cases.json"
        payload.write_text(json.dumps(cases))
        source = base / "main.swift"
        source.write_text('''import Foundation
let data = try Data(contentsOf: URL(fileURLWithPath: CommandLine.arguments[1]))
let results = try JSONDecoder().decode([ScanResultItem].self, from: data)
let reviews = try JSONDecoder().decode([ReviewItem].self, from: data)
let raw = try JSONSerialization.jsonObject(with: data) as! [[String: Any]]
for (index, item) in results.enumerated() {
    let review = reviews[index]
    let explanation = item.reviewExplanation
    assert(explanation.isKnown, "Undescribed engine reason: \\(item.reason)")
    assert(item.actionTitle == review.title && review.explanation == explanation.explanation)
    assert(item.actionTitle != "Needs review" && item.actionTitle != "Needs your decision")
    assert(!explanation.explanation.contains(item.reason), "Raw code shown as explanation")
    assert(explanation.explanation.count > 40 && explanation.nextStep.count > 20)
    assert(review.canProcessNormally == raw[index]["can_process"] as! Bool)
}
let missing = ReviewExplanation(reason: "embedded_date_missing")
assert(missing.explanation.contains("embedded date") && missing.nextStep.contains("Add date"))
let unreadable = ReviewExplanation(reason: "media_probe_failed")
assert(unreadable.title.contains("could not be read") && !unreadable.explanation.contains("is damaged"))
let combined = ReviewExplanation(reason: "video_source_review:hdr_transfer:smpte2084,multiple_audio_streams:2,chapters_present:3")
assert(combined.title.hasPrefix("3 reasons"))
assert(combined.explanation.contains("brightness") && combined.explanation.contains("audio track") && combined.explanation.contains("chapter"))
let unknown = ReviewExplanation(reason: "future_unrecognized_safety_check")
assert(!unknown.isKnown && unknown.nextStep.contains("Keep the original"))
assert(!unknown.explanation.contains("future_unrecognized"))
let mixed = ReviewExplanation(reason: "video_source_review:extra_subtitle_streams:2,new_unknown_check")
assert(!mixed.isKnown && mixed.explanation.contains("subtitle") && mixed.title.hasPrefix("2 reasons"))
print("Accurate review descriptions, combined risks, safe fallback and engine approval parity: PASS (\\(results.count) reasons)")
''')
        binary = base / "contract"
        subprocess.run(["/usr/bin/swiftc", str(ROOT / "macos/Veronica/Sources/Models.swift"),
                        str(source), "-o", str(binary)], check=True, timeout=90)
        subprocess.run([str(binary), str(payload)], check=True)


if __name__ == "__main__":
    main()
