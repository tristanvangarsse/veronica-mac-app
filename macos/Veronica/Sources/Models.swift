import Foundation

struct MediaProcessingPolicy: Codable, Equatable {
    var images: Bool
    var videos: Bool
    var audio: Bool
    var imageExtensions: [String]
    var videoExtensions: [String]
    var audioExtensions: [String]
    var excludedDirectoryNames: [String]

    static let defaultExcludedDirectoryNames: [String] = []

    static let allImageExtensions = [".bmp", ".gif", ".heic", ".heif", ".jpeg", ".jpg", ".png", ".webp"]
    static let allVideoExtensions = [".3gp", ".avi", ".m2ts", ".m4v", ".mkv", ".mov", ".mp4", ".mts", ".webm"]
    static let allAudioExtensions = [".aac", ".aif", ".aiff", ".amr", ".flac", ".m4a", ".m4r", ".mp3", ".ogg", ".opus", ".wav"]

    static let recommended = MediaProcessingPolicy(
        images: true, videos: true, audio: true,
        imageExtensions: allImageExtensions.filter { $0 != ".gif" },
        videoExtensions: allVideoExtensions, audioExtensions: allAudioExtensions
    )

    enum CodingKeys: String, CodingKey {
        case images
        case videos
        case audio
        case imageExtensions = "image_extensions"
        case videoExtensions = "video_extensions"
        case audioExtensions = "audio_extensions"
        case excludedDirectoryNames = "excluded_directory_names"
    }

    init(
        images: Bool,
        videos: Bool,
        audio: Bool,
        imageExtensions: [String],
        videoExtensions: [String],
        audioExtensions: [String],
        excludedDirectoryNames: [String] = Self.defaultExcludedDirectoryNames
    ) {
        self.images = images
        self.videos = videos
        self.audio = audio
        self.imageExtensions = imageExtensions
        self.videoExtensions = videoExtensions
        self.audioExtensions = audioExtensions
        self.excludedDirectoryNames = excludedDirectoryNames
    }

    init(from decoder: Decoder) throws {
        var container = try decoder.container(keyedBy: CodingKeys.self)
        var images = try container.decodeIfPresent(Bool.self, forKey: .images) ?? true
        var videos = try container.decodeIfPresent(Bool.self, forKey: .videos) ?? true
        var audio = try container.decodeIfPresent(Bool.self, forKey: .audio) ?? true

        self.images = images
        self.videos = videos
        self.audio = audio
        self.imageExtensions = try container.decodeIfPresent([String].self, forKey: .imageExtensions)
            ?? (images ? Self.allImageExtensions : [])
        self.videoExtensions = try container.decodeIfPresent([String].self, forKey: .videoExtensions)
            ?? (videos ? Self.allVideoExtensions : [])
        self.audioExtensions = try container.decodeIfPresent([String].self, forKey: .audioExtensions)
            ?? (audio ? Self.allAudioExtensions : [])
        self.excludedDirectoryNames = try container.decodeIfPresent([String].self, forKey: .excludedDirectoryNames)
            ?? Self.defaultExcludedDirectoryNames
    }
}

enum SettingsNumberInput {
    static func decimal(_ text: String) -> Double? {
        guard let number = Double(text.trimmingCharacters(in: .whitespacesAndNewlines).replacingOccurrences(of: ",", with: ".")),
              number.isFinite else { return nil }
        return number
    }
}

struct OptimizationSettings: Codable, Equatable {
    var imageOutputFormat: String
    var imageMaxMegapixels: Double
    var jpegQuality: Int
    var videoMaxEdge: Int
    var audioMinSizeMB: Int
    var videoAllowCameraMetadataDrop: Bool
    var recompressImagesBelowTarget: Bool = true
    var minimumSavingPercent: Double = 10
    var minimumSavingMB: Double = 1

    static let recommended = OptimizationSettings(
        imageOutputFormat: "jpeg",
        imageMaxMegapixels: 20,
        jpegQuality: 70,
        videoMaxEdge: 1280,
        audioMinSizeMB: 10,
        videoAllowCameraMetadataDrop: true
    )

