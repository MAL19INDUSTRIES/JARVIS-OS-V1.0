import SwiftUI

@main
struct JARVISPhoneApp: App {
    @StateObject private var store = PhoneLinkStore()

    var body: some Scene {
        WindowGroup {
            ContentView()
                .environmentObject(store)
                .onOpenURL { store.handleDeepLink($0) }
        }
    }
}
