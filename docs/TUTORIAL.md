# JARVIS — Download, Install, and First Run

This tutorial takes you from "I just clicked Download" to a working
voice assistant in one sitting. Pick the path that matches your
comfort level:

- **[The 5-Minute Path](#the-5-minute-path-no-terminal-needed)** — download
  the ZIP, double-click a launcher, talk to JARVIS. Works on macOS and
  Windows. (No terminal required.)
- **[The Developer Path](#the-developer-path-git--venv)** — `git clone`,
  `python -m venv`, run from a terminal. For people who already have a
  Python workflow.

If anything goes wrong, jump to **[Troubleshooting](#troubleshooting)**.

---

## Before you start

You need three things no matter which path you take:

1. **A Google Gemini API key.** Get one at
   <https://aistudio.google.com/apikey>. The free tier works; the
   Gemini Live models JARVIS uses do require a key that has Live API
   access — if the free key complains, billing has to be enabled on
   the project that owns the key.
2. **A working microphone** (built-in is fine) and permission for
   JARVIS to use it.
3. **A desktop operating system JARVIS supports:** macOS (Intel or
   Apple Silicon), Windows 10/11, or Linux.

---

## The 5-Minute Path (no terminal needed)

### 1. Download the ZIP

1. Open the JARVIS GitHub repository in your browser.
2. Click the green **`<> Code`** button, then **Download ZIP**.
3. When the ZIP finishes downloading, **double-click it** to unzip.
   macOS does this automatically; on Windows you may need
   "Extract All...".
4. Move the unzipped folder somewhere stable (e.g. `~/Applications/`
   on macOS or `C:\Apps\` on Windows). Don't put it inside iCloud,
   OneDrive, or Downloads — JARVIS keeps a virtual environment in the
   folder, and cloud sync can corrupt it.

You should now have a folder that contains `main.py`, `requirements.txt`,
`README.md`, a `scripts/` folder, and a few others. **Open that folder
and keep it open** — the next step needs it.

### 2. Get a Gemini API key (if you don't have one)

1. Visit <https://aistudio.google.com/apikey>.
2. Click **Create API key** and copy the value.
3. Treat it like a password. Don't paste it into chat, screenshots, or
   GitHub issues.

### 3. Create your `.env` file

The ZIP does not include a `.env` because `.env` holds your secret and
must never be shared.

1. In the JARVIS folder, find the file `.env.example` and **make a copy
   of it in the same folder**.
2. Rename the copy to `.env` (note the leading dot).
   - **macOS Finder:** right-click → Rename. If Finder hides the dot,
     rename from a terminal with `mv .env.example .env`.
   - **Windows Explorer:** show file extensions (View → Show →
     File name extensions), then rename.
3. Open `.env` in any text editor (TextEdit, Notepad, VS Code…).
4. Replace `YOUR_GEMINI_API_KEY` with the key from step 2.
5. Save and close.

Optional but useful: change `GEMINI_VOICE_NAME` to one of
`puck`, `charon`, `kore`, `fenrir`, `aoede`, `leda`, `orus`,
`schedar`, or `zubenelgenubi`. Leave it as `puck` if you don't have a
preference.

### 4. Launch JARVIS

**macOS:**

1. In Finder, open the `scripts/` folder inside the JARVIS folder.
2. Double-click **`start_jarvis.command`**.
3. The first launch will pop a Terminal window, create a virtual
   environment, and install dependencies. This takes 2–5 minutes.
4. Subsequent launches start JARVIS in seconds.
5. macOS will ask for microphone permission the first time JARVIS
   tries to use the mic — click **Allow**.

**Windows:**

1. In File Explorer, open the `scripts/` folder inside the JARVIS folder.
2. Double-click **`start_jarvis.bat`**.
3. The first launch opens a Command Prompt window, creates a virtual
   environment, and installs dependencies. This takes 2–5 minutes.
4. Subsequent launches start JARVIS in seconds.
5. Windows will ask for microphone permission the first time — click
   **Yes**.

If the launcher closes immediately, see [Troubleshooting](#troubleshooting).

### 5. Say hello

When JARVIS is ready you'll see its UI and a small log panel. Say:

> "Hello JARVIS. What can you do?"

It should respond out loud. If it doesn't, see
[Troubleshooting](#troubleshooting).

---

## The Developer Path (git + venv)

For people who already use Python and the terminal.

### 1. Clone

```bash
git clone https://github.com/<owner>/<repo>.git jarvis
cd jarvis
```

### 2. Virtual environment + dependencies

```bash
python3 -m venv .venv
source .venv/bin/activate         # macOS / Linux
# .\.venv\Scripts\activate       # Windows PowerShell
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

If you plan to use browser automation tools, also install Playwright's
browsers:

```bash
python -m playwright install
```

### 3. Configure

```bash
cp .env.example .env
```

Edit `.env` and set `GEMINI_API_KEY`. See step 3 of the 5-Minute Path
for the optional `GEMINI_VOICE_NAME` and other settings.

### 4. Run

```bash
jarvis
```

You can also use the launchers in `scripts/`:

- macOS: `./scripts/start_jarvis.command` (or double-click in Finder)
- Linux: `./scripts/start_jarvis.sh`
- Windows: `scripts\start_jarvis.bat` (or double-click in Explorer)

The launchers create the venv, install requirements, and check your
`.env` for a placeholder before running `main.py`.

---

## What you should see on first run

The UI window opens, the log panel prints startup lines like:

```
[JARVIS] 🔑 Validating Gemini API key...
[JARVIS] ✅ Gemini API key validated.
[Awareness] 👁️ Awareness engine started
[JARVIS] 🔌 Connecting...
[JARVIS] ✅ Connected.
[JARVIS] 🎤 Mic started
```

If you see "GEMINI_API_KEY environment variable not set" or
"Live API model not available", jump to
[Troubleshooting](#troubleshooting).

When JARVIS says its greeting out loud, the first run is complete.

---

## Things to try first

Voice or text commands:

- "What is on my screen?"
- "What's the weather in Tokyo?"
- "Search the web for noise-cancelling headphones under $200."
- "Open Chrome."
- "Set a reminder for tomorrow at 8:30 AM to call Mom."

JARVIS also accepts typed input in the UI's text field — useful when
you're in a noisy room or testing without a mic.

---

## Troubleshooting

### "GEMINI_API_KEY environment variable not set"

Your `.env` is missing, in the wrong folder, or doesn't have a real
key.

1. Confirm the file is named `.env` (with the leading dot).
2. Confirm it's in the JARVIS project root, **the same folder that
   contains `main.py`**.
3. Open it and make sure the line reads
   `GEMINI_API_KEY="your-actual-key-here"` with your real key in the
   quotes — no leftover `YOUR_GEMINI_API_KEY` placeholder.
4. Restart JARVIS.

### Instagram messaging setup

JARVIS uses its own controlled browser profile for Instagram DMs. The
first time you ask JARVIS to message someone on Instagram, it may open a
separate browser window and ask you to log in there.

1. Log into Instagram in the JARVIS browser window.
2. Leave that window signed in.
3. Ask JARVIS to send the Instagram message again.

JARVIS will type the draft and ask before sending. It should not require
Chrome's **Allow JavaScript from Apple Events** setting for Instagram.

### Microphone won't start

- **macOS:** System Settings → Privacy & Security → Microphone. Make
  sure Terminal (or whichever app launched JARVIS) is checked. Quit
  and reopen the app after toggling.
- **Windows:** Settings → Privacy → Microphone. Make sure "Let desktop
  apps access your microphone" is on.
- **Linux:** check `pavucontrol` or your distro's audio settings.
- Confirm the mic isn't already in use by another app (Zoom, a browser
  tab, etc.).

### Launcher closes immediately on macOS

The first run does a dependency install that takes minutes — if you
double-clicked and saw a Terminal window flash closed, you probably ran
an *older* version of the launcher. Re-download the ZIP or, from
Finder, right-click the launcher and choose **Open With → Terminal**
so errors stay visible.

### `pip install` fails on Linux with "externally-managed-environment"

Use the venv as documented above (`python3 -m venv .venv`). The error
means you're trying to install into the system Python, which modern
Linux distros block. The venv sidesteps it.

### Live API error: `1011 Deadline expired` / `model not available`

JARVIS will print a warning and auto-select a fallback Live model from
your account's available models. If it can't auto-select, check your
Google AI Studio project: the key must have **Live API** enabled.
Free-tier keys sometimes need billing enabled to access Live API —
see <https://aistudio.google.com/>.

### Browser automation errors (`playwright install`)

```bash
python -m playwright install
```

On Linux you may also need:

```bash
python -m playwright install-deps
```

### Voice falls back to "puck" automatically

Either you set `GEMINI_VOICE_NAME` to something not in the supported
list, or the model doesn't support the voice you chose. Pick from
`puck, charon, kore, fenrir, aoede, leda, orus, schedar,
zubenelgenubi`.

### "Contacts" permission error when sending iMessage

System Settings → Privacy & Security → Contacts → enable Terminal (or
whatever launched JARVIS). macOS asks per-app; rerun the JARVIS send
after granting.

### Reset everything

If the venv is corrupted or you just want a clean slate, **delete the
`.venv` folder** inside the JARVIS directory. The next launcher run
will recreate it and reinstall everything.

---

## Updating JARVIS later

When new commits land on GitHub:

- **ZIP users:** download a fresh ZIP and replace your JARVIS folder.
  Keep your `.env` from the old folder — copy it into the new one
  before you delete the old.
- **Git users:** `git pull`, then re-run `python -m pip install -r
  requirements.txt` if `requirements.txt` changed.

The `.env`, `config/api_keys.json`, and anything in `memory/` are
yours and won't be touched by an update.

---

## Where to go next

- `README.md` — project overview.
- `docs/USAGE.md` — daily-usage commands and example workflows.
- `CONTRIBUTING.md` — if you want to send a pull request.
- The GitHub Issues tab — bug reports and feature requests.
