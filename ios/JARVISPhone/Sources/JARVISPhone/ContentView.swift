import SwiftUI
import UIKit
import Combine

struct ContentView: View {
    @EnvironmentObject private var store: JARVISStore
    @Environment(\.scenePhase) private var scenePhase
    @StateObject private var actions = NativeActionController()
    @StateObject private var voice = VoiceInputController()

    var body: some View {
        ZStack {
            Color.jarvisWorkspace.ignoresSafeArea()
            Group {
                if !store.isSignedIn {
                    AuthenticationView()
                } else if !store.isAIConfigured {
                    AIConfigurationView()
                } else {
                    ConversationView(voice: voice, beginVoice: beginVoice)
                }
            }
            JARVISEdge(phase: store.phase)
                .allowsHitTesting(false)
        }
        .preferredColorScheme(.dark)
        .onAppear {
            store.start()
            store.consumeIntentActivation()
        }
        .onChange(of: scenePhase) { _, phase in
            guard phase == .active else {
                voice.cancel()
                return
            }
            store.consumeIntentActivation()
        }
        .onChange(of: store.activationRequest) { _, _ in beginVoice() }
        .onReceive(NotificationCenter.default.publisher(for: .jarvisVoiceActivationRequested)) { _ in
            store.consumeIntentActivation()
        }
        .sheet(item: $actions.messageDraft) { _ in
            MessageComposer(draft: $actions.messageDraft).ignoresSafeArea()
        }
        .sheet(isPresented: $actions.cameraPresented) {
            CameraCaptureView(isPresented: $actions.cameraPresented).ignoresSafeArea()
        }
        .alert(item: $store.pendingAction) { action in
            Alert(
                title: Text(action.label),
                message: Text(action.message),
                primaryButton: .default(Text("Continue")) {
                    actions.perform(action)
                    store.actionCompleted()
                },
                secondaryButton: .cancel { store.actionCompleted() }
            )
        }
        .overlay(alignment: .top) {
            if let notice = actions.notice {
                Text(notice)
                    .font(.footnote.weight(.medium))
                    .foregroundStyle(Color.jarvisText)
                    .padding(.horizontal, 16)
                    .padding(.vertical, 11)
                    .background(Color.jarvisRaised, in: Capsule())
                    .overlay { Capsule().stroke(Color.jarvisCyan.opacity(0.35)) }
                    .padding(.top, 62)
                    .onTapGesture { actions.notice = nil }
                    .transition(.move(edge: .top).combined(with: .opacity))
            }
        }
        .animation(.easeOut(duration: 0.2), value: actions.notice)
    }

    private func beginVoice() {
        guard store.isSignedIn, store.isAIConfigured else { return }
        if voice.isListening {
            voice.stopAndSubmit()
            return
        }
        UIImpactFeedbackGenerator(style: .medium).impactOccurred()
        store.beginListening()
        voice.start(
            onResult: { store.submitVoiceCommand($0) },
            onFailure: { store.listeningFailed($0) }
        )
    }
}

