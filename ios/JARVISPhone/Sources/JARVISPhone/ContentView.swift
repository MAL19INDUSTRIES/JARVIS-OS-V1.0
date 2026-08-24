import SwiftUI

struct ContentView: View {
    @EnvironmentObject private var store: PhoneLinkStore
    @Environment(\.scenePhase) private var scenePhase
    @StateObject private var actions = NativeActionController()
    @FocusState private var composerFocused: Bool

    var body: some View {
        ZStack {
            Color(red: 0.008, green: 0.031, blue: 0.051).ignoresSafeArea()
            VStack(spacing: 0) {
                header
                transcript
                composer
            }
        }
        .preferredColorScheme(.dark)
        .onAppear { store.start() }
        .onChange(of: scenePhase) { _, phase in
            if phase == .active { store.start() } else { store.stop() }
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
                primaryButton: .default(Text("Continue")) { actions.perform(action) },
                secondaryButton: .cancel()
            )
        }
        .overlay(alignment: .top) {
            if let notice = actions.notice {
                Text(notice)
                    .font(.footnote)
                    .foregroundStyle(Color(red: 0.84, green: 0.96, blue: 1))
                    .padding(.horizontal, 16)
                    .padding(.vertical, 12)
                    .background(.ultraThinMaterial, in: Capsule())
                    .padding(.top, 68)
                    .onTapGesture { actions.notice = nil }
                    .transition(.move(edge: .top).combined(with: .opacity))
            }
        }
        .animation(.easeOut(duration: 0.2), value: actions.notice)
    }

    private var header: some View {
        HStack(spacing: 11) {
            Circle()
                .stroke(store.connected ? Color.cyan : Color.gray, lineWidth: 1)
                .frame(width: 9, height: 9)
                .shadow(color: store.connected ? .cyan : .clear, radius: 7)
            VStack(alignment: .leading, spacing: 2) {
                Text(store.persona)
                    .font(.system(size: 14, weight: .semibold, design: .rounded))
                    .tracking(2.2)
                Text(store.status)
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .lineLimit(1)
            }
            Spacer()
            Menu {
                Button("Forget this Mac", role: .destructive) { store.forgetConnection() }
            } label: {
                Image(systemName: "ellipsis.circle")
                    .font(.title3)
                    .foregroundStyle(Color.cyan.opacity(0.8))
            }
        }
        .padding(.horizontal, 18)
        .padding(.vertical, 14)
        .overlay(alignment: .bottom) { Divider().opacity(0.25) }
    }

    private var transcript: some View {
        ScrollViewReader { proxy in
            ScrollView {
                LazyVStack(spacing: 18) {
                    if store.messages.isEmpty {
                        VStack(spacing: 15) {
                            Image(systemName: "circle.hexagongrid.circle")
                                .font(.system(size: 52, weight: .ultraLight))
                                .foregroundStyle(Color.cyan.opacity(0.8))
                            Text(store.connected ? "Your JARVIS, within reach." : "Pair JARVIS from your Mac")
                                .font(.title3.weight(.medium))
                            Text(store.connected
                                 ? "Ask for a call, message, supported app, camera, or JARVIS notifications."
                                 : "Open Phone Link on the Mac, scan its QR code, then tap Open JARVIS App.")
                                .font(.subheadline)
                                .foregroundStyle(.secondary)
                                .multilineTextAlignment(.center)
                                .lineSpacing(3)
                        }
                        .frame(maxWidth: 330)
                        .padding(.top, 90)
                    }
                    ForEach(store.messages) { message in
                        MessageRow(message: message, persona: store.persona)
                            .id(message.id)
                    }
                }
                .padding(.horizontal, 18)
                .padding(.vertical, 22)
            }
            .scrollDismissesKeyboard(.interactively)
            .onChange(of: store.messages.count) { _, _ in
                if let last = store.messages.last?.id {
                    withAnimation(.easeOut(duration: 0.22)) { proxy.scrollTo(last, anchor: .bottom) }
                }
            }
        }
    }

    private var composer: some View {
        HStack(alignment: .bottom, spacing: 8) {
            TextField("Message JARVIS", text: $store.draft, axis: .vertical)
                .lineLimit(1...5)
                .focused($composerFocused)
                .submitLabel(.send)
                .onSubmit { store.send() }
                .padding(.horizontal, 12)
                .padding(.vertical, 11)
            Button(action: store.send) {
                Image(systemName: "arrow.up")
                    .font(.system(size: 17, weight: .bold))
                    .frame(width: 42, height: 42)
                    .background(Color.cyan, in: RoundedRectangle(cornerRadius: 11))
                    .foregroundStyle(Color(red: 0, green: 0.06, blue: 0.08))
            }
            .disabled(!store.connected || store.draft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
            .opacity(store.connected ? 1 : 0.35)
        }
        .padding(7)
        .background(Color(red: 0.025, green: 0.07, blue: 0.1), in: RoundedRectangle(cornerRadius: 15))
        .overlay { RoundedRectangle(cornerRadius: 15).stroke(Color.cyan.opacity(0.22)) }
        .padding(.horizontal, 14)
        .padding(.vertical, 10)
    }
}

private struct MessageRow: View {
    let message: PhoneMessage
    let persona: String

    var isUser: Bool { message.role == "user" }

    var body: some View {
        VStack(alignment: isUser ? .trailing : .leading, spacing: 6) {
            Text(isUser ? "YOU" : persona)
                .font(.system(size: 10, weight: .medium, design: .rounded))
                .tracking(1.4)
                .foregroundStyle(isUser ? Color.secondary : Color.cyan.opacity(0.75))
            Text(message.content)
                .font(.system(size: 15))
                .lineSpacing(3)
                .padding(.horizontal, 14)
                .padding(.vertical, 12)
                .background(
                    isUser ? Color.cyan.opacity(0.12) : Color.white.opacity(0.035),
                    in: RoundedRectangle(cornerRadius: 14)
                )
                .overlay {
                    RoundedRectangle(cornerRadius: 14)
                        .stroke(Color.cyan.opacity(isUser ? 0.25 : 0.1))
                }
        }
        .frame(maxWidth: .infinity, alignment: isUser ? .trailing : .leading)
    }
}
