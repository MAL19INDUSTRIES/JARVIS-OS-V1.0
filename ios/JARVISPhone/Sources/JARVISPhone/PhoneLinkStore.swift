import Foundation
import Combine

@MainActor
final class JARVISStore: ObservableObject {
    @Published private(set) var profile: UserProfile?
    @Published private(set) var messages: [PhoneMessage] = []
    @Published private(set) var phase: JARVISPhase = .signedOut
    @Published private(set) var status = "Sign in to reach JARVIS"
    @Published private(set) var authBusy = false
    @Published private(set) var authError: String?
    @Published var pendingAction: PhoneAction?
    @Published var draft = ""
    @Published private(set) var activationRequest = UUID()

    private let serverURL: URL
    private var accessToken: String?
    private var hasStarted = false
    private var voiceActivationPending = false
    private var completionTask: Task<Void, Never>?

    var isSignedIn: Bool { profile != nil && accessToken != nil }
    var isAIConfigured: Bool { profile?.geminiConfigured == true }

    init(serverURL: URL = JARVISStore.configuredServerURL) {
        self.serverURL = serverURL
        self.accessToken = KeychainStore.read("cloud-access-token")
    }

    static var configuredServerURL: URL {
        if let override = ProcessInfo.processInfo.environment["JARVIS_API_BASE_URL"],
           let url = URL(string: override) {
            return url
        }
        let configured = Bundle.main.object(forInfoDictionaryKey: "JARVISAPIBaseURL") as? String
        return URL(string: configured ?? "http://localhost:8000")!
    }

    func start() {
        guard !hasStarted else { return }
        hasStarted = true
        guard accessToken != nil else {
            phase = .signedOut
            return
        }
        Task { await restoreSession() }
    }

    func signIn(email: String, password: String) async {
        await authenticate(
            path: "/auth/login",
            payload: ["email": email, "password": password]
        )
    }

    func signUp(displayName: String, email: String, password: String) async {
        await authenticate(
            path: "/auth/signup",
            payload: [
                "display_name": displayName,
                "email": email,
                "password": password,
            ]
        )
    }

    func configureAI(apiKey: String) async {
        let clean = apiKey.trimmingCharacters(in: .whitespacesAndNewlines)
        guard clean.count >= 20 else {
            authError = "Enter a valid Gemini API key."
            return
        }
        authBusy = true
        authError = nil
        do {
            let payload = try JSONSerialization.data(withJSONObject: [
                "api_key": clean,
                "validate": true,
            ])
            let (data, response) = try await request(
                path: "/me/gemini-key",
                method: "POST",
                body: payload,
                authenticated: true
            )
            try validate(response: response, data: data)
            await restoreSession()
        } catch {
            authError = error.localizedDescription
        }
        authBusy = false
    }

    func send() {
        let message = draft.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !message.isEmpty, isSignedIn, isAIConfigured else { return }
        draft = ""
        completionTask?.cancel()
        messages.append(PhoneMessage(role: "user", content: message))
        phase = .thinking
        status = "Working on your request"

        Task {
            do {
                let payload = try JSONSerialization.data(withJSONObject: [
                    "message": message,
                    "client_kind": "ios",
                ])
                let (data, response) = try await request(
                    path: "/chat",
                    method: "POST",
                    body: payload,
                    authenticated: true
                )
                try validate(response: response, data: data)
                let reply = try JSONDecoder().decode(CloudChatResponse.self, from: data)
                messages.append(PhoneMessage(role: "assistant", content: reply.response))
                pendingAction = reply.handoff
                if reply.handoff != nil {
                    phase = .acting
                    status = "Your approval is required"
                } else {
                    markComplete()
                }
            } catch {
                phase = .offline
                status = error.localizedDescription
                messages.append(PhoneMessage(
                    role: "system",
                    content: error.localizedDescription
                ))
            }
        }
    }

    func submitVoiceCommand(_ command: String) {
        let clean = command.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !clean.isEmpty else {
            phase = .ready
            status = "Ready for your request"
            return
        }
        draft = clean
        send()
    }

    func beginListening() {
        completionTask?.cancel()
        phase = .listening
        status = "Listening"
    }

    func listeningFailed(_ message: String) {
        phase = .offline
        status = message
    }

    func actionCompleted() {
        pendingAction = nil
        markComplete()
    }

    func requestVoiceActivation() {
        guard isSignedIn, isAIConfigured else {
            voiceActivationPending = true
            return
        }
        voiceActivationPending = false
        activationRequest = UUID()
    }

    func handleDeepLink(_ url: URL) {
        guard url.scheme?.lowercased() == "jarvisphone" else { return }
        if url.host?.lowercased() == "listen" {
            requestVoiceActivation()
        }
    }