    enum CodingKeys: String, CodingKey {
        case imageOutputFormat = "image_output_format"
        case imageMaxMegapixels = "image_max_megapixels"
        case jpegQuality = "jpeg_quality"
        case videoMaxEdge = "video_max_edge"
        case audioMinSizeMB = "audio_min_size_mb"
        case videoAllowCameraMetadataDrop = "video_allow_camera_metadata_drop"
        case recompressImagesBelowTarget = "recompress_images_below_target"
        case minimumSavingPercent = "minimum_saving_percent"
        case minimumSavingMB = "minimum_saving_mb"
    }
}

extension OptimizationSettings {
    init(from decoder: Decoder) throws {
        let values = try decoder.container(keyedBy: CodingKeys.self)
        imageOutputFormat = try values.decode(String.self, forKey: .imageOutputFormat)
        imageMaxMegapixels = try values.decode(Double.self, forKey: .imageMaxMegapixels)
        jpegQuality = try values.decode(Int.self, forKey: .jpegQuality)
        videoMaxEdge = try values.decode(Int.self, forKey: .videoMaxEdge)
        audioMinSizeMB = try values.decode(Int.self, forKey: .audioMinSizeMB)
        videoAllowCameraMetadataDrop = try values.decode(Bool.self, forKey: .videoAllowCameraMetadataDrop)
        recompressImagesBelowTarget = try values.decodeIfPresent(Bool.self, forKey: .recompressImagesBelowTarget) ?? true
        minimumSavingPercent = try values.decodeIfPresent(Double.self, forKey: .minimumSavingPercent) ?? 10
        minimumSavingMB = try values.decodeIfPresent(Double.self, forKey: .minimumSavingMB) ?? 1
    }
}

enum FilenameDateStyle {
    static let choices = [
        ("YYMMDD-", "230101-photo.jpg"),
        ("YYYY-MM-DD_", "2023-01-01_photo.jpg"),
        ("YYYYMMDD-", "20230101-photo.jpg"),
        ("DD-MM-YYYY_", "01-01-2023_photo.jpg")
    ]
    static func isValid(_ style: String) -> Bool {
        guard (6...32).contains(style.count), let last = style.last, "-_. ".contains(last) else { return false }
        let regex = try! NSRegularExpression(pattern: "YYYY|YY|MM|DD")
        let source = style as NSString
        let matches = regex.matches(in: style, range: NSRange(location: 0, length: source.length))
        let tokens = matches.map { source.substring(with: $0.range) }
        let remaining = regex.stringByReplacingMatches(in: style, range: NSRange(location: 0, length: source.length), withTemplate: "")
        return tokens.count == 3 && tokens.filter { $0 == "YYYY" || $0 == "YY" }.count == 1
            && tokens.filter { $0 == "MM" }.count == 1 && tokens.filter { $0 == "DD" }.count == 1
            && remaining.allSatisfy { "-_. ".contains($0) }
    }
    static func example(_ style: String) -> String {
        style.replacingOccurrences(of: "YYYY", with: "2023")
            .replacingOccurrences(of: "YY", with: "23")
            .replacingOccurrences(of: "MM", with: "01")
            .replacingOccurrences(of: "DD", with: "01") + "photo.jpg"
    }
}

struct ProcessingRecipe: Codable, Equatable {
    var mediaProcessing: MediaProcessingPolicy
    var optimizationSettings: OptimizationSettings
    var filenamePolicy: FilenamePolicySettings
    var dateScope: DateScopeSettings

    static let recommended = ProcessingRecipe(
        mediaProcessing: .recommended, optimizationSettings: .recommended,
        filenamePolicy: .recommended, dateScope: .recommended
    )

    enum CodingKeys: String, CodingKey {
        case mediaProcessing = "media_processing"
        case optimizationSettings = "optimization_settings"
        case filenamePolicy = "filename_policy"
        case dateScope = "date_scope"
    }

