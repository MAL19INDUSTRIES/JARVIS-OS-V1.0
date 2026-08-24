import Foundation

enum JARVISPhase: String, Equatable {
    case signedOut
    case ready
    case listening
    case thinking
    case acting
    case complete
    case offline

    var label: String {
        switch self {
        case .signedOut: return "SIGN IN"
        case .ready: return "READY"
        case .listening: return "LISTENING"
        case .thinking: return "THINKING"
        case .acting: return "AWAITING APPROVAL"
        case .complete: return "DONE"
        case .offline: return "OFFLINE"
        }
    }

    var isActive: Bool {
        self == .listening || self == .thinking || self == .acting
    }
}

struct PhoneMessage: Codable, Identifiable, Equatable {
    let id: String
    let role: String
    let content: String
    let createdAt: String?

    init(id: String = UUID().uuidString, role: String, content: String, createdAt: String? = nil) {
        self.id = id
        self.role = role
        self.content = content
        self.createdAt = createdAt
    }

    enum CodingKeys: String, CodingKey {
        case id, role, content
        case createdAt = "created_at"
    }
}

struct PhoneAction: Codable, Identifiable, Equatable {
    let kind: String
    let label: String
    let message: String
    let url: String?
    let recipient: String?
    let contact: String?
    let copy: String?

    var id: String {
        [kind, label, url ?? "", recipient ?? "", contact ?? "", copy ?? ""]
            .joined(separator: "|")
    }
}

struct UserProfile: Codable, Equatable {
    let id: String
    let email: String
    let displayName: String
    let geminiConfigured: Bool

    enum CodingKeys: String, CodingKey {
        case id, email
        case displayName = "display_name"
        case geminiConfigured = "gemini_configured"
    }
}

struct AuthSession: Codable {
    let accessToken: String
    let user: UserProfile

    enum CodingKeys: String, CodingKey {
        case accessToken = "access_token"
        case user
    }
}

struct CloudChatResponse: Codable {
    let response: String
    let handoff: PhoneAction?
}

struct APIErrorResponse: Codable {
    let detail: String?
    let error: String?
}
