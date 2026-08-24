import AVFoundation
import Contacts
import MessageUI
import SwiftUI
import UserNotifications

struct MessageDraft: Identifiable {
    let id = UUID()
    let recipients: [String]
    let body: String
}

@MainActor
final class NativeActionController: ObservableObject {
    @Published var messageDraft: MessageDraft?
    @Published var cameraPresented = false
    @Published var notice: String?

    func perform(_ action: PhoneAction) {
        switch action.kind {
        case "call":
            open(action.url)
        case "message":
            guard let recipient = action.recipient else {
                notice = "The message recipient was missing."
                return
            }
            presentMessage(to: recipient, body: action.copy ?? "")
        case "open":
            open(action.url)
        case "call-contact", "message-contact":
            resolveContact(for: action)
        case "camera":
            requestCamera()
        case "notifications":
            requestNotifications()
        default:
            notice = "This version of JARVIS does not recognize that phone action."
        }
    }

    private func open(_ value: String?) {
        guard let value, let url = URL(string: value) else {
            notice = "That phone action did not contain a valid link."
            return
        }
        UIApplication.shared.open(url) { [weak self] success in
            if !success { self?.notice = "iOS could not open that action." }
        }
    }

    private func presentMessage(to recipient: String, body: String) {
        guard MFMessageComposeViewController.canSendText() else {
            notice = "Messages is not available on this device."
            return
        }
        messageDraft = MessageDraft(recipients: [recipient], body: body)
    }

    private func resolveContact(for action: PhoneAction) {
        guard let name = action.contact, !name.isEmpty else {
            notice = "The contact name was missing."
            return
        }
        Task {
            do {
                let phone = try await ContactResolver.phoneNumber(matching: name)
                if action.kind == "call-contact" {
                    open("tel:\(phone.filter { $0.isNumber || "+*#".contains($0) })")
                } else {
                    presentMessage(to: phone, body: action.copy ?? "")
                }
            } catch {
                notice = error.localizedDescription
            }
        }
    }

    private func requestCamera() {
        guard UIImagePickerController.isSourceTypeAvailable(.camera) else {
            notice = "A camera is not available on this device."
            return
        }
        switch AVCaptureDevice.authorizationStatus(for: .video) {
        case .authorized:
            cameraPresented = true
        case .notDetermined:
            AVCaptureDevice.requestAccess(for: .video) { [weak self] allowed in
                Task { @MainActor in
                    if allowed { self?.cameraPresented = true }
                    else { self?.notice = "Camera permission was not granted." }
                }
            }
        default:
            notice = "Enable camera access for JARVIS in iPhone Settings."
        }
    }

    private func requestNotifications() {
        Task {
            do {
                let granted = try await UNUserNotificationCenter.current()
                    .requestAuthorization(options: [.alert, .sound, .badge])
                notice = granted
                    ? "JARVIS notifications are enabled."
                    : "Notification permission was not granted."
            } catch {
                notice = error.localizedDescription
            }
        }
    }
}

enum ContactResolver {
    static func phoneNumber(matching name: String) async throws -> String {
        let store = CNContactStore()
        let allowed = try await withCheckedThrowingContinuation {
            (continuation: CheckedContinuation<Bool, Error>) in
            store.requestAccess(for: .contacts) { allowed, error in
                if let error { continuation.resume(throwing: error) }
                else { continuation.resume(returning: allowed) }
            }
        }
        guard allowed else { throw ContactLookupError.permissionDenied }
        let keys = [CNContactGivenNameKey, CNContactFamilyNameKey, CNContactPhoneNumbersKey]
            as [CNKeyDescriptor]
        let request = CNContactFetchRequest(keysToFetch: keys)
        request.predicate = CNContact.predicateForContacts(matchingName: name)
        var candidates: [CNContact] = []
        try store.enumerateContacts(with: request) { contact, _ in candidates.append(contact) }
        let wanted = name.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        let match = candidates.first {
            "\($0.givenName) \($0.familyName)".trimmingCharacters(in: .whitespaces)
                .lowercased() == wanted
        } ?? candidates.first
        guard let phone = match?.phoneNumbers.first?.value.stringValue else {
            throw ContactLookupError.notFound(name)
        }
        return phone
    }
}

enum ContactLookupError: LocalizedError {
    case permissionDenied
    case notFound(String)

    var errorDescription: String? {
        switch self {
        case .permissionDenied: return "Contact access was not granted."
        case .notFound(let name): return "I could not find a phone number for \(name)."
        }
    }
}

struct MessageComposer: UIViewControllerRepresentable {
    @Binding var draft: MessageDraft?

    func makeCoordinator() -> Coordinator { Coordinator(draft: $draft) }

    func makeUIViewController(context: Context) -> MFMessageComposeViewController {
        let controller = MFMessageComposeViewController()
        controller.messageComposeDelegate = context.coordinator
        controller.recipients = draft?.recipients
        controller.body = draft?.body
        return controller
    }

    func updateUIViewController(_ controller: MFMessageComposeViewController, context: Context) {}

    final class Coordinator: NSObject, MFMessageComposeViewControllerDelegate {
        @Binding var draft: MessageDraft?
        init(draft: Binding<MessageDraft?>) { _draft = draft }
        func messageComposeViewController(
            _ controller: MFMessageComposeViewController,
            didFinishWith result: MessageComposeResult
        ) {
            controller.dismiss(animated: true)
            draft = nil
        }
    }
}

struct CameraCaptureView: UIViewControllerRepresentable {
    @Binding var isPresented: Bool

    func makeCoordinator() -> Coordinator { Coordinator(isPresented: $isPresented) }

    func makeUIViewController(context: Context) -> UIImagePickerController {
        let controller = UIImagePickerController()
        controller.sourceType = .camera
        controller.delegate = context.coordinator
        return controller
    }

    func updateUIViewController(_ controller: UIImagePickerController, context: Context) {}

    final class Coordinator: NSObject, UIImagePickerControllerDelegate, UINavigationControllerDelegate {
        @Binding var isPresented: Bool
        init(isPresented: Binding<Bool>) { _isPresented = isPresented }
        func imagePickerControllerDidCancel(_ picker: UIImagePickerController) { isPresented = false }
        func imagePickerController(
            _ picker: UIImagePickerController,
            didFinishPickingMediaWithInfo info: [UIImagePickerController.InfoKey: Any]
        ) { isPresented = false }
    }
}
