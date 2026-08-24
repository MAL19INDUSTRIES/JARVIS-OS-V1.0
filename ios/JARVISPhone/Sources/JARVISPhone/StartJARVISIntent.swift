import AppIntents
import Foundation

struct StartJARVISIntent: AppIntent {
    static var title: LocalizedStringResource = "Start JARVIS"
    static var description = IntentDescription("Open JARVIS and begin listening for a request.")
    static var openAppWhenRun = true

    func perform() async throws -> some IntentResult {
        UserDefaults.standard.set(true, forKey: "jarvis-start-listening")
        NotificationCenter.default.post(name: .jarvisVoiceActivationRequested, object: nil)
        return .result()
    }
}

extension Notification.Name {
    static let jarvisVoiceActivationRequested = Notification.Name(
        "com.mal19industries.jarvisphone.start-listening"
    )
}

struct JARVISAppShortcuts: AppShortcutsProvider {
    static var appShortcuts: [AppShortcut] {
        AppShortcut(
            intent: StartJARVISIntent(),
            phrases: [
                "Start \(.applicationName)",
                "Talk to \(.applicationName)",
                "Ask \(.applicationName)",
            ],
            shortTitle: "Start JARVIS",
            systemImageName: "waveform.circle.fill"
        )
    }
}
