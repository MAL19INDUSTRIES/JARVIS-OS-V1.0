# JARVIS

Local Gemini Live desktop assistant with a PyQt6 interface, voice interaction, detachable panels, and optional browser, file, screen, and messaging tools.

Created and maintained by **AMDCREATIONZ**:

- GitHub: [MAL19INDUSTRIES](https://github.com/MAL19INDUSTRIES)
- Instagram: [@AMDCREATIONZ](https://www.instagram.com/AMDCREATIONZ/)

This project is publicly available under the MIT License. Anyone may use,
copy, modify, and distribute it while retaining the included copyright and
license notice.

JARVIS also includes a dedicated presentation studio that creates, edits,
redesigns, and extends editable widescreen `.pptx` decks from documents, data,
images, audio, and video, with optional PDF export. See the
[usage guide](docs/USAGE.md#6-powerpoint-presentations) for examples.

The desktop assistant can also build local websites and open them in its
integrated responsive preview. Automatically generated sites are kept in the
signed-in user's `Documents/JARVIS Websites` folder. The preview supports
desktop, tablet, and mobile widths and follows the active JARVIS, ULTRON, or
ATLAS interface while preserving the persona that created the site. Website
creation uses a staged React, Vite, and Tailwind workflow: JARVIS presents three
design directions, waits for a selection, displays the exact npm manifest, and
installs nothing until the user explicitly approves it. Pasted 21st.dev prompts
are supported as untrusted design references; JARVIS does not scrape the site.
Website work runs in a clean full-window focus workspace: dashboard analytics,
comms, rails, and application controls are hidden. A compact instance of the
real persona orb remains in the lower-right and opens an Enter-to-send mini chat.
Generated sites prohibit native 3D models, WebGL, Three.js, React Three Fiber,
Spline, Babylon, model-viewer, GLB, and GLTF output.

## Requirements

You need **Python 3.11 or newer** installed to set up and run JARVIS. Confirm
your Python version before continuing:

```bash
python --version
```

## Quick start (Windows, macOS, Linux)

In Terminal, run:

```bash
git clone https://github.com/MAL19INDUSTRIES/JARVIS-OS-V.2.git
cd JARVIS-OS-V.2
python scripts/setup_jarvis.py
```

On Windows, you can double-click `scripts/setup_jarvis.bat` instead.

Open `.env`, add your `GEMINI_API_KEY`, then launch JARVIS:

```bash
jarvis
```

You only need to run setup once. Activate `.venv` when opening a new terminal,
then type `jarvis`.

JARVIS's core UI, Gemini connection, presentations, research, files, and CLI are
cross-platform. Some computer-control, email, media, and browser integrations
depend on permissions and available applications on each operating system.

## iPhone companion

Phone Link now uses an [Apple Shortcut](docs/IPHONE_SHORTCUT.md) as the native
iPhone action layer on the same local Wi-Fi network. The shortcut can run from
the Home Screen, Siri, a widget, or the Action button without a QR or permanent
browser session. JARVIS opens a signed Shortcut installer and copies its private
connection code automatically, so no actions need to be assembled by hand. A
normal run is voice-first: say “Siri, JARVIS,” or tap once and speak without
opening the Shortcuts app or typing. A standalone
[native companion](ios/JARVISPhone/README.md)
remains under development and is not distributed through TestFlight or the App
Store.

## Hosted web application

The repository also contains a multi-user FastAPI service and a Next.js web
client. Hosted sessions use Postgres for user-scoped memory and configuration,
Redis for request quotas, encrypted per-user Gemini keys, and Gemini Live over
an authenticated WebSocket. The desktop launcher continues to use its local
stores and full local action inventory.

Start the complete local web stack with Docker:

```bash
docker compose up --build
```

Then open `http://localhost:3000`. To run each service directly:

```bash
# API
cp .env.example .env
alembic upgrade head
uvicorn api.server:app --reload

# Web client
cd web
cp .env.example .env.local
npm install
npm run dev
```

Production templates are included for Fly.io (`fly.toml`), Render
(`render.yaml`), and Vercel (`web/vercel.json`). Configure `DATABASE_URL`,
`REDIS_URL`, `JWT_SECRET`, `JARVIS_ENCRYPTION_KEY`, and `CORS_ORIGINS` on the
API host. Configure `NEXT_PUBLIC_API_URL` and `NEXT_PUBLIC_WS_URL` on Vercel.
The deployment workflow runs manually after the Fly and Vercel repository
secrets have been added.

## Manual setup

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install --upgrade pip
python3 -m pip install -r requirements.txt
cp .env.example .env
./scripts/install_jarvis_cli.sh
jarvis
```

Set `GEMINI_API_KEY` in `.env` before launch. Optional settings such as voice and local API keys are documented in `.env.example`.

### Launch with `jarvis`

The CLI launcher is included in this repository. After cloning and completing
the one-time setup, install it for your user with:

```bash
./scripts/install_jarvis_cli.sh
```

Open a new terminal (or reload your shell profile), then start JARVIS with:

```bash
jarvis
```

Before packaging or releasing the desktop app, run the side-effect-safe
capability audit:

```bash
jarvis --self-test
```

The audit exercises voice/tool contracts, messaging routing and approval
boundaries, a local browser interaction, isolated file operations, vision,
agent recovery, and memory. It never sends a real message or performs a live
desktop mutation. Results that still require a person, account, or physical
device are labeled `LIVE CHECK REQUIRED`, and a JSON report is written under
`.qa-artifacts/`.

Alternatively, from an activated virtual environment, `python3 -m pip install -e .`
installs the same `jarvis` command through the standard Python package entry point.

## Documentation

- [Usage guide](docs/USAGE.md)
- [Tutorial](docs/TUTORIAL.md)
- [Complete QA and bug-audit guide](docs/QA.md)
- [Contribution notes](CONTRIBUTING.md)

## Configuration files

Template files are included for local setup:

- `.env.example`
- `config/api_keys.example.json`
- `config/layout_settings.example.json`
- `config/ui_settings.example.json`
- `memory/long_term.example.json`
- `memory/task_history.example.json`

## Publishing checklist

- Keep `.env` and local secret files out of git.
- Do not commit `memory/long_term.json` or `config/api_keys.json`.
- Run `python3 -m py_compile main.py ui.py` before tagging a release.

## License

MIT License, see [LICENSE](LICENSE). Copyright © 2026 AMDCREATIONZ
(GitHub: MAL19INDUSTRIES).
