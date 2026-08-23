# JARVIS Quality Assurance

The QA system has two stages. Automated checks are always run first. Supervised checks then exercise real macOS audio, permissions, displays, and integrations while QA safety rules remain active.

## Automated audit

```bash
python3 scripts/qa.py automated
```

This enables `JARVIS_QA_MODE`, creates an isolated workspace, compiles the runtime, checks installed dependencies, runs the complete test suite, scans tracked files for Gemini key patterns, audits tool declarations, and writes redacted Markdown and JSON reports under `.qa-artifacts/`.

## Supervised macOS audit

Automate every safe checklist item first:

```bash
python3 scripts/qa.py checklist-auto
```

This command is non-interactive. It tests startup gating, mocked key recovery, selected-voice wiring, PCM subtitle timing, device enumeration, UI sizes, themes, graphics, localhost browser automation, sandboxed files, safety blocks, screen permission state, tool contracts, and short stability. Results that require human hearing, private message access, physical display movement, or real macOS state changes are labelled `partial`, `blocked`, or `manual-required`; they are never falsely marked passed.

Use a longer automatic stability sample if desired:

```bash
python3 scripts/qa.py checklist-auto --stability-seconds 300
```

For the remaining perception and device checks, start the supervised checklist:

Start the checklist:

```bash
python3 scripts/qa.py live
```

The runner prints a unique QA workspace. In another terminal, launch JARVIS with the two environment values it displays. Record pass, fail, blocked, or skipped for each case.

Optional supervised capabilities must be enabled individually:

```bash
JARVIS_QA_ALLOW_BROWSER=1
JARVIS_QA_ALLOW_DESKTOP=1
JARVIS_QA_ALLOW_DRAFTS=1
JARVIS_QA_ALLOW_REMINDERS=1
JARVIS_QA_ALLOW_MEMORY=1
```

Real message sending, computer shutdown/restart, connectivity changes, game installation/update, and file writes outside the QA workspace remain blocked even when optional capabilities are enabled.

To collect a 30-minute stability sample from a running JARVIS process:

```bash
python3 scripts/qa.py live --pid JARVIS_PID --soak-minutes 30
```

## Reports and bug handling

```bash
python3 scripts/qa.py report
```

Every finding includes severity, subsystem, impact, reproduction guidance, expected behavior, and actual evidence. Treat P0 as blocking, P1 as release-critical, P2 as a planned correction, and P3 as polish. Establish the report first, fix bugs in separate batches, then rerun both audit stages.
