# Outward App: Windows Qt integration

This is the local adaptation of Impeccable for the existing PySide6 desktop application. The user requested preservation of its current design and help with frontend development.

## Load and preserve

Read the project overview at `.codex/skills/outward-app-overview/SKILL.md`, root `PRODUCT.md` and `DESIGN.md`, then the relevant source. Existing code and the user's request are the visual authority. The usual app-screen mode is Operate: prioritize task clarity, state, consistency and native interaction.

Read only the playbook relevant to the request: `polish.md`, `layout.md`, `typeset.md`, `harden.md`, `clarify.md`, `audit.md`, `critique.md`, or `extract.md`. Read `craft-floor.md` before UI edits. A request for a new feature normally extends the incumbent system; it does not authorize a new visual world, fonts or palette. Preserve the Segoe UI type, approved Graphite light/dark semantic palettes, flat bordered panels and compact control radii recorded in DESIGN.md. `ui/themes.py` is the source for QSS, palette, painter and rich-text colors; keep the immediate, independently persisted theme selector working. These explicit project decisions override generic aesthetic bans in upstream references, including selected-row accents and existing text glyphs; assess any actual usability defect separately.

## Translate to the actual frontend

- Components are Qt widgets, shared builders, object names and dynamic QSS properties. Layout uses QVBoxLayout/QHBoxLayout/QGridLayout, stretch, size policies and scroll areas.
- Use QSS-supported properties; browser CSS features, Tailwind, DOM semantics and ARIA do not apply. Check the effective widget type before assuming a stylesheet selector matches.
- Map accessibility advice to Qt focus policy, tab order, keyboard activation, accessibleName/accessibleDescription and QLabel buddies where applicable. Custom controls require their own keyboard and accessibility assessment.
- Map responsive advice to minimum/normal window sizes, Windows DPI scaling and long Russian copy. Do not copy mobile device breakpoints or touch targets into desktop requirements indiscriminately.
- Preserve the worker threads/signals for connect, disconnect and updates. Visual changes must not start blocking network or process work on the GUI thread.
- Keep actual protocol availability and state transitions intact. Do not expose profile secrets in examples or captures.

## Engine and browser-only features

For Qt tasks, read context files directly. Do not run the Impeccable engine, automatic design hooks, DOM detector, browser overlay, live/generate workflow, web dev server setup or catalog/image-generation pipeline as part of ordinary desktop UI work. They do not establish Qt rendering or accessibility correctness. Engine-specific steps in a playbook, such as critique-storage commands, have no required Qt equivalent; keep review findings in the task unless the user asks to save them.

If a user explicitly asks for live/generate against the Qt window, explain that browser mode does not attach to Qt Widgets and proceed with a source-based Qt refinement or native visual check appropriate to their request. Web-specific hooks or tooling are a separate setup task if a real web frontend is later added.

This installation contains the upstream scripts and references for completeness, but no engine binary or hooks were installed or run. Do not represent this project adaptation as official Impeccable Qt support.

## Verify proportionally

For UI edits, inspect the actual Qt result when the environment permits; use synthetic profile data and avoid triggering a connection, startup registration or an update installation just to review appearance. Validate the changed path's states, keyboard focus, long labels and resize/DPI behavior. A historical screenshot, static source review or successful web detector is not proof of the current Qt render. State clearly when rendering was not checked.

Use `.\.venv\Scripts\python.exe -m unittest discover -s tests` for changes affecting behavior; run relevant focused checks rather than inventing tests for cosmetic-only or documentation changes. Check `outward-release-notes` for user-visible changes and maintain DESIGN.md when intentional visual system decisions change.
