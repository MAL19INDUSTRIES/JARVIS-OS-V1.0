import Foundation

struct PhoneMessage: Codable, Identifiable, Equatable {
    let seq: Int
    let role: String
    let content: String
    let source: String
    let time: Double

    var id: Int { seq }
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

struct LinkedDevice: Codable {
    let id: String
    let name: String
    let clientKind: String?

    enum CodingKeys: String, CodingKey {
        case id, name
        case clientKind = "client_kind"
    }
}

struct PairingResponse: Codable {
    let deviceToken: String
    let device: LinkedDevice

    enum CodingKeys: String, CodingKey {
        case deviceToken = "device_token"
        case device
    }
}

struct SessionResponse: Codable {
    let connected: Bool
    let persona: String
    let messages: [PhoneMessage]
}

struct ChatResponse: Codable {
    let accepted: Bool
    let handoff: PhoneAction?
}

struct APIErrorResponse: Codable {
    let error: String
}
