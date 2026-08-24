import Foundation
import UIKit
import Combine

@MainActor
final class PhoneLinkStore: ObservableObject {
    @Published private(set) var messages: [PhoneMessage] = []
    @Published private(set) var persona = "JARVIS"
    @Published private(set) var status = "Scan the Phone Link QR on your Mac"
    @Published private(set) var connected = false
    @Published var pendingAction: PhoneAction?
    @Published var draft = ""

    private var serverURL: URL?
    private var deviceToken: String?
    private var lastSequence = 0
    private var pollTask: Task<Void, Never>?

    init() {
        if let server = KeychainStore.read("server"), let url = URL(string: server) {
            serverURL = url
        }
        deviceToken = KeychainStore.read("device-token")
    }

    func handleDeepLink(_ url: URL) {
        guard url.scheme?.lowercased() == "jarvisphone",
              url.host?.lowercased() == "pair",
              let components = URLComponents(url: url, resolvingAgainstBaseURL: false),
              let serverValue = components.queryItems?.first(where: { $0.name == "server" })?.value,
              let token = components.queryItems?.first(where: { $0.name == "token" })?.value,
              token.count >= 20,
              let server = URL(string: serverValue),
              Self.isAllowedLocalServer(server) else {
            status = "That pairing link is not a trusted local JARVIS address."
            return
        }
        Task { await pair(server: server, token: token) }
    }

    func start() {
        guard pollTask == nil, serverURL != nil, deviceToken != nil else { return }
        pollTask = Task { [weak self] in
            while !Task.isCancelled {
                await self?.poll()
                try? await Task.sleep(for: .seconds(1.1))
            }
        }
    }

    func stop() {
        pollTask?.cancel()
        pollTask = nil
    }

    func send() {
        let message = draft.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !message.isEmpty, connected else { return }
        draft = ""
        Task {
            do {
                status = "Sending…"
                let payload = try JSONSerialization.data(withJSONObject: ["message": message])
                let (data, response) = try await request(
                    path: "/api/phone/chat",
                    method: "POST",
                    body: payload,
                    authenticated: true
                )
                try validate(response: response, data: data)
                let reply = try JSONDecoder().decode(ChatResponse.self, from: data)
                pendingAction = reply.handoff
                await poll()
            } catch {
                status = error.localizedDescription
            }
        }
    }

    func forgetConnection() {
        stop()
        serverURL = nil
        deviceToken = nil
        connected = false
        messages = []
        lastSequence = 0
        KeychainStore.delete("server")
        KeychainStore.delete("device-token")
        status = "Scan the Phone Link QR on your Mac"
    }

    private func pair(server: URL, token: String) async {
        stop()
        serverURL = server
        status = "Pairing with your Mac…"
        do {
            let payload = try JSONSerialization.data(withJSONObject: [
                "pair_token": token,
                "device_name": UIDevice.current.name,
                "client_kind": "ios-native",
            ])
            let (data, response) = try await request(
                path: "/api/phone/pair",
                method: "POST",
                body: payload,
                authenticated: false
            )
            try validate(response: response, data: data)
            let paired = try JSONDecoder().decode(PairingResponse.self, from: data)
            deviceToken = paired.deviceToken
            KeychainStore.write(server.absoluteString, account: "server")
            KeychainStore.write(paired.deviceToken, account: "device-token")
            connected = true
            status = "Connected on local Wi-Fi"
            await poll()
            start()
        } catch {
            connected = false
            status = error.localizedDescription
        }
    }

    private func poll() async {
        guard serverURL != nil, deviceToken != nil else { return }
        do {
            let (data, response) = try await request(
                path: "/api/phone/session?after=\(lastSequence)",
                method: "GET",
                body: nil,
                authenticated: true
            )
            if response.statusCode == 401 {
                forgetConnection()
                status = "This iPhone link was revoked. Scan a new QR code."
                return
            }
            try validate(response: response, data: data)
            let session = try JSONDecoder().decode(SessionResponse.self, from: data)
            persona = session.persona
            for item in session.messages where !messages.contains(where: { $0.seq == item.seq }) {
                messages.append(item)
                lastSequence = max(lastSequence, item.seq)
            }
            connected = session.connected
            status = "Connected on local Wi-Fi"
        } catch {
            connected = false
            status = "Waiting for your Mac…"
        }
    }

    private func request(
        path: String,
        method: String,
        body: Data?,
        authenticated: Bool
    ) async throws -> (Data, HTTPURLResponse) {
        guard let base = serverURL, let url = URL(string: path, relativeTo: base)?.absoluteURL else {
            throw PhoneLinkClientError.invalidServer
        }
        var request = URLRequest(url: url, timeoutInterval: 9)
        request.httpMethod = method
        request.httpBody = body
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        if authenticated, let deviceToken {
            request.setValue("Bearer \(deviceToken)", forHTTPHeaderField: "Authorization")
        }
        let (data, response) = try await URLSession.shared.data(for: request)
        guard let http = response as? HTTPURLResponse else {
            throw PhoneLinkClientError.invalidResponse
        }
        return (data, http)
    }

    private func validate(response: HTTPURLResponse, data: Data) throws {
        guard (200..<300).contains(response.statusCode) else {
            let detail = (try? JSONDecoder().decode(APIErrorResponse.self, from: data).error)
            throw PhoneLinkClientError.server(detail ?? "JARVIS could not complete that request.")
        }
    }

    private static func isAllowedLocalServer(_ url: URL) -> Bool {
        guard ["http", "https"].contains(url.scheme?.lowercased() ?? ""),
              url.user == nil, url.password == nil, let rawHost = url.host else { return false }
        let host = rawHost.lowercased()
        if host == "localhost" || host.hasSuffix(".local") || host == "127.0.0.1" { return true }
        if host.hasPrefix("10.") || host.hasPrefix("192.168.") { return true }
        if host.hasPrefix("fc") || host.hasPrefix("fd") || host.hasPrefix("fe80:") { return true }
        let pieces = host.split(separator: ".").compactMap { Int($0) }
        return pieces.count == 4 && pieces[0] == 172 && (16...31).contains(pieces[1])
    }
}

enum PhoneLinkClientError: LocalizedError {
    case invalidServer
    case invalidResponse
    case server(String)

    var errorDescription: String? {
        switch self {
        case .invalidServer: return "The saved JARVIS address is invalid. Scan a new QR code."
        case .invalidResponse: return "JARVIS returned an invalid response."
        case .server(let detail): return detail
        }
    }
}
