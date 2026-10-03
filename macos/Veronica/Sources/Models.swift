import Foundation

struct MediaProcessingPolicy: Codable {
    let images: Bool
    let videos: Bool
    let audio: Bool
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
    let unresolvedReviews: [ReviewItem]
    let recentChanges: [RecentChange]
    let filenamePolicy: FilenamePolicySettings
    let dateScope: DateScopeSettings
    let mediaProcessing: MediaProcessingPolicy
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
        case unresolvedReviews = "unresolved_reviews"
        case recentChanges = "recent_changes"
        case filenamePolicy = "filename_policy"
        case dateScope = "date_scope"
        case mediaProcessing = "media_processing"
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
        reason.contains("date_low_confidence") || reason.contains("date_conflict")
    }


    var title: String {
        if reason.contains("variable_frame_rate") { return "Variable frame timing" }
        if reason.contains("frame_count_mismatch") { return "Inconsistent frame count" }
        if reason.contains("date_low_confidence") { return "Date needs review" }
        if reason.contains("date_conflict") { return "Conflicting dates" }
        if reason.contains("legacy_v2_but_image_exceeds_current_target") { return "Previously processed large image" }
        if reason.contains("category_mismatch") { return "Media type does not match its folder" }
        if reason.contains("empty_file") { return "Empty file" }
        return "Needs review"
    }

    var explanation: String {
        if reason.contains("variable_frame_rate") {
            return "Frame timing varies enough that Veronica will not automatically transcode this video."
        }
        if reason.contains("frame_count_mismatch") {
            return "The container's declared frame count does not agree with decoded frame timing, so automatic conversion is blocked."
        }
        if reason.contains("date_low_confidence") {
            return "The available date evidence is not strong enough for Veronica to make an automatic decision."
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
