import AppKit
import Foundation
import UserNotifications

@MainActor
final class NotificationManager: NSObject, ObservableObject, UNUserNotificationCenterDelegate {
    static let shared = NotificationManager()

    private let userDefaultsKey = "veronica.notifications.enabled"
    private let center = UNUserNotificationCenter.current()
    private var authorizationError: String?

    @Published private(set) var authorizationStatus: UNAuthorizationStatus = .notDetermined
    @Published var isEnabled: Bool {
        didSet {
            UserDefaults.standard.set(isEnabled, forKey: userDefaultsKey)
            if isEnabled {
                Task { await requestAuthorizationIfNeeded() }
            }
        }
    }

    var statusLabel: String {
        guard isEnabled else { return "Off in Veronica" }

        switch authorizationStatus {
        case .authorized, .provisional:
            return "Enabled"
        case .denied:
            return "Off in macOS Settings"
        case .notDetermined:
            if authorizationError != nil {
                return "Signed build required"
            }
            return "Permission needed"
        case .ephemeral:
            return "Enabled for this session"
        @unknown default:
            return "Unknown"
        }
    }

    var canDeliver: Bool {
        isEnabled && (authorizationStatus == .authorized || authorizationStatus == .provisional)
    }

    private override init() {
        if UserDefaults.standard.object(forKey: userDefaultsKey) == nil {
            UserDefaults.standard.set(true, forKey: userDefaultsKey)
        }
        isEnabled = UserDefaults.standard.bool(forKey: userDefaultsKey)
        super.init()
        center.delegate = self
    }

    func prepare() async {
        await refreshAuthorizationStatus()
    }

    func setEnabled(_ enabled: Bool) async {
        isEnabled = enabled
        if enabled {
            await requestAuthorizationIfNeeded()
        } else {
            center.removeAllPendingNotificationRequests()
        }
        await refreshAuthorizationStatus()
    }

    func requestAuthorizationIfNeeded() async {
        await refreshAuthorizationStatus()
        guard authorizationStatus == .notDetermined else { return }

        do {
            let granted = try await center.requestAuthorization(
                options: [.alert, .badge, .sound]
            )
            authorizationError = nil
            DiagnosticsCenter.shared.log(
                granted ? "INFO" : "WARN",
                "Notifications",
                granted ? "Notification permission granted" : "Notification permission not granted"
            )
        } catch {
            authorizationError = error.localizedDescription
            DiagnosticsCenter.shared.log(
                "ERROR",
                "Notifications",
                "Notification permission request failed: \(error.localizedDescription)"
            )
        }

        await refreshAuthorizationStatus()
    }

    func refreshAuthorizationStatus() async {
        let settings = await center.notificationSettings()
        authorizationStatus = settings.authorizationStatus
    }

    func notify(title: String, body: String, identifier: String = UUID().uuidString) async {
        guard isEnabled else {
            DiagnosticsCenter.shared.log(
                "INFO",
                "Notifications",
                "Skipped notification while disabled in Veronica: \(title)"
            )
            return
        }

        await requestAuthorizationIfNeeded()
        guard canDeliver else {
            let reason = authorizationStatus == .denied
                ? "macOS permission is denied"
                : "this build is not authorized for native macOS notifications"
            DiagnosticsCenter.shared.log(
                "WARN",
                "Notifications",
                "Skipped notification because \(reason): \(title)"
            )
            return
        }

        let content = UNMutableNotificationContent()
        content.title = title
        content.body = body
        content.sound = .default

        let request = UNNotificationRequest(
            identifier: "veronica.\(identifier)",
            content: content,
            trigger: nil
        )

        do {
            try await center.add(request)
            DiagnosticsCenter.shared.log("INFO", "Notifications", "Delivered notification: \(title)")
        } catch {
            DiagnosticsCenter.shared.log(
                "ERROR",
                "Notifications",
                "Could not deliver notification: \(error.localizedDescription)"
            )
        }
    }

    nonisolated func userNotificationCenter(
        _ center: UNUserNotificationCenter,
        willPresent notification: UNNotification
    ) async -> UNNotificationPresentationOptions {
        [.banner, .list, .sound]
    }

    nonisolated func userNotificationCenter(
        _ center: UNUserNotificationCenter,
        didReceive response: UNNotificationResponse
    ) async {
        await MainActor.run {
            NSApp.activate(ignoringOtherApps: true)
        }
    }

}
