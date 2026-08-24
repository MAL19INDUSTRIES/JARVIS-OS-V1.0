# JARVIS iPhone companion

This is the native half of Phone Link. It intentionally stays to one screen: the JARVIS chat log and composer. The QR landing page opens the app with a one-time local pairing token; the resulting device credential is stored in the iOS Keychain.

## Run it on an iPhone

1. Install the full Xcode app and XcodeGen on the Mac (`brew install xcodegen`).
2. In this directory, run `xcodegen generate` and open `JARVISPhone.xcodeproj`.
3. Select the `JARVISPhone` target, choose your Apple Developer team under Signing & Capabilities, connect the iPhone, and press Run.
4. The native companion is currently a development preview, not an App Store or TestFlight release. The normal Phone Link QR intentionally opens the working Safari client directly until a signed companion build is distributed.

The Mac and iPhone must share local Wi-Fi and desktop JARVIS must be running. Calls, message drafts, contact lookup, camera access, and JARVIS notification permission are confirmed on the phone. The app cannot silently send messages, read other apps' notifications, automate arbitrary iOS screens, or maintain a general control channel while iOS has suspended it.