    var summary: String {
        var parts: [String] = []
        if mediaProcessing.images {
            let format = optimizationSettings.imageOutputFormat == "png" ? "PNG" : "JPEG \(optimizationSettings.jpegQuality)"
            parts.append("Images: \(Int(optimizationSettings.imageMaxMegapixels)) MP · \(format)")
        }
        if mediaProcessing.videos { parts.append("Video") }
        if mediaProcessing.audio { parts.append("Audio") }
        return parts.isEmpty ? "No media selected" : parts.joined(separator: " · ")
    }
}

struct FolderSettings: Codable, Identifiable, Equatable {
    let folder: String
    let stateDir: String
    let recipe: ProcessingRecipe
    let presetID: String?
    let presetName: String?
    let needsAnalysis: Bool
    var id: String { folder }

    enum CodingKeys: String, CodingKey {
        case folder, recipe
        case stateDir = "state_dir"
        case presetID = "preset_id"
        case presetName = "preset_name"
        case needsAnalysis = "needs_analysis"
    }
}

struct SettingsPreset: Codable, Identifiable, Equatable {
    let id: String
    let name: String
    let builtIn: Bool
    let recipe: ProcessingRecipe

    enum CodingKeys: String, CodingKey {
        case id, name, recipe
        case builtIn = "built_in"
    }
}

struct PresetCatalog: Codable {
    let presets: [SettingsPreset]
    let defaultPresetID: String

    enum CodingKeys: String, CodingKey {
        case presets
        case defaultPresetID = "default_preset_id"
    }
}

struct OptimizationPreview: Codable, Identifiable {
    let root: String
    let relpath: String
    let operation: String
    let sourceSize: Int64

    var id: String { root + "|" + relpath }

    var fileURL: URL {
        URL(fileURLWithPath: root).appendingPathComponent(relpath)
    }

    var filename: String {
        fileURL.lastPathComponent
    }

    var actionTitle: String {
        switch operation {
        case "CONVERT_IMAGE": return "Optimize image"
        case "CONVERT_VIDEO": return "Optimize video"
        case "CONVERT_AUDIO": return "Optimize audio"
        case "RENAME": return "Standardize filename"
        default: return "Planned change"
        }
    }

    enum CodingKeys: String, CodingKey {
        case root, relpath, operation
        case sourceSize = "source_size"
    }
}

struct ScanResultItem: Decodable, Identifiable {
    let root: String
    let stateDir: String
    let relpath: String
    let operation: String
    let sourceSize: Int64
    let reason: String
    let category: String
    let detail: String
    let destination: String?
    let planPath: String?
    let embeddedDate: String?
    let canEditDate: Bool?

    var id: String { root + "|" + relpath }
    var fileURL: URL {
        let original = URL(fileURLWithPath: root).appendingPathComponent(relpath)
        if category == "unchanged", let destination,
           !FileManager.default.fileExists(atPath: original.path) {
            let output = URL(fileURLWithPath: root).appendingPathComponent(destination)
            if FileManager.default.fileExists(atPath: output.path) { return output }
        }
        return original
    }
    var filename: String { fileURL.lastPathComponent }
    var dateEditingUnavailableReason: String {
        if reason == "empty_file" {
            return "There is no media content in this empty file to add a date to."
        }
        if reason == "media_probe_failed" || reason == "video_source_probe_failed" {
            return "Date editing is unavailable because this file could not be read safely."
        }
        if reason == "excluded_directory" {
            return "Date editing is disabled because this file is in a skipped subfolder."
        }
        if operation == "PRESERVE" {
            return "Date editing is disabled to keep this protected file unchanged."
        }
        return "Date editing is not available for this file format."
    }
    var actionTitle: String {
        guard category != "unchanged" else { return "Keep unchanged" }
        if category == "review" { return reviewExplanation.title }
        switch operation {
        case "CONVERT_IMAGE": return "Optimize image"
        case "CONVERT_VIDEO": return "Optimize video"
        case "CONVERT_AUDIO": return "Optimize audio"
        case "RENAME": return "Rename file"
        case "REVIEW": return "Needs your decision"
        default: return "Keep unchanged"
        }
    }
    var reviewExplanation: ReviewExplanation { ReviewExplanation(reason: reason) }
    enum CodingKeys: String, CodingKey {
        case root, relpath, operation, reason, category, detail, destination
        case stateDir = "state_dir"
        case sourceSize = "source_size"
        case planPath = "plan_path"
        case embeddedDate = "embedded_date"
        case canEditDate = "can_edit_date"
    }
}

