# JARVIS Apple Shortcut

This is the replacement iPhone connection. It uses Apple's Shortcuts app as the native action layer and talks directly to desktop JARVIS over local Wi-Fi. It does not depend on a QR code, Safari storage, an App Store build, or a permanent browser tab.

## Before you begin

- Keep the iPhone and Mac on the same trusted Wi-Fi.
- Start desktop JARVIS.
- In JARVIS, open **Phone Link**, confirm access, and choose **Set Up Apple Shortcut**.
- Select **Copy Config**, then **Open Shortcuts**.
- Treat the copied bearer token like a password. Anyone with it on your local network can submit commands until you revoke the shortcut in JARVIS.

## Build the shortcut

Create a shortcut named **JARVIS** with these actions in order:

1. **Ask for Input**
   - Input Type: `Text`
   - Prompt: `What should JARVIS do?`
2. **URL**
   - Paste the `url` value from the copied configuration.
3. **Get Contents of URL**
   - Method: `POST`
   - Header: `Authorization`
   - Header value: the complete `Bearer ...` value from the configuration.
   - Request Body: `JSON`
   - Add a text field named `command` whose value is the **Provided Input** variable from step 1.
4. **Get Dictionary Value**
   - Key: `action`
   - Dictionary: **Contents of URL**
5. **Get Dictionary Value**
   - Key: `kind`
   - Dictionary: **Dictionary Value** from step 4.

Use **If** actions to handle the returned `kind`:

- `call`, `message`, or `open`: get `url` from the action dictionary, then use **Open URLs**.
- `camera`: use **Take Photo**. Add **Save to Photo Album** only if you want captures saved.
- `notifications`: get `message`, then use **Show Notification**.
- `call-contact`: get `contact`, use **Find Contacts** where Name matches it, then use **Call**.
- `message-contact`: get `contact` and `copy`, find the contact, then use **Send Message** with `copy` as the message.
- `complete`: get `message`, then use **Show Result**.

Run the shortcut once in the editor and approve the local-network, Contacts, Camera, and messaging permissions you choose to use. Add it to the iPhone Home Screen, a Shortcuts widget, the Action button, or invoke it by saying “Siri, JARVIS.” iOS may require the phone to be unlocked for an action that opens an app or accesses private data.

## Supported commands

- `Call 4155550123`
- `Call Alex`
- `Text 4155550123 saying I am on my way`
- `Text Alex saying I am on my way`
- `Open Instagram`, `Open Maps`, `Open Music`, or `Open YouTube`
- `Open the camera`
- `Enable JARVIS notifications`

Other commands are forwarded to desktop JARVIS and return a completion notice. Phone actions remain subject to iOS permissions and confirmation behavior.
