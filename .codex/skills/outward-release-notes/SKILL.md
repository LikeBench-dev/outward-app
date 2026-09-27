---
name: outward-release-notes
description: Maintain Outward App release notes whenever repository changes add, fix, remove, or otherwise alter user-visible behavior, packaging, update flow, supported protocols, settings, or tests.
---

# Outward Release Notes

Use this skill when making or reviewing changes in `C:\Home Projects\outward-app` that should be visible in the next release. The goal is to keep release notes useful to users instead of publishing only installer checksums.

## What To Update

- Find the current app version in `VERSION`.
- Keep `release-notes.md` in the repository root as the editable release body source for the current version.
- The build script reads `release-notes.md` by default, writes `installer-output/release-notes-<version>.md`, and appends the installer SHA256.
- If `release-notes.md` does not exist yet, create it with an empty `## Changes` section. Do not include a version heading in this source file unless there is a specific reason.
- Keep the `## SHA256` section for checksum lines, but do not let it be the only meaningful content unless the code change truly has no user-facing effect.

## Writing Rules

- Add concise bullets under `## Changes` for user-visible changes, bug fixes, packaging changes, protocol support, update behavior, settings, runtime-file behavior, and notable test coverage.
- Write release-note bullets in the same language as the surrounding file when it is already established; otherwise prefer Russian for this repository's user-facing notes.
- Do not expose secrets, internal tokens, raw proxy credentials, WireGuard private keys, or unrelated implementation churn.
- Avoid repeating commit messages verbatim when a clearer user-facing summary is possible.
- If a change is purely internal and has no release-note value, leave the file unchanged and mention that decision in the final response.

## Placement

Keep the generated versioned release notes shape:

```markdown
# Outward App <version>

## Changes

- ...

## SHA256

<checksum>  Outward App Setup-<version>.exe
```

When adding a change before the installer is built, add it to root `release-notes.md` under `## Changes`; the build script adds the version heading and `## SHA256` section.

## Final Check

Before finishing a repository change, check whether release notes need an entry. In the final response, say whether release notes were updated and name `release-notes.md` or the generated versioned file as appropriate.