private struct AuthenticationView: View {
    @EnvironmentObject private var store: JARVISStore
    @State private var creatingAccount = false
    @State private var displayName = ""
    @State private var email = ""
    @State private var password = ""

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 0) {
                Image(systemName: "circle.hexagongrid.circle.fill")
                    .font(.system(size: 46, weight: .ultraLight))
                    .foregroundStyle(Color.jarvisCyan)
                    .shadow(color: Color.jarvisCyan.opacity(0.45), radius: 18)
                    .padding(.bottom, 28)

                Text(creatingAccount ? "Create your JARVIS" : "Welcome back")
                    .font(.system(size: 32, weight: .semibold, design: .rounded))
                    .foregroundStyle(Color.jarvisText)
                Text(creatingAccount
                     ? "One account keeps your conversations and preferences separate on every device."
                     : "Your assistant is available even when your Mac is off.")
                    .font(.body)
                    .foregroundStyle(Color.jarvisSecondary)
                    .lineSpacing(4)
                    .padding(.top, 9)
                    .padding(.bottom, 34)

                if creatingAccount {
                    AuthField(title: "NAME", placeholder: "Your name", text: $displayName)
                        .textContentType(.name)
                }
                AuthField(title: "EMAIL", placeholder: "you@example.com", text: $email)
                    .textContentType(.emailAddress)
                    .keyboardType(.emailAddress)
                    .textInputAutocapitalization(.never)
                AuthField(
                    title: "PASSWORD",
                    placeholder: creatingAccount ? "At least 10 characters" : "Your password",
                    text: $password,
                    secure: true
                )
                .textContentType(creatingAccount ? .newPassword : .password)

                if let error = store.authError {
                    Label(error, systemImage: "exclamationmark.circle.fill")
                        .font(.footnote)
                        .foregroundStyle(Color.jarvisError)
                        .padding(.top, 6)
                }

                Button(action: authenticate) {
                    HStack {
                        if store.authBusy { ProgressView().tint(Color.jarvisInk) }
                        Text(creatingAccount ? "CREATE ACCOUNT" : "SIGN IN")
                            .font(.system(size: 13, weight: .bold, design: .rounded))
                            .tracking(1.1)
                    }
                    .frame(maxWidth: .infinity)
                    .frame(height: 50)
                    .foregroundStyle(Color.jarvisInk)
                    .background(Color.jarvisCyan, in: RoundedRectangle(cornerRadius: 13))
                }
                .disabled(!formValid || store.authBusy)
                .opacity(formValid ? 1 : 0.42)
                .padding(.top, 20)

                Button(creatingAccount ? "Already have an account? Sign in" : "New to JARVIS? Create an account") {
                    creatingAccount.toggle()
                }
                .font(.subheadline.weight(.medium))
                .foregroundStyle(Color.jarvisCyan)
                .frame(maxWidth: .infinity)
                .padding(.top, 20)
            }
            .frame(maxWidth: 440)
            .padding(.horizontal, 28)
            .padding(.top, 72)
            .padding(.bottom, 40)
            .frame(maxWidth: .infinity)
        }
        .scrollDismissesKeyboard(.interactively)
    }

    private var formValid: Bool {
        email.contains("@") && password.count >= 10 && (!creatingAccount || !displayName.isEmpty)
    }

    private func authenticate() {
        Task {
            if creatingAccount {
                await store.signUp(displayName: displayName, email: email, password: password)
            } else {
                await store.signIn(email: email, password: password)
            }
        }
    }
}

private struct AuthField: View {
    let title: String
    let placeholder: String
    @Binding var text: String
    var secure = false

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(title)
                .font(.system(size: 10, weight: .semibold, design: .rounded))
                .tracking(1.5)
                .foregroundStyle(Color.jarvisSecondary)
            Group {
                if secure {
                    SecureField(placeholder, text: $text)
                } else {
                    TextField(placeholder, text: $text)
                }
            }
            .font(.body)
            .foregroundStyle(Color.jarvisText)
            .padding(.horizontal, 14)
            .frame(height: 50)
            .background(Color.jarvisSurface, in: RoundedRectangle(cornerRadius: 12))
            .overlay {
                RoundedRectangle(cornerRadius: 12)
                    .stroke(Color.jarvisBorder)
            }
        }
        .padding(.bottom, 18)
    }
}

private struct AIConfigurationView: View {
    @EnvironmentObject private var store: JARVISStore
    @State private var apiKey = ""

