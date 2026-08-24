# JARVIS iPhone companion

The companion is a focused native app with one chat log, voice input, visible
assistant state, and confirmed phone actions. It connects to the hosted JARVIS
API, so the desktop app and Mac can be offline.

## Included in the current beta foundation

- Cloud account creation and sign-in with the session stored in Keychain.
- User-scoped cloud conversation history and encrypted AI credentials.
- Typed chat and speech-to-text requests.
- A moving screen-edge signal for listening, thinking, and approval states.
- An App Intent named `Start JARVIS` for Siri, the Action button, and Apple's
  Vocal Shortcuts feature.
- Confirmed calls, message drafts, contact lookup, camera, app links, and
  notification permission.
- In-app account deletion for App Store compliance.
- A 1024 px App Store icon without an alpha channel.

The app cannot draw its edge animation above other apps. iOS reserves that kind
of system-wide overlay for Apple. A future ActivityKit extension can carry the
same state into the Dynamic Island and Lock Screen.

## Run locally

1. Install the full Xcode app and XcodeGen (`brew install xcodegen`).
2. Start the API from the repository root:

   ```bash
   .venv/bin/uvicorn api.server:app --reload
   ```

3. From this directory, run `xcodegen generate` and open
   `JARVISPhone.xcodeproj`.
4. Choose an Apple development team under Signing & Capabilities.
5. Run on the iOS Simulator. The Debug API URL defaults to
   `http://localhost:8000`.

For a physical phone or release archive, point the `JARVIS_API_BASE_URL` build
setting at the deployed HTTPS API. Do not ship a localhost URL.

## Let people say only "JARVIS"

After installing the beta, each tester completes this once:

1. Open Settings > Accessibility > Vocal Shortcuts.
2. Create a Vocal Shortcut and choose the `Start JARVIS` app action.
3. Record `JARVIS` as the phrase.

The app opens, starts listening, shows the animated edge, sends the transcribed
request to the cloud, and displays any protected action for confirmation.

## Distribution

See [DISTRIBUTION.md](DISTRIBUTION.md) for the hosted API, TestFlight, and App
Store release checklist.

## iOS security boundaries

Calls, message drafts, contacts, camera access, and notifications remain under
iOS permission and confirmation controls. The app cannot silently send an SMS
or iMessage, read other apps' notifications, automate arbitrary iOS screens, or
remain an unrestricted background process.