    func consumeIntentActivation() {
        let defaults = UserDefaults.standard
        guard defaults.bool(forKey: "jarvis-start-listening") else { return }
        defaults.set(false, forKey: "jarvis-start-listening")
        requestVoiceActivation()
    }

    func signOut() {
        completionTask?.cancel()
        accessToken = nil
        profile = nil
        messages = []
        pendingAction = nil
        phase = .signedOut
        status = "Sign in to reach JARVIS"
        authError = nil
        KeychainStore.delete("cloud-access-token")
    }

    func deleteAccount() async {
        do {
            let (data, response) = try await request(
                path: "/auth/account",
                method: "DELETE",
                body: nil,
                authenticated: true
            )
            try validate(response: response, data: data)
            signOut()
        } catch {
            phase = .offline
            status = error.localizedDescription
        }
    }

    private func authenticate(path: String, payload: [String: String]) async {
        authBusy = true
        authError = nil
        do {
            let body = try JSONSerialization.data(withJSONObject: payload)
            let (data, response) = try await request(
                path: path,
                method: "POST",
                body: body,
                authenticated: false
            )
            try validate(response: response, data: data)
            let session = try JSONDecoder().decode(AuthSession.self, from: data)
            accessToken = session.accessToken
            profile = session.user
            KeychainStore.write(session.accessToken, account: "cloud-access-token")
            phase = .ready
            status = "Ready for your request"
            await loadHistory()
            triggerPendingVoiceActivation()
        } catch {
            authError = error.localizedDescription
            phase = .signedOut
        }
        authBusy = false
    }

    private func restoreSession() async {
        do {
            let (data, response) = try await request(
                path: "/auth/me",
                method: "GET",
                body: nil,
                authenticated: true
            )
            try validate(response: response, data: data)
            profile = try JSONDecoder().decode(UserProfile.self, from: data)
            phase = .ready
            status = "Ready for your request"
            await loadHistory()
            triggerPendingVoiceActivation()
        } catch PhoneCloudError.unauthorized {
            signOut()
        } catch {
            phase = .offline
            status = error.localizedDescription
        }
    }

    private func loadHistory() async {
        do {
            let (data, response) = try await request(
                path: "/chat/history",
                method: "GET",
                body: nil,
                authenticated: true
            )
            try validate(response: response, data: data)
            messages = try JSONDecoder().decode([PhoneMessage].self, from: data)
        } catch {
            // A usable signed-in session matters more than restoring old chat.
        }
    }

    private func markComplete() {
        phase = .complete
        status = "Request complete"
        completionTask?.cancel()
        completionTask = Task { [weak self] in
            try? await Task.sleep(for: .seconds(1.1))
            guard !Task.isCancelled else { return }
            self?.phase = .ready
            self?.status = "Ready for your request"
        }
    }

    private func triggerPendingVoiceActivation() {
        guard voiceActivationPending, isSignedIn, isAIConfigured else { return }
        voiceActivationPending = false
        activationRequest = UUID()
    }

    private func request(
        path: String,
        method: String,
        body: Data?,
        authenticated: Bool
    ) async throws -> (Data, HTTPURLResponse) {
        guard let url = URL(string: path, relativeTo: serverURL)?.absoluteURL else {
            throw PhoneCloudError.invalidServer
        }
        var request = URLRequest(url: url, timeoutInterval: 20)
        request.httpMethod = method
        request.httpBody = body
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        if authenticated, let accessToken {
            request.setValue("Bearer \(accessToken)", forHTTPHeaderField: "Authorization")
        }
        let (data, response) = try await URLSession.shared.data(for: request)
        guard let http = response as? HTTPURLResponse else {
            throw PhoneCloudError.invalidResponse
        }
        return (data, http)
    }

    private func validate(response: HTTPURLResponse, data: Data) throws {
        if response.statusCode == 401 { throw PhoneCloudError.unauthorized }
        guard (200..<300).contains(response.statusCode) else {
            let payload = try? JSONDecoder().decode(APIErrorResponse.self, from: data)
            throw PhoneCloudError.server(
                payload?.detail ?? payload?.error ?? "JARVIS could not complete that request."
            )
        }
    }
}

enum PhoneCloudError: LocalizedError {
    case invalidServer
    case invalidResponse
    case unauthorized
    case server(String)

    var errorDescription: String? {
        switch self {
        case .invalidServer: return "The JARVIS cloud address is invalid."
        case .invalidResponse: return "JARVIS returned an invalid response."
        case .unauthorized: return "Your JARVIS session expired. Sign in again."
        case .server(let detail): return detail
        }
    }
}