    var body: some View {
        VStack(alignment: .leading, spacing: 18) {
            Spacer()
            Image(systemName: "key.horizontal.fill")
                .font(.system(size: 34, weight: .light))
                .foregroundStyle(Color.jarvisCyan)
            Text("Connect the intelligence")
                .font(.system(size: 29, weight: .semibold, design: .rounded))
                .foregroundStyle(Color.jarvisText)
            Text("Private beta accounts use their own Gemini API key. It is encrypted before storage and never saved on this iPhone.")
                .font(.body)
                .foregroundStyle(Color.jarvisSecondary)
                .lineSpacing(4)
            SecureField("Gemini API key", text: $apiKey)
                .textInputAutocapitalization(.never)
                .autocorrectionDisabled()
                .padding(.horizontal, 14)
                .frame(height: 50)
                .background(Color.jarvisSurface, in: RoundedRectangle(cornerRadius: 12))
                .overlay { RoundedRectangle(cornerRadius: 12).stroke(Color.jarvisBorder) }
            if let error = store.authError {
                Text(error).font(.footnote).foregroundStyle(Color.jarvisError)
            }
            Button("CONNECT") { Task { await store.configureAI(apiKey: apiKey) } }
                .font(.system(size: 13, weight: .bold, design: .rounded))
                .tracking(1.2)
                .frame(maxWidth: .infinity)
                .frame(height: 50)
                .foregroundStyle(Color.jarvisInk)
                .background(Color.jarvisCyan, in: RoundedRectangle(cornerRadius: 13))
                .disabled(apiKey.count < 20 || store.authBusy)
                .opacity(apiKey.count >= 20 ? 1 : 0.42)
            Button("Sign out") { store.signOut() }
                .foregroundStyle(Color.jarvisSecondary)
                .frame(maxWidth: .infinity)
            Spacer()
        }
        .frame(maxWidth: 440)
        .padding(.horizontal, 28)
        .frame(maxWidth: .infinity)
    }
}

private struct ConversationView: View {
    @EnvironmentObject private var store: JARVISStore
    @ObservedObject var voice: VoiceInputController
    let beginVoice: () -> Void
    @FocusState private var composerFocused: Bool
    @State private var confirmAccountDeletion = false

    var body: some View {
        VStack(spacing: 0) {
            header
            transcript
            if voice.isListening { liveTranscript }
            composer
        }
        .confirmationDialog(
            "Delete your JARVIS account?",
            isPresented: $confirmAccountDeletion,
            titleVisibility: .visible
        ) {
            Button("Delete account and data", role: .destructive) {
                Task { await store.deleteAccount() }
            }
            Button("Cancel", role: .cancel) {}
        } message: {
            Text("This permanently removes your cloud conversation history, memory, and saved credentials.")
        }
    }

    private var header: some View {
        HStack(spacing: 11) {
            Circle()
                .fill(phaseColor)
                .frame(width: 8, height: 8)
                .shadow(color: phaseColor.opacity(store.phase.isActive ? 0.9 : 0.3), radius: 7)
            VStack(alignment: .leading, spacing: 2) {
                Text("JARVIS")
                    .font(.system(size: 14, weight: .semibold, design: .rounded))
                    .tracking(2.2)
                    .foregroundStyle(Color.jarvisText)
                Text(store.phase.label)
                    .font(.system(size: 10, weight: .medium, design: .monospaced))
                    .tracking(1.1)
                    .foregroundStyle(phaseColor)
            }
            Spacer()
            Text(store.status)
                .font(.caption)
                .foregroundStyle(Color.jarvisSecondary)
                .lineLimit(1)
            Menu {
                Text(store.profile?.email ?? "")
                Button("Sign out", role: .destructive) { store.signOut() }
                Button("Delete account", role: .destructive) {
                    confirmAccountDeletion = true
                }
            } label: {
                Image(systemName: "ellipsis.circle")
                    .font(.title3)
                    .foregroundStyle(Color.jarvisCyan.opacity(0.85))
            }
        }
        .padding(.horizontal, 18)
        .padding(.vertical, 14)
        .overlay(alignment: .bottom) { Divider().overlay(Color.jarvisBorder) }
    }