struct ScanResultsPage: Decodable {
    let scanID: String
    let items: [ScanResultItem]
    let total: Int
    let offset: Int
    let limit: Int
    let counts: [String: Int]
    enum CodingKeys: String, CodingKey {
        case items, total, offset, limit, counts
        case scanID = "scan_id"
    }
}

struct UISnapshot: Codable {
    let version: String
    let configured: Bool
    let databaseExists: Bool
    let stateDir: String
    let database: String
    let archiveRoot: String?
    let archiveAvailable: Bool
    let scanFolders: [String]
    let unavailableScanFolders: [String]
    let folderSettings: [FolderSettings]?
    let settingsPresets: [SettingsPreset]?
    let defaultPresetID: String?
    let activeAssets: Int
    let committedOutputs: Int
    let optimizedOutputs: Int?
    let renamedOutputs: Int?
    let rolledBackOutputs: Int
    let totalSavingBytes: Int64
    let pendingStagedOutputs: Int?
    let quarantineDirectories: Int
    let annual: AnnualScope
    let latestPlan: LatestPlan?
    let optimizationPreviews: [OptimizationPreview]?
    let unresolvedReviews: [ReviewItem]
    let recentChanges: [RecentChange]
    let filenamePolicy: FilenamePolicySettings
    let dateScope: DateScopeSettings
    let mediaProcessing: MediaProcessingPolicy
    let optimizationSettings: OptimizationSettings?
    let preflight: PreflightStatus

    enum CodingKeys: String, CodingKey {
        case version, configured, database, annual, preflight
        case databaseExists = "database_exists"
        case stateDir = "state_dir"
        case archiveRoot = "archive_root"
        case archiveAvailable = "archive_available"
        case scanFolders = "scan_folders"
        case unavailableScanFolders = "unavailable_scan_folders"
        case folderSettings = "folder_settings"
        case settingsPresets = "settings_presets"
        case defaultPresetID = "default_preset_id"
        case activeAssets = "active_assets"
        case committedOutputs = "committed_outputs"
        case optimizedOutputs = "optimized_outputs"
        case renamedOutputs = "renamed_outputs"
        case rolledBackOutputs = "rolled_back_outputs"
        case totalSavingBytes = "total_saving_bytes"
        case pendingStagedOutputs = "pending_staged_outputs"
        case quarantineDirectories = "quarantine_directories"
        case latestPlan = "latest_plan"
        case optimizationPreviews = "optimization_previews"
        case unresolvedReviews = "unresolved_reviews"
        case recentChanges = "recent_changes"
        case filenamePolicy = "filename_policy"
        case dateScope = "date_scope"
        case mediaProcessing = "media_processing"
        case optimizationSettings = "optimization_settings"
    }
}

struct DateScopeSettings: Codable, Equatable {
    var mode: String
    var start: String?
    var end: String?
    var legacy: Bool

    static let recommended = DateScopeSettings(mode: "older_than_two_years", start: nil, end: nil, legacy: false)

    var summary: String {
        switch mode {
        case "older_than_two_years":
            return "Older than 2 years"
        case "legacy":
            return end.map { "Through \($0)" } ?? "Annual calendar cutoff"
        case "all":
            return "All dates"
        case "within":
            return "Only within \(start ?? "—") through \(end ?? "—")"
        case "outside":
            return "Outside \(start ?? "—") through \(end ?? "—")"
        default:
            return "All dates"
        }
    }
}

struct FilenamePolicySettings: Codable, Equatable {
    var enabled: Bool
    var dateFormat: String
    var maxBytes: Int

    static let recommended = FilenamePolicySettings(enabled: true, dateFormat: "YYMMDD-", maxBytes: 60)

    enum CodingKeys: String, CodingKey {
        case enabled
        case dateFormat = "date_format"
        case maxBytes = "max_bytes"
    }
}

