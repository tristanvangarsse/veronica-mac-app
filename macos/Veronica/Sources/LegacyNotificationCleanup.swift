import UserNotifications

// Remove requests left by older Veronica versions without asking for permission.
enum LegacyNotificationCleanup {
    static func clear() {
        let center = UNUserNotificationCenter.current()
        center.removeAllPendingNotificationRequests()
        center.removeAllDeliveredNotifications()
    }
}