    private var transcript: some View {
        ScrollViewReader { proxy in
            ScrollView {
                LazyVStack(spacing: 18) {
                    if store.messages.isEmpty {
                        VStack(spacing: 15) {
                            Image(systemName: "waveform.circle")
                                .font(.system(size: 52, weight: .ultraLight))
                                .foregroundStyle(Color.jarvisCyan.opacity(0.82))
                            Text("JARVIS is within reach")
                                .font(.title3.weight(.medium))
                                .foregroundStyle(Color.jarvisText)
                            Text("Tap the microphone and speak, or type a request below. Your Mac does not need to be running.")
                                .font(.subheadline)
                                .foregroundStyle(Color.jarvisSecondary)
                                .multilineTextAlignment(.center)
                                .lineSpacing(3)
                        }
                        .frame(maxWidth: 330)
                        .padding(.top, 82)
                    }
                    ForEach(store.messages) { message in
                        MessageRow(message: message)
                            .id(message.id)
                    }
                }
                .padding(.horizontal, 18)
                .padding(.vertical, 22)
            }
            .scrollDismissesKeyboard(.interactively)
            .onChange(of: store.messages.count) { _, _ in
                if let last = store.messages.last?.id {
                    withAnimation(.easeOut(duration: 0.22)) {
                        proxy.scrollTo(last, anchor: .bottom)
                    }
                }
            }
        }
    }

    private var liveTranscript: some View {
        HStack(spacing: 10) {
            Image(systemName: "waveform")
                .symbolEffect(.variableColor.iterative)
                .foregroundStyle(Color.jarvisCyan)
            Text(voice.transcript.isEmpty ? "Listening…" : voice.transcript)
                .font(.subheadline)
                .foregroundStyle(Color.jarvisText)
                .lineLimit(2)
            Spacer()
        }
        .padding(.horizontal, 18)
        .padding(.vertical, 10)
        .background(Color.jarvisCyan.opacity(0.07))
        .overlay(alignment: .top) { Divider().overlay(Color.jarvisCyan.opacity(0.18)) }
    }

    private var composer: some View {
        HStack(alignment: .bottom, spacing: 8) {
            Button(action: beginVoice) {
                Image(systemName: voice.isListening ? "stop.fill" : "mic.fill")
                    .font(.system(size: 16, weight: .semibold))
                    .frame(width: 42, height: 42)
                    .foregroundStyle(voice.isListening ? Color.jarvisInk : Color.jarvisCyan)
                    .background(
                        voice.isListening ? Color.jarvisCyan : Color.jarvisRaised,
                        in: RoundedRectangle(cornerRadius: 11)
                    )
            }
            .accessibilityLabel(voice.isListening ? "Stop listening" : "Talk to JARVIS")

            TextField("Message JARVIS", text: $store.draft, axis: .vertical)
                .lineLimit(1...5)
                .focused($composerFocused)
                .submitLabel(.send)
                .onSubmit { store.send() }
                .padding(.horizontal, 8)
                .padding(.vertical, 11)
                .foregroundStyle(Color.jarvisText)
            Button(action: store.send) {
                Image(systemName: "arrow.up")
                    .font(.system(size: 17, weight: .bold))
                    .frame(width: 42, height: 42)
                    .background(Color.jarvisCyan, in: RoundedRectangle(cornerRadius: 11))
                    .foregroundStyle(Color.jarvisInk)
            }
            .disabled(store.draft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
            .opacity(store.draft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty ? 0.35 : 1)
        }
        .padding(7)
        .background(Color.jarvisSurface, in: RoundedRectangle(cornerRadius: 15))
        .overlay { RoundedRectangle(cornerRadius: 15).stroke(Color.jarvisCyan.opacity(0.22)) }
        .padding(.horizontal, 14)
        .padding(.vertical, 10)
    }

    private var phaseColor: Color {
        switch store.phase {
        case .offline: return .jarvisError
        case .complete: return .jarvisSuccess
        case .acting: return .jarvisWarning
        default: return .jarvisCyan
        }
    }
}

private struct MessageRow: View {
    let message: PhoneMessage
    private var isUser: Bool { message.role == "user" }
    private var isSystem: Bool { message.role == "system" }

