# Third-Party Notices

This project includes content derived from third-party work, used under the terms of its original license.

## Platform Design Skills

The `skill/reference/ios.md` and `skill/reference/android.md` platform reference files are distilled from ehmo's `platform-design-skills` (Apple Human Interface Guidelines and Material Design 3 rules), rewritten in Impeccable's voice.

**Original work:** https://github.com/ehmo/platform-design-skills
**Original license:** MIT
**Author:** ehmo

## Outward App project copy

Source: https://github.com/pbakaus/impeccable
Pinned commit: c3bb418ee38ee49a6b999b7752c1368f3123a2bd
Upstream skill version: 4.8.0
Installed: 2026-11-06

Local modifications: SKILL.md adds Windows/PySide6 discovery and routes Outward App UI work through reference/outward-qt.md, a new project-specific adaptation. All other upstream skill files are retained as distributed. The project router loads this integration and root PRODUCT.md/DESIGN.md. No engine binary, browser integration or design hooks were enabled.

To update, review a new upstream revision and reapply the Qt integration; a blind replacement of this folder loses the project-specific routing. The Apache-2.0 license in this folder applies to upstream Impeccable material and is separate from the Outward App source and asset licenses.
