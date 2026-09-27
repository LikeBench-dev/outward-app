---
name: outward-app-start-here
description: Use at the start of any Outward App repository task before modifying, reviewing, debugging, or explaining the app; it routes Codex to the maintained project overview first.
---

# Outward App Start Here

At the beginning of any task in `C:\Home Projects\outward-app`, first load the `outward-app-overview` skill and use it as the project map.

If the skill is not listed by the runtime yet, read this file directly:

```text
C:\Home Projects\outward-app\.codex\skills\outward-app-overview\SKILL.md
```

After reading the overview, inspect only the source files relevant to the user's request unless the user asks for a fresh audit or the overview appears stale. Let the overview guide where to look, but verify source code before making behavioral changes.

When a task changes repository files, read this file directly and use it to decide whether the versioned release notes file needs an entry:

```text
C:\Home Projects\outward-app\.codex\skills\outward-release-notes\SKILL.md
```

When a task changes major app behavior, architecture, runtime file locations, connect/disconnect flow, packaging, or testing conventions, update `outward-app-overview` as part of the same work.