    var body: some View {
        VStack(alignment: isUser ? .trailing : .leading, spacing: 6) {
            Text(isSystem ? "SYSTEM" : (isUser ? "YOU" : "JARVIS"))
                .font(.system(size: 10, weight: .medium, design: .rounded))
                .tracking(1.4)
                .foregroundStyle(isSystem ? Color.jarvisError : (isUser ? Color.jarvisSecondary : Color.jarvisCyan))
            Text(message.content)
                .font(.system(size: 15))
                .foregroundStyle(Color.jarvisText)
                .lineSpacing(3)
                .padding(.horizontal, 14)
                .padding(.vertical, 12)
                .background(
                    isUser ? Color.jarvisCyan.opacity(0.12) : Color.jarvisRaised.opacity(0.72),
                    in: RoundedRectangle(cornerRadius: 14)
                )
                .overlay {
                    RoundedRectangle(cornerRadius: 14)
                        .stroke(isSystem ? Color.jarvisError.opacity(0.35) : Color.jarvisCyan.opacity(isUser ? 0.25 : 0.1))
                }
        }
        .frame(maxWidth: .infinity, alignment: isUser ? .trailing : .leading)
    }
}

private struct JARVISEdge: View {
    let phase: JARVISPhase
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    var body: some View {
        TimelineView(.animation(minimumInterval: 1.0 / 30.0, paused: reduceMotion || !phase.isActive)) { timeline in
            let seconds = timeline.date.timeIntervalSinceReferenceDate
            let angle = reduceMotion ? 0 : seconds * 34
            RoundedRectangle(cornerRadius: 35, style: .continuous)
                .stroke(
                    AngularGradient(
                        colors: edgeColors,
                        center: .center,
                        angle: .degrees(angle)
                    ),
                    style: StrokeStyle(lineWidth: phase.isActive ? 5 : 1.2)
                )
                .opacity(edgeOpacity)
                .shadow(color: Color.jarvisCyan.opacity(phase.isActive ? 0.5 : 0), radius: 9)
                .padding(3)
                .ignoresSafeArea()
        }
        .animation(.easeOut(duration: 0.2), value: phase)
        .accessibilityHidden(true)
    }

    private var edgeOpacity: Double {
        switch phase {
        case .listening, .thinking, .acting: return 1
        case .complete: return 0.58
        case .offline: return 0.22
        default: return 0.1
        }
    }

    private var edgeColors: [Color] {
        if phase == .acting {
            return [.jarvisWarning, .jarvisCyan, .jarvisWarning, .jarvisCyan]
        }
        return [
            .jarvisCyan,
            Color(red: 0.25, green: 0.48, blue: 0.98),
            Color(red: 0.70, green: 0.30, blue: 0.96),
            Color(red: 0.96, green: 0.26, blue: 0.63),
            .jarvisCyan,
        ]
    }
}

private extension Color {
    static let jarvisWorkspace = Color(red: 0.000, green: 0.012, blue: 0.024)
    static let jarvisSurface = Color(red: 0.000, green: 0.031, blue: 0.059)
    static let jarvisRaised = Color(red: 0.000, green: 0.047, blue: 0.094)
    static let jarvisBorder = Color(red: 0.039, green: 0.145, blue: 0.208)
    static let jarvisCyan = Color(red: 0.000, green: 0.784, blue: 1.000)
    static let jarvisText = Color(red: 0.910, green: 0.973, blue: 1.000)
    static let jarvisSecondary = Color(red: 0.318, green: 0.671, blue: 0.753)
    static let jarvisInk = Color(red: 0.000, green: 0.047, blue: 0.070)
    static let jarvisSuccess = Color(red: 0.000, green: 0.900, blue: 0.480)
    static let jarvisWarning = Color(red: 1.000, green: 0.650, blue: 0.000)
    static let jarvisError = Color(red: 1.000, green: 0.180, blue: 0.300)
}
