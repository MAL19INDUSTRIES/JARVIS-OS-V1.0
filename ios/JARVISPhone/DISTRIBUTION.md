# Distributing JARVIS for iPhone

## What testers receive

The first release goes through TestFlight. A tester opens one link, installs
Apple's TestFlight app if needed, then installs JARVIS. There is no QR code and
their Mac does not need to be running.

Each person creates a separate cloud account. The API scopes chat history,
memory, configuration, quotas, and encrypted credentials by user ID.

## 1. Prepare the hosted service

Deploy the repository's `render.yaml` blueprint or `fly.toml` app and configure:

- A production Postgres database.
- Redis for rate limits.
- Unique `JWT_SECRET` and `JARVIS_ENCRYPTION_KEY` secrets.
- `JARVIS_ENV=production`, `AUTO_CREATE_TABLES=0`, and `REDIS_REQUIRED=1`.
- `JARVIS_SERVICE_GEMINI_KEY` if normal users should not bring their own key.
- HTTPS on the public API address.

Run the Alembic migration before serving traffic. Verify `/health`, account
creation, account deletion, and an authenticated `/chat` request.

The private beta can use per-user Gemini keys. A public release should normally
use the server key plus quotas or subscriptions so users never handle an API
key and one account cannot create unlimited cost.

## 2. Prepare the Apple account

Enroll in the Apple Developer Program. An individual membership lists the
person's legal name as the seller. An organization membership lists the legal
entity and requires Apple's organization verification, including a D-U-N-S
Number.

Create an App Store Connect record with:

- App name: `JARVIS` or the approved public product name.
- Bundle ID: `com.mal19industries.jarvisphone`.
- Primary language and category.
- A privacy policy URL and support URL.

## 3. Build the beta

1. Set `JARVIS_API_BASE_URL` in `project.yml` to the production HTTPS API.
2. Run `xcodegen generate`.
3. Open `JARVISPhone.xcodeproj` in the full Xcode app.
4. Choose the developer team and confirm automatic signing.
5. Test microphone, speech recognition, contacts, camera, notifications,
   message confirmation, account deletion, reduced motion, and an expired
   session on a physical iPhone.
6. Select Any iOS Device, then Product > Archive.
7. In Organizer, choose Distribute App > App Store Connect > Upload.

## 4. Invite testers

In App Store Connect, open the TestFlight tab, create an external testing group,
add the uploaded build, provide beta review notes and a working review account,
then submit the first external build for beta review. After approval, invite
people by email or share a public TestFlight link.

## 5. Prepare the public App Store release

Before App Review, provide:

- Accurate screenshots showing sign-in, chat, active edge, and action approval.
- Privacy nutrition labels matching the API's real data handling.
- A public privacy policy and support contact.
- A working demo account for App Review.
- Clear microphone, speech, contact, camera, and notification explanations.
- Server-side abuse limits and a support process.
- Subscription or quota behavior if the service pays for AI usage.
- App Review notes explaining that protected phone actions require confirmation.

The backend must stay online throughout TestFlight and App Review. Uploading the
app alone does not host JARVIS.
