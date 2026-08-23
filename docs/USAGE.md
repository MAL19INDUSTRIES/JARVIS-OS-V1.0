# JARVIS — Usage Guide

This guide is focused on **daily usage** once you’ve installed and started the app.

## Start Jarvis

```bash
jarvis
```

If `GEMINI_API_KEY` is set correctly, Jarvis will:
- open the UI
- start microphone audio
- connect to Gemini Live
- listen and respond by voice

## What you can say (practical examples)

### 1) Basic actions
- “Open Chrome”
- “What’s the weather in Paris?”
- “Search the web for …”

### 2) Screen / camera questions
- “What is on my screen?”
- “Look at my camera and tell me what you see”
- “Analyze this screenshot”

### 3) Reminders
- “Set a reminder for tomorrow at 8:30 AM to call Mom”

### 4) Files
When you have a file available via the UI/upload flow, you can ask for:
- “Summarize this PDF”
- “Extract text from this image”
- “Fix and optimize this code”
- “Analyze this CSV”

### 5) Desktop controls
Examples (depending on what your toolset supports):
- “Organize my desktop by type”
- “Clean my downloads folder”
- “Take a screenshot”

### 6) Gmail

Gmail uses Google OAuth rather than an API key or Gmail password. One-time setup:

1. Create or select a project in Google Cloud.
2. Enable the Gmail API.
3. Configure Google Auth Platform Branding, Audience, and Data Access. If the app
   is External and still in testing, add your Gmail account as a test user.
4. Add the scopes `gmail.readonly` and `gmail.send`.
5. Create an OAuth Client ID with application type **Desktop app** and download
   its JSON file.
6. Drag that JSON into JARVIS and say: “Connect Gmail using this file.”
7. Complete Google's consent page in the browser that opens.

JARVIS stores the refresh credential in the operating-system keychain, not in
`token.json` or the project configuration. Example commands:

- “Is Gmail connected?”
- “Show my unread Gmail messages.”
- “Search Gmail for `from:alex@example.com newer_than:7d`.”
- “Read Gmail message ID 18f...”
- “Prepare an email to alex@example.com with subject Project Update saying the deck is ready.”
- “Approve that email.”
- “Cancel that email.”
- “Disconnect Gmail.”

Preparing a Gmail email never sends it. JARVIS opens a visible Gmail compose window,
types the recipient, optional Cc/Bcc, subject, and body in sequence, then leaves the
draft open for review. A separate explicit approval verifies that the visible draft
still matches and clicks Gmail's Send button. On first use, sign in to Gmail inside
the JARVIS-controlled Chrome profile when prompted, then ask JARVIS to prepare the
email again. If the Gmail API connection already identifies the account, JARVIS
prefills that address and waits while you complete Google's password or 2FA screen;
JARVIS never reads or stores those credentials. The browser session remains signed
in for later drafts.

### 7) Deep Research
JARVIS can investigate a complex question across multiple searches, compare evidence,
surface disagreements and uncertainty, and save a cited report.
Examples:

- “Do deep research on whether heat pumps make financial sense for my home.”
- “Thoroughly research the leading local AI frameworks, focusing on privacy and Mac performance.”
- “Do quick deep research on this company before my interview.”
- “What is the status of my research?”
- “Cancel research task 4f2a8c10.”

Before research begins, JARVIS asks whether you want it to run quietly in the
background or let you watch the research. Background mode shows a compact bar
labeled `RUNNING IN THE BACKGROUND` and keeps browser windows closed. Visible
mode opens JARVIS's controlled browser, performs each search, and visits sources
in separate tabs so you can follow the investigation. No research starts while
JARVIS is waiting for that choice.

Research depth can be `quick`, `standard` (default), or `deep`. Reports are saved as
Markdown only when you explicitly ask JARVIS to save them. Until then, the report,
search plan, evidence, and sources remain in volatile memory and are not written to
task history or `outputs/research`. When research finishes, JARVIS gives a detailed
summary and offers to save the report to Files, save it to Desktop, or read the
entire report aloud. Deep Research requires a valid Gemini API key. Source gathering uses direct web search so one research
run does not exhaust the Gemini request quota. Gemini is used for final synthesis
when quota is available; otherwise JARVIS keeps a source-first fallback report in memory.

### 8) PowerPoint presentations
JARVIS can create, edit, redesign, and extend editable widescreen `.pptx` decks.
Presentation jobs run in the background, report progress through `task_status`,
and export a PDF when Microsoft PowerPoint is available. Examples:

- “Create an eight-slide PowerPoint about renewable energy for high-school students.”
- “Make a quality-mode executive presentation using these PDFs and spreadsheets.”
- “Redesign the uploaded deck, preserve its branding, and add speaker notes.”
- “Extend this investor deck to 20 slides and export both PowerPoint and PDF.”
- “Create a premium presentation from this product-demo video.”
- “What is the status of my presentation?”
- “Cancel presentation task 4f2a8c10.”

Available themes are `arc_reactor`, `executive`, and `platinum`. By default,
presentations are saved in `Desktop/JARVIS Presentations`. Quality modes are
`fast`, `quality` (default), and `premium`, with a maximum of 50 slides.

Sources may include PDF, Word, PowerPoint, Excel, CSV, JSON, Markdown, text,
images, audio, video, or specific URLs. JARVIS uses supplied sources first and
will only perform broader web research after you explicitly allow it. Supplied
decks are never overwritten during edit, redesign, or extension jobs.

### 9) Local website builder

Ask any active persona to create a website, then choose one of the three design
directions shown in the center workspace. JARVIS displays every requested npm
package before installation and builds only after you select `APPROVE & BUILD`.
The default stack is React, Vite, and Tailwind. Examples:

- “Build a portfolio website for an independent industrial designer.”
- “Create a product landing page using these pasted component prompts.”
- “Revise the current website so the pricing section is clearer.”
- “Reopen my Signal Studio website.”

You can paste 21st.dev component prompts, source links, or local prompt files.
They are treated as untrusted visual references, never as commands, and the
builder does not scrape 21st.dev. Source URLs, authors, licenses, prompt hashes,
approved packages, and the creating persona are recorded in the project's
`.jarvis/provenance.json`. Generated projects are saved permanently under
`Documents/JARVIS Websites/<project-name>` and previewed from a local Vite server.
The server stops when JARVIS exits or when you ask it to stop the preview.

As soon as website creation begins, JARVIS clears the ordinary dashboard and
uses the complete window as the website workspace. Only the website content and
a small version of the active persona orb remain. Click the orb to open the
conversation log above it; type into the single field and press Enter to send.
Press Escape to collapse the chat, or type “return to dashboard” to leave the
website workspace. The builder keeps generated interfaces two-dimensional and
rejects native 3D models, WebGL frameworks, and GLB/GLTF assets during generation,
repair, revision, package approval, and build validation.

## Troubleshooting during usage

### API key issues
If you see:
- `GEMINI_API_KEY environment variable not set`

Fix:
- ensure `.env` exists in the repo root
- set `GEMINI_API_KEY`
- restart Jarvis

### Voice not available
If Jarvis can’t use your selected voice, it will fall back to the default voice (`puck`).

Fix:
- set `GEMINI_VOICE_NAME` to a supported voice name from `main.py`

### If tools fail
Jarvis usually logs errors to the UI log.

Fix:
- check environment permissions (mic, display, etc.)
- ensure any optional dependencies (like Playwright) are installed
- if needed, open an issue with the traceback
