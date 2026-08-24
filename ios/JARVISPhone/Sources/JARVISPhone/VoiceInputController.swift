import AVFoundation
import Combine
import Speech

@MainActor
final class VoiceInputController: ObservableObject {
    @Published private(set) var isListening = false
    @Published private(set) var transcript = ""

    private let audioEngine = AVAudioEngine()
    private let recognizer = SFSpeechRecognizer(locale: Locale.current)
    private var recognitionRequest: SFSpeechAudioBufferRecognitionRequest?
    private var recognitionTask: SFSpeechRecognitionTask?
    private var silenceTask: Task<Void, Never>?
    private var completion: ((String) -> Void)?
    private var failure: ((String) -> Void)?

    func start(
        onResult: @escaping (String) -> Void,
        onFailure: @escaping (String) -> Void
    ) {
        guard !isListening else { return }
        completion = onResult
        failure = onFailure
        Task {
            guard await requestPermissions() else {
                fail("Enable microphone and speech recognition for JARVIS in Settings.")
                return
            }
            do {
                try beginRecognition()
            } catch {
                fail(error.localizedDescription)
            }
        }
    }

    func stopAndSubmit() {
        finish(commit: true)
    }

    func cancel() {
        finish(commit: false)
    }

    private func requestPermissions() async -> Bool {
        let speechAllowed: Bool = await withCheckedContinuation { continuation in
            SFSpeechRecognizer.requestAuthorization { status in
                continuation.resume(returning: status == .authorized)
            }
        }
        guard speechAllowed else { return false }
        return await withCheckedContinuation { continuation in
            AVAudioSession.sharedInstance().requestRecordPermission { allowed in
                continuation.resume(returning: allowed)
            }
        }
    }

    private func beginRecognition() throws {
        recognitionTask?.cancel()
        recognitionTask = nil
        transcript = ""

        let session = AVAudioSession.sharedInstance()
        try session.setCategory(.record, mode: .measurement, options: [.duckOthers])
        try session.setActive(true, options: .notifyOthersOnDeactivation)

        let request = SFSpeechAudioBufferRecognitionRequest()
        request.shouldReportPartialResults = true
        request.requiresOnDeviceRecognition = recognizer?.supportsOnDeviceRecognition == true
        recognitionRequest = request

        let input = audioEngine.inputNode
        let format = input.outputFormat(forBus: 0)
        guard format.sampleRate > 0 else {
            throw VoiceInputError.microphoneUnavailable
        }
        input.removeTap(onBus: 0)
        input.installTap(onBus: 0, bufferSize: 1024, format: format) { buffer, _ in
            request.append(buffer)
        }

        recognitionTask = recognizer?.recognitionTask(with: request) { [weak self] result, error in
            Task { @MainActor in
                guard let self else { return }
                if let result {
                    self.transcript = result.bestTranscription.formattedString
                    self.scheduleSilenceCommit()
                    if result.isFinal { self.finish(commit: true) }
                } else if let error, self.isListening {
                    self.fail(error.localizedDescription)
                }
            }
        }

        audioEngine.prepare()
        try audioEngine.start()
        isListening = true
    }

    private func scheduleSilenceCommit() {
        silenceTask?.cancel()
        silenceTask = Task { [weak self] in
            try? await Task.sleep(for: .seconds(1.35))
            guard !Task.isCancelled else { return }
            self?.finish(commit: true)
        }
    }

    private func finish(commit: Bool) {
        let finalTranscript = transcript
        silenceTask?.cancel()
        silenceTask = nil
        if audioEngine.isRunning { audioEngine.stop() }
        audioEngine.inputNode.removeTap(onBus: 0)
        recognitionRequest?.endAudio()
        recognitionTask?.cancel()
        recognitionTask = nil
        recognitionRequest = nil
        try? AVAudioSession.sharedInstance().setActive(
            false,
            options: .notifyOthersOnDeactivation
        )
        isListening = false
        transcript = ""
        let callback = completion
        completion = nil
        failure = nil
        if commit { callback?(finalTranscript) }
    }

    private func fail(_ message: String) {
        let callback = failure
        finish(commit: false)
        callback?(message)
    }
}

enum VoiceInputError: LocalizedError {
    case microphoneUnavailable

    var errorDescription: String? {
        "The microphone is not available right now."
    }
}
