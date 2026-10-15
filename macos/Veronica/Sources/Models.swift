import Foundation

struct MediaProcessingPolicy: Codable {
    let images: Bool
    let videos: Bool
    let audio: Bool
    let imageExtensions: [String]
    let videoExtensions: [String]
    let audioExtensions: [String]

    static let allImageExtensions = [".bmp", ".gif", ".heic", ".heif", ".jpeg", ".jpg", ".png", ".webp"]
    static let allVideoExtensions = [".3gp", ".avi", ".m2ts", ".m4v", ".mkv", ".mov", ".mp4", ".mts", ".webm"]
    static let allAudioExtensions = [".aac", ".aif", ".aiff", ".amr", ".flac", ".m4a", ".m4r", ".mp3", ".ogg", ".opus", ".wav"]

    enum CodingKeys: String, CodingKey {
        case images
        case videos
        case audio
        case imageExtensions = "image_extensions"
        case videoExtensions = "video_extensions"
        case audioExtensions = "audio_extensions"
    }

    init(
        images: Bool,
        videos: Bool,
        audio: Bool,
        imageExtensions: [String],
        videoExtensions: [String],
        audioExtensions: [String]
    ) {
        self.images = images
        self.videos = videos
        self.audio = audio
        self.imageExtensions = imageExtensions
        self.videoExtensions = videoExtensions
        self.audioExtensions = audioExtensions
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        let images = try container.decodeIfPresent(Bool.self, forKey: .images) ?? true
        let videos = try container.decodeIfPresent(Bool.self, forKey: .videos) ?? true
        let audio = try container.decodeIfPresent(Bool.self, forKey: .audio) ?? true

        self.images = images
        self.videos = videos
        self.audio = audio
        self.imageExtensions = try container.decodeIfPresent([String].self, forKey: .imageExtensions)
            ?? (images ? Self.allImageExtensions : [])
        self.videoExtensions = try container.decodeIfPresent([String].self, forKey: .videoExtensions)
            ?? (videos ? Self.allVideoExtensions : [])
        self.audioExtensions = try container.decodeIfPresent([String].self, forKey: .audioExtensions)
            ?? (audio ? Self.allAudioExtensions : [])
    }
}

struct OptimizationSettings: Codable {
    let imageOutputFormat: String
    let imageMaxMegapixels: Double
    let jpegQuality: Int
    let videoMaxEdge: Int
    let audioMinSizeMB: Int
    let videoAllowCameraMetadataDrop: Bool

    static let recommended = OptimizationSettings(
        imageOutputFormat: "jpeg",
        imageMaxMegapixels: 10,
        jpegQuality: 50,
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
    let activeAssets: Int
    let committedOutputs: Int
    let rolledBackOutputs: Int
    let totalSavingBytes: Int64
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
        case activeAssets = "active_assets"
        case committedOutputs = "committed_outputs"
        case rolledBackOutputs = "rolled_back_outputs"
        case totalSavingBytes = "total_saving_bytes"
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

struct DateScopeSettings: Codable {
    let mode: String
    let start: String?
    let end: String?
    let legacy: Bool

    var summary: String {
        switch mode {
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

struct FilenamePolicySettings: Codable {
    let enabled: Bool
    let dateFormat: String
    let maxBytes: Int

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

        for tool in ["file", "ffprobe", "ffmpeg", "HandBrakeCLI", "xattr"] {
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