struct PreflightStatus: Codable {
    let tools: [String: ToolStatus]
    let pillow: PillowStatus
    let python: String
    let pythonVersion: String

    enum CodingKeys: String, CodingKey {
        case tools, pillow, python
        case pythonVersion = "python_version"
    }

    var missingRequirements: [String] {
        var missing: [String] = []

        if python.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
            missing.append("Python runtime")
        }

        if !pillow.available {
            missing.append("Pillow")
        }

        for tool in ["file", "ffprobe", "ffmpeg", "HandBrakeCLI", "xattr", "ExifTool", "Perl"] {
            if tools[tool]?.available != true {
                missing.append(tool)
            }
        }

        return missing
    }

    var requiredToolsReady: Bool {
        missingRequirements.isEmpty
    }
}

struct ToolStatus: Codable {
    let available: Bool
    let path: String?
}

struct PillowStatus: Codable {
    let available: Bool
    let version: String?
}

struct AnnualScope: Codable {
    let runYear: Int
    let includeThrough: String
    let cutoffExclusive: String
    enum CodingKeys: String, CodingKey {
        case runYear = "run_year"
        case includeThrough = "include_through"
        case cutoffExclusive = "cutoff_exclusive"
    }
}

struct LatestPlan: Codable {
    let planId: String
    let createdAt: String
    let runDate: String
    let cutoff: String
    let itemCount: Int
    let executableCount: Int
    let remainingExecutableCount: Int?
    let reviewCount: Int
    let unresolvedReviewCount: Int
    let planPath: String?
    enum CodingKeys: String, CodingKey {
        case planId = "plan_id"
        case createdAt = "created_at"
        case runDate = "run_date"
        case cutoff
        case itemCount = "item_count"
        case executableCount = "executable_count"
        case remainingExecutableCount = "remaining_executable_count"
        case reviewCount = "review_count"
        case unresolvedReviewCount = "unresolved_review_count"
        case planPath = "plan_path"
    }
}

struct ReviewItem: Codable, Identifiable {
    var id: String { root + "|" + relpath }
    let root: String
    let stateDir: String
    let relpath: String
    let reason: String
    let sourceSize: Int64
    let planPath: String?
    enum CodingKeys: String, CodingKey {
        case root, relpath, reason
        case stateDir = "state_dir"
        case sourceSize = "source_size"
        case planPath = "plan_path"
    }
    var canProcessNormally: Bool {
        if reason.contains("date_low_confidence") || reason.contains("date_conflict") {
            return true
        }

        let prefix = "video_source_review:apple_quicktime_metadata_streams:"
        guard reason.hasPrefix(prefix) else { return false }

        let countText = String(reason.dropFirst(prefix.count))
        guard let count = Int(countText) else { return false }
        return count > 0
    }

    var reviewExplanation: ReviewExplanation { ReviewExplanation(reason: reason) }
    var category: String { reviewExplanation.category }
    var recommendedAction: String { reviewExplanation.nextStep }
    var title: String { reviewExplanation.title }
    var explanation: String { reviewExplanation.explanation }
}

/// One presentation for review reasons in both the results browser and Review.
/// Keep the original code for diagnostics; never mistake an unknown check for approval.
struct ReviewExplanation {
    let category: String
    let title: String
    let explanation: String
    let nextStep: String
    let isKnown: Bool

    init(reason: String) {
        let prefix = "video_source_review:"
        let codes = reason.hasPrefix(prefix) ? String(reason.dropFirst(prefix.count)) : reason
        let checks = codes.split(separator: ",").map { Self.describe(String($0)) }
        if checks.count == 1, let check = checks.first {
            self = check
        } else if !checks.isEmpty {
            category = "Multiple safety checks"
            title = "\(checks.count) reasons to keep this file unchanged"
            explanation = checks.map { "\($0.title): \($0.explanation)" }.joined(separator: "\n\n")
            nextStep = "Keep the original. Every safety check must be addressed before Veronica can convert this file."
            isKnown = checks.allSatisfy(\.isKnown)
        } else {
            self = Self.describe("")
        }
    }

