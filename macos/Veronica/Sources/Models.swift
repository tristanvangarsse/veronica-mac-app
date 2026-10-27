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
    var actionTitle: String {
        guard category != "unchanged" else { return "Keep unchanged" }
        switch operation {
        case "CONVERT_IMAGE": return "Optimize image"
        case "CONVERT_VIDEO": return "Optimize video"
        case "CONVERT_AUDIO": return "Optimize audio"
        case "RENAME": return "Rename file"
        case "REVIEW": return "Needs your decision"
        default: return "Keep unchanged"
        }
    }
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

    var category: String {
        if reason == "embedded_date_missing" { return "Date evidence" }
        if reason.contains("dolby_vision") || reason.contains("hdr_transfer") || reason.contains("wide_gamut") {
            return "Color quality"
        }
        if reason.contains("variable_frame_rate")
            || reason.contains("frame_count_mismatch")
            || reason.contains("non_monotonic_frame_timestamps")
            || reason.contains("duplicate_frame_timestamps") {
            return "Motion timing"
        }
        if reason.contains("multiple_audio_streams")
            || reason.contains("multichannel_audio")
            || reason.contains("extra_subtitle_streams")
            || reason.contains("chapters_present")
            || reason.contains("extra_attachment_streams")
            || reason.contains("video_stream_count") {
            return "Extra tracks"
        }
        if reason.contains("date_low_confidence")
            || reason.contains("date_conflict")
            || reason.contains("date_unknown")
            || reason.contains("no_eligibility_date") {
            return "Date evidence"
        }
        if reason.contains("legacy_v2_but_image_exceeds_current_target") {
            return "Previous optimization"
        }
        return "Needs decision"
    }

    var recommendedAction: String {
        if reason == "embedded_date_missing" { return "Keep the original. Veronica needs a usable date stored inside the file." }
        if category == "Color quality" {
            return "Keep the original unless you are comfortable losing HDR or Dolby Vision behavior."
        }
        if category == "Motion timing" {
            return "Preview first. Keep the original if smooth playback matters."
        }
        if category == "Extra tracks" {
            return "Keep the original if subtitles, chapters, surround audio, or alternate tracks matter."
        }
        if category == "Date evidence" {
            return "Only needed when date-based organization or date ranges are active."
        }
        return "Preview the file, then choose whether Veronica should leave it unchanged."
    }

    var title: String {
        if reason == "embedded_date_missing" { return "No embedded date" }
        if category == "Color quality" { return "HDR or Dolby Vision video" }
        if reason.contains("variable_frame_rate") { return "Video timing may change" }
        if reason.contains("frame_count_mismatch") { return "Video timing is inconsistent" }
        if reason.contains("date_low_confidence") { return "Date needs review" }
        if reason.contains("date_conflict") { return "Conflicting dates" }
        if reason.contains("multiple_audio_streams") { return "Multiple audio tracks" }
        if reason.contains("multichannel_audio") { return "Surround audio" }
        if reason.contains("extra_subtitle_streams") { return "Subtitle tracks" }
        if reason.contains("chapters_present") { return "Video chapters" }
        if reason.contains("apple_quicktime_metadata_streams") { return "Camera metadata" }
        if reason.contains("legacy_v2_but_image_exceeds_current_target") { return "Previously processed large image" }
        if reason.contains("category_mismatch") { return "Media type does not match its folder" }
        if reason.contains("empty_file") { return "Empty file" }
        return "Needs review"
    }

    var explanation: String {
        if reason == "embedded_date_missing" {
            return "This file has no usable embedded date. It stays unchanged until its date can be read from inside the file."
        }
        if category == "Color quality" {
            return "This video carries HDR, Dolby Vision, or wide-gamut color information. A standard optimization can change how it looks, so Veronica will not transcode it automatically."
        }
        if reason.contains("variable_frame_rate") {
            return "The video uses variable frame timing. Transcoding can alter motion smoothness or audio sync, even when duration checks pass."
        }
        if reason.contains("frame_count_mismatch") {
            return "The container's declared frame count does not agree with decoded frame timing, so automatic conversion is blocked."
        }
        if category == "Extra tracks" {
            return "This file contains extra streams such as alternate audio, subtitles, chapters, attachments, or surround channels. Veronica does not assume those can be discarded."
        }
        if reason.contains("date_low_confidence") {
            return "The available date evidence is not strong enough for date-based organization."
        }
        if reason.contains("apple_quicktime_metadata_streams") {
            return "This QuickTime video contains Apple Core Media metadata tracks that are not preserved by Veronica's MP4 conversion. You can approve normal processing or keep the original unchanged."
        }
        if reason.contains("legacy_v2_but_image_exceeds_current_target") {
            return "This image was historically processed, but it is larger than today's dimensional target."
        }
        return reason
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