    private init(_ category: String, _ title: String, _ explanation: String, _ nextStep: String, known: Bool = true) {
        self.category = category
        self.title = title
        self.explanation = explanation
        self.nextStep = nextStep
        self.isKnown = known
    }

    private static func describe(_ code: String) -> Self {
        let key = String(code.split(separator: ":", maxSplits: 1).first ?? "")
        switch key {
        case "embedded_date_missing", "date_unknown", "no_eligibility_date":
            return Self("File date", "No usable date inside the file",
                        "Veronica could not find a usable embedded date. It will not guess from the filename or Finder dates, so this file has been left unchanged.",
                        "If you know the correct date, choose Add date below. Otherwise, keep the original unchanged.")
        case "date_conflict":
            return Self("File date", "The file contains conflicting dates",
                        "The available date evidence disagrees. Using the wrong date could put the file in the wrong date range or give it an incorrect filename.",
                        "Check the date, then use Edit date if available. Approve normal processing only if you accept the selected date.")
        case "date_low_confidence":
            return Self("File date", "The file date is uncertain",
                        "The available date evidence is not reliable enough to choose a date safely.",
                        "Check the date, then use Edit date if available, or keep the original unchanged.")
        case "empty_file":
            return Self("File contents", "The file is empty",
                        "This file contains zero bytes. There is no media content for Veronica to read or optimize.",
                        "Check your original or backup. Veronica cannot repair an empty file.")
        case "media_probe_failed", "video_source_probe_failed":
            return Self("File contents", "The media could not be read safely",
                        "Veronica could not inspect this file's media information. The file may be incomplete, unavailable, damaged, or use an unsupported format; this check does not establish which.",
                        "Try opening the original in another app. If it plays correctly, keep it unchanged and inspect Technical details or export diagnostics.")
        case "image_dimensions_unknown":
            return Self("Image size", "The image size could not be read",
                        "Veronica could not determine this image's dimensions, so it cannot choose or verify a safe resize.",
                        "Preview the original and check that it opens correctly. Keep it unchanged until its dimensions can be read.")
        case "filename_collision", "unicode_or_case_name_collision":
            return Self("Filename", "A filename conflicts with another file",
                        "A filename would conflict with another file, including names that differ only by letter case or equivalent Unicode characters. Veronica will not overwrite either file.",
                        "Give the conflicting files distinct names, then scan again.")
        case "category_mismatch":
            return Self("Media type", "The media type does not match its expected category",
                        "The detected media type differs from the category expected for this file. Veronica has stopped rather than apply the wrong conversion rules.",
                        "Check the file's contents and location, then scan again or keep it unchanged.")
        case "invalid_date_scope":
            return Self("Folder settings", "The folder's date range is invalid",
                        "Veronica cannot apply the selected date range safely.",
                        "Open this folder's settings, correct the date range, and scan again.")
        case "legacy_v2_but_image_exceeds_current_target":
            return Self("Previous optimization", "An earlier optimization used a larger image size",
                        "A legacy processing tag marks this image as processed, but its dimensions exceed this folder's current size limit. Veronica will not automatically recompress it.",
                        "Compare the image with your current settings and keep the original unless you deliberately want another conversion.")
        case "hdr_transfer", "wide_gamut", "dolby_vision", "dolby_vision_side_data", "hdr_mastering_metadata":
            return Self("Color quality", "HDR or wide-gamut color needs protection",
                        "This video contains HDR, Dolby Vision, or wide-gamut color information. The current conversion cannot guarantee preserving its brightness and colors.",
                        "Keep the original to preserve its color information. Automatic conversion is blocked.")
        case "variable_frame_rate":
            return Self("Motion timing", "Video frame timing may change",
                        "The video uses variable frame timing. Conversion could change motion smoothness or audio synchronization.",
                        "Keep the original. Previewing alone cannot verify that a conversion would preserve its timing.")
        case "frame_count_mismatch":
            return Self("Motion timing", "The video's frame counts disagree",
                        "The declared frame count does not agree with the inspected frame timing. Veronica cannot verify a safe conversion.",
                        "Keep the original and check playback. Automatic conversion is blocked.")
        case "non_monotonic_frame_timestamps", "duplicate_frame_timestamps":
            return Self("Motion timing", "Video frame timestamps are inconsistent",
                        "Some video frames have repeated or out-of-order timestamps. Conversion could alter timing or audio synchronization.",
                        "Keep the original and check playback. Automatic conversion is blocked.")
        case "multiple_audio_streams":
            return Self("Audio tracks", "The video has multiple audio tracks",
                        "This video contains more than one audio track. Conversion could discard an alternate language or other audio track.",
                        "Keep the original to preserve every audio track.")
        case "multichannel_audio":
            return Self("Audio channels", "Surround audio needs protection",
                        "This video has more than two audio channels. The current conversion could reduce surround audio to stereo.",
                        "Keep the original to preserve its audio channels.")
        case "extra_subtitle_streams":
            return Self("Subtitle tracks", "The video contains subtitles",
                        "This video has subtitle tracks that the current conversion does not guarantee preserving.",
                        "Keep the original to preserve its subtitles.")
        case "chapters_present":
            return Self("Video chapters", "The video contains chapter markers",
                        "This video has chapter markers. Veronica cannot currently verify that every chapter would survive conversion.",
                        "Keep the original to preserve its chapters.")
        case "apple_quicktime_metadata_streams":
            return Self("Camera metadata", "Conversion would remove camera metadata tracks",
                        "This QuickTime video contains Apple Core Media metadata tracks that Veronica's MP4 conversion does not preserve. These are additional tracks, separate from the picture and sound.",
                        "Keep the original to retain these tracks. Process Normally explicitly accepts their removal; other safety checks still apply.")
        case "extra_data_streams", "extra_attachment_streams":
            return Self("Additional tracks", "The video contains additional data or attachments",
                        "This video includes data tracks or attachments that Veronica cannot guarantee preserving during conversion.",
                        "Keep the original to preserve these additional contents.")
        case "video_stream_count":
            return Self("Video tracks", "The video track layout needs protection",
                        "Veronica expected exactly one video track but found a different track layout. It cannot safely choose what to convert or discard.",
                        "Keep the original to preserve every track.")
        case "no_media_conversion_policy", "no_phase2_policy", "unclassified_content":
            return Self("Supported formats", "No supported conversion is available",
                        "Veronica does not have a verified conversion policy for this media type.",
                        "Keep the original unchanged. Do not change its extension to force conversion.")
        default:
            return Self("Safety check", "A safety check needs attention",
                        "Veronica could not establish that this file can be changed safely, so it has been left unchanged.",
                        "Keep the original. Open Technical details or export diagnostics to investigate the unrecognized check.", known: false)
        }
    }
}

struct RecentChange: Codable, Identifiable {
    var id: String { root + "|" + commitId + "|" + relpath }
    let root: String
    let stateDir: String
    let commitId: String
    let relpath: String
    let operation: String
    let finalPath: String?
    let completedAt: String?
    let sourceSize: Int64
    let outputSize: Int64
    let savingBytes: Int64
    let savingPercent: Double
    enum CodingKeys: String, CodingKey {
        case root, relpath, operation
        case stateDir = "state_dir"
        case commitId = "commit_id"
        case finalPath = "final_path"
        case completedAt = "completed_at"
        case sourceSize = "source_size"
        case outputSize = "output_size"
        case savingBytes = "saving_bytes"
        case savingPercent = "saving_percent"
    }

    var operationLabel: String {
        switch operation {
        case "CONVERT_IMAGE": return "Image"
        case "CONVERT_VIDEO": return "Video"
        case "CONVERT_AUDIO": return "Audio"
        default: return operation
        }
    }
}

struct CleanupOutcome {
    let completed: Bool
    let optimized: Int
    let renamed: Int
    let savedBytes: Int64
    let unreadable: Int
    let kept: Int

    var title: String {
        if !completed { return "Cleanup stopped" }
        if optimized == 0 && savedBytes == 0 { return "No space saved" }
        return unreadable > 0 ? "Cleanup finished" : "Cleanup complete"
    }

    var subtitle: String {
        if !completed { return "Only the changes shown below were applied. Open cleanup details to see why it stopped." }
        if unreadable == 1 { return "1 unreadable file was left unchanged. Other verified files were processed." }
        if unreadable > 1 { return "\(unreadable.formatted()) unreadable files were left unchanged. Other verified files were processed." }
        if optimized == 0 {
            return kept > 0 ? "The replacements didn’t save enough space, so your originals were kept."
                : "No files were compressed. Any filename changes are shown below."
        }
        return "Your optimized files are ready in their folders."
    }

    var formattedSaving: String {
        savedBytes == 0 ? "0 bytes" : ByteCountFormatter.string(fromByteCount: savedBytes, countStyle: .file)
    }
}

struct AnalysisProgress: Decodable {
    let phase: String
    let folder: String
    let folderIndex: Int
    let folderCount: Int
    let completedFiles: Int
    let totalFiles: Int?

    enum CodingKeys: String, CodingKey {
        case phase, folder
        case folderIndex = "folder_index"
        case folderCount = "folder_count"
        case completedFiles = "completed_files"
        case totalFiles = "total_files"
    }

    var fractionCompleted: Double? {
        guard phase == "scanning", let totalFiles, totalFiles > 0 else { return nil }
        return min(max(Double(completedFiles) / Double(totalFiles), 0), 1)
    }

    var title: String {
        switch phase {
        case "discovering": return "Counting files"
        case "scanning": return "Scanning your folder"
        default: return "Preparing your results"
        }
    }
}

struct EngineEvent: Codable, Identifiable {
    let id = UUID()
    let event: String
    let at: String?
    let relpath: String?
    let finalRelpath: String?
    let status: String?
    let savingPercent: Double?
    let error: String?
    let index: Int?
    let total: Int?
    let media: String?
    let operation: String?
    let batchNumber: Int?
    let remainingImages: Int?
    let remainingVideos: Int?
    let executable: Int?
    let review: Int?
    let inventoried: Int?
    let cutoff: String?
    let includeThrough: String?

    enum CodingKeys: String, CodingKey {
        case event, at, relpath, status, error, index, total, media, operation, executable, review, inventoried, cutoff
        case finalRelpath = "final_relpath"
        case savingPercent = "saving_percent"
        case batchNumber = "batch_number"
        case remainingImages = "remaining_images"
        case remainingVideos = "remaining_videos"
        case includeThrough = "include_through"
    }

    var title: String {
        switch event {
        case "annual_started": return "Maintenance started"
        case "annual_cutoff": return "Date scope confirmed"
        case "plan_complete": return "Folder scan complete"
        case "batch_started": return "Starting conversion batch"
        case "staging_started": return "Preparing verified replacements"
        case "stage_item":
            if status == "STAGED_VERIFIED" { return "Verified replacement" }
            if status == "KEEP_ORIGINAL" { return "Keeping original" }
            if status == "SOURCE_UNREADABLE" { return "Unreadable file left unchanged" }
            if status == "FAILED" { return "Verification failed" }
            return "Staging media"
        case "commit_item": return "Committed verified replacement"
        case "annual_complete": return "Maintenance complete"
        default: return event.replacingOccurrences(of: "_", with: " ").capitalized
        }
    }

    var detail: String? {
        if let relpath { return relpath }
        if event == "annual_cutoff", let includeThrough { return "Media through \(includeThrough)" }
        if event == "plan_complete" {
            let inventory = inventoried.map { "\($0.formatted()) files" } ?? "Folder"
            let work = executable.map { "\($0) executable" } ?? ""
            let reviews = review.map { "\($0) review" } ?? ""
            return [inventory, work, reviews].filter { !$0.isEmpty }.joined(separator: " • ")
        }
        if event == "batch_started" {
            let images = remainingImages ?? 0
            let videos = remainingVideos ?? 0
            return "\(images) image(s), \(videos) video(s) remaining"
        }
        if let error { return error }
        return nil
    }
}
